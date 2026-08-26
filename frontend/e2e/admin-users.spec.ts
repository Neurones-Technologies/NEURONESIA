import { randomUUID } from "node:crypto";

import { test, expect } from "@playwright/test";

import { DEMO_EMAILS, demoPassword } from "./support/demo-credentials";

/**
 * Écran Comptes — cycle complet sur un compte jetable.
 *
 * UNE SEULE connexion pour tout le fichier, et c'est une contrainte, pas un
 * raccourci : `/v1/auth/login` est rate-limité à 5/minute par IP et les
 * tentatives échouées comptent aussi (cf. `auth-vision-flow.spec.ts`, qui en
 * consomme déjà deux, plus une chacun pour dc-sections et df-sections). Une
 * connexion supplémentaire ferait tomber la suite entière sur des 429 sans
 * rapport avec ce qui est testé.
 *
 * Conséquence : le refus opposé à un NON-admin n'est pas vérifié ici, faute de
 * seconde session. Il l'est côté serveur, où il compte vraiment — les neuf
 * endpoints d'administration sont testés en 403 pour un non-admin
 * (`backend/tests/unit/test_admin_users.py`). Ce qui est vérifié ici sans
 * session : une page protégée renvoie bien vers /login (le proxy), ce qui ne
 * coûte aucune connexion.
 *
 * Le compte créé porte un identifiant aléatoire : le test est relançable sans
 * buter sur le 409 « email déjà utilisé », et deux exécutions concurrentes ne se
 * marchent pas dessus.
 */
test.describe("Écran Comptes (admin)", () => {
  test.describe.configure({ mode: "serial" });

  const suffixe = randomUUID().slice(0, 8);
  const emailJetable = `e2e-${suffixe}@neuronestech.com`;
  // Mot de passe jetable généré au vol : rien de nouveau n'entre dans le dépôt,
  // et ce compte est supprimé à la fin du fichier.
  const motDePasseJetable = randomUUID().slice(0, 16);

  test("sans session, l'écran renvoie vers la connexion", async ({ page }) => {
    await page.goto("/dg/admin");

    await expect(page).toHaveURL(/\/login\?next=%2Fdg%2Fadmin/);
    await expect(page.getByRole("heading", { name: "Connexion" })).toBeVisible();
  });

  test("crée, modifie, désactive puis supprime un compte", async ({ page }) => {
    // ── Connexion (la seule du fichier) ──
    await page.goto("/login");
    await page.locator("#email").fill(DEMO_EMAILS.admin);
    await page.locator("#password").fill(demoPassword());
    await page.getByRole("button", { name: "Se connecter" }).click();
    // L'admin n'a pas de cockpit propre : il atterrit sur celui du DG.
    await page.waitForURL("**/dg/vision");

    // ── L'entrée de rail n'existe que pour un admin ──
    const railComptes = page.getByRole("link", { name: "Comptes" });
    await expect(railComptes).toBeVisible();
    await railComptes.click();
    await page.waitForURL("**/dg/admin");
    await expect(page.getByRole("heading", { name: "Comptes et droits" })).toBeVisible();

    // ── Création, dans une modale ouverte par l'en-tête du bloc ──
    await page.getByRole("link", { name: "Nouveau compte" }).click();
    const creation = page.getByRole("dialog", { name: "Créer un compte" });
    await expect(creation).toBeVisible({ timeout: 20_000 });
    // La modale vit dans l'URL, comme la fiche : son lien se partage.
    await expect(page).toHaveURL(/nouveau=1/);

    await creation.getByLabel("Adresse e-mail").fill(emailJetable);
    await creation.getByLabel("Nom complet").fill(`Compte jetable ${suffixe}`);
    await creation.getByLabel("Rôle").selectOption("commercial");
    await creation.getByLabel("Mot de passe initial").fill(motDePasseJetable);
    await creation.getByRole("button", { name: "Créer le compte" }).click();

    await expect(creation.getByRole("status")).toContainText(emailJetable, { timeout: 20_000 });

    // La modale reste ouverte sur son message : c'est un geste refermé à la main.
    await creation.getByRole("link", { name: "Fermer" }).click();
    await expect(creation).toBeHidden({ timeout: 20_000 });

    // ── Le filtrage est fait par le serveur : la liste doit se réduire ──
    await page.getByLabel("Rechercher").fill(suffixe);
    const ligne = page.getByRole("row").filter({ hasText: emailJetable });
    await expect(ligne).toHaveCount(1, { timeout: 20_000 });
    await expect(ligne).toContainText("actif");

    // ── Ouverture de la fiche : une navigation, pas un état client ──
    // La modale est nommée par le compte qu'elle porte — deux fiches ouvertes
    // successivement ne se confondent donc pas dans les traces du test.
    await ligne.getByRole("link").first().click();
    const fiche = page.getByRole("dialog", { name: `Compte jetable ${suffixe}` });
    await expect(fiche).toBeVisible({ timeout: 20_000 });
    // La modale ne porte plus que des champs : l'adresse y est une VALEUR
    // modifiable, pas un texte affiché.
    await expect(fiche.getByLabel("Adresse e-mail")).toHaveValue(emailJetable);
    // L'URL porte la fiche ouverte ET conserve la recherche en cours.
    await expect(page).toHaveURL(new RegExp(`q=${suffixe}.*compte=\\d+`));

    // ── Changement de rôle ──
    const identite = fiche
      .locator("form")
      .filter({ has: page.getByRole("button", { name: "Enregistrer" }) });
    await identite.getByLabel("Rôle").selectOption("dir_operations");
    await identite.getByRole("button", { name: "Enregistrer" }).click();
    await expect(identite.getByRole("status")).toContainText("Direction des opérations", {
      timeout: 20_000,
    });

    // ── Désactivation ──
    const statut = fiche
      .locator("form")
      .filter({ has: page.getByRole("button", { name: "Désactiver" }) });
    await statut.getByRole("button", { name: "Désactiver" }).click();
    await expect(statut.getByRole("status")).toContainText("désactivé", { timeout: 20_000 });
    await expect(fiche).toContainText("Réactiver");

    // ── Suppression : le bouton reste inerte tant que l'adresse n'est pas recopiée ──
    const suppressionBtn = fiche.getByRole("button", { name: "Supprimer définitivement" });
    await expect(suppressionBtn).toBeDisabled();
    await fiche.getByLabel(`Recopier ${emailJetable}`).fill(emailJetable);
    await expect(suppressionBtn).toBeEnabled();
    await suppressionBtn.click();

    // La fiche survit à la suppression du compte (l'URL porte encore son id) et
    // dit ce qui s'est passé au lieu de tomber en erreur.
    await expect(page.getByRole("heading", { name: "Ce compte n'existe plus" })).toBeVisible({
      timeout: 20_000,
    });
    await page.getByRole("link", { name: "Revenir à la liste" }).click();

    // ── Le journal garde la trace des quatre actions ──
    await page.goto("/dg/admin");
    const journal = page
      .locator(".pblk")
      .filter({ hasText: "Journal d'administration" })
      .locator("table.tb");
    await expect(journal).toContainText("Compte créé");
    await expect(journal).toContainText("Compte supprimé");
    await expect(journal.getByRole("row").filter({ hasText: emailJetable })).not.toHaveCount(0);
  });
});
