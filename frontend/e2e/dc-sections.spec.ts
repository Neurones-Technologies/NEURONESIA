import { test, expect, type Cookie } from "@playwright/test";

// Nécessite un backend joignable (BACKEND_URL) avec les comptes démo seedés
// via `python backend/scripts/seed_demo_users.py` — même prérequis que
// auth-vision-flow.spec.ts.
//
// Le cockpit DC est le seul profil en navigation PAR ROUTE : chaque onglet est une
// page distincte, et une entrée de `VISION_SECTIONS.dc` sans entrée correspondante
// dans le registre `DC_SECTIONS` (ou l'inverse) produit un 404 que rien ne signale
// au développement. Ce test parcourt les onglets déclarés et vérifie qu'ils rendent
// tous — c'est la seule protection contre un menu qui pointe dans le vide.
//
// Les onglets DC appellent le backend en composant serveur : une page qui rend son
// `main.canvas` prouve que l'appel a abouti ET que la désérialisation a tenu.

const SECTIONS = [
  "pipeline",
  "objectifs",
  "comptes",
  "base-installee",
  "pipe-qualite",
  "cycle-vie",
  "mix-offre",
  "marche",
  "equipe",
  "transformation",
  "visites",
] as const;

test.describe("Cockpit DC — les onglets rendent tous", () => {
  // UNE SEULE connexion pour tout le fichier, et sa session est réinjectée dans
  // chaque contexte. Deux raisons, la seconde étant la plus contraignante :
  //
  // - ce test porte sur le RENDU des onglets, pas sur le parcours de connexion
  //   (couvert par auth-vision-flow.spec.ts) : remplir le formulaire à chaque cas
  //   ferait payer la double redirection /login → /dc/vision → /dc/vision/pipeline,
  //   soit un préambule plus lent que le test lui-même ;
  // - `/v1/auth/login` est limité à 5 appels par minute et par IP côté backend
  //   (cf. api/v1/auth.py). Se connecter à chaque cas faisait échouer les tests à
  //   partir du cinquième, sur un 429 qui n'avait rien à voir avec les pages.
  let session: Cookie[] = [];

  test.beforeAll(async ({ playwright, baseURL }) => {
    const api = await playwright.request.newContext({ baseURL });
    const reponse = await api.post("/api/auth/login", {
      data: { email: "pbourron@neuronestech.com", password: "neurones2026" },
    });
    expect(reponse.ok(), "connexion du compte démo DC").toBeTruthy();
    session = (await api.storageState()).cookies;
    await api.dispose();
  });

  test.beforeEach(async ({ context }) => {
    await context.addCookies(session);
  });

  for (const section of SECTIONS) {
    test(`/dc/vision/${section} rend son contenu`, async ({ page }) => {
      const reponse = await page.goto(`/dc/vision/${section}`);
      expect(reponse?.status(), `statut HTTP de /dc/vision/${section}`).toBe(200);
      await expect(page.locator("main.canvas")).toBeVisible();
      // Une tuile au moins : une page qui rendrait un canvas vide passerait
      // l'assertion précédente sans rien afficher.
      await expect(page.locator(".tile, .brief").first()).toBeVisible();
    });
  }

  // La cadence de lecture vit dans l'URL : elle doit survivre à un rechargement et
  // rester partageable par lien (c'est sa raison d'être face à un état client).
  // Deux segmentés cohabitent (cadence, puis exercice) : le sélecteur cible le
  // premier par son libellé accessible, sinon les deux liens actifs remontent.
  test("la cadence de lecture est portée par l'URL", async ({ page }) => {
    const cadence = page.getByRole("navigation", { name: "Cadence de lecture" });
    await page.goto("/dc/vision/objectifs?periode=mois");
    await expect(cadence.locator('a[aria-current="page"]')).toHaveText("Mensuel");
    await page.goto("/dc/vision/objectifs?periode=annee");
    await expect(cadence.locator('a[aria-current="page"]')).toHaveText("Annuel");
    // Une valeur absurde retombe sur le défaut de l'onglet plutôt que de vider l'écran.
    await page.goto("/dc/vision/objectifs?periode=nimportequoi");
    await expect(cadence.locator('a[aria-current="page"]')).toHaveText("Trimestriel");
  });

  // Une section inventée doit tomber en 404 plutôt que rendre une page vide.
  test("une section inconnue répond 404", async ({ page }) => {
    const reponse = await page.goto("/dc/vision/section-inexistante");
    expect(reponse?.status()).toBe(404);
  });
});
