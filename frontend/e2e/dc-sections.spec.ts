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

// Les quatorze écrans, dans l'ordre des six chapitres du compte-rendu.
const SECTIONS = [
  // 1. Pilotage stratégique du portefeuille
  "marche",
  "base-installee",
  "pics",
  // 2. Suivi commercial par compte
  "comptes",
  "cycle-vie",
  // 3. Prospection et performance commerciale
  "efficacite",
  "prospection",
  // 4. Analyse sectorielle et pipeline
  "secteurs",
  "pipeline",
  "pipe-qualite",
  "objectifs",
  "mix-offre",
  // 5. Aide à la décision
  "transformation",
  // 6. Traçabilité terrain
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

  // Le menu est à deux niveaux : les six chapitres du compte-rendu en haut, les
  // écrans du chapitre ouvert en dessous. Ce test protège les deux propriétés qui
  // font tenir ce dessin : le chapitre de la section courante est surligné même
  // quand on l'atteint par lien direct, et la seconde rangée ne montre que ses
  // écrans — pas les quatorze.
  test("le chapitre actif et ses écrans suivent la section ouverte", async ({ page }) => {
    const chapitres = page.getByRole("navigation", { name: "Chapitres de la vue" });
    const ecrans = page.getByRole("navigation", { name: "Écrans du chapitre" });

    await page.goto("/dc/vision/pics");
    await expect(chapitres.locator('a[aria-current="page"]')).toHaveText("Pilotage stratégique");
    await expect(ecrans.locator("a")).toHaveText([
      "Tendances et marché",
      "Animation de compte",
      "Pics et alertes",
    ]);
    await expect(ecrans.locator('a[aria-current="page"]')).toHaveText("Pics et alertes");

    await page.goto("/dc/vision/cycle-vie");
    await expect(chapitres.locator('a[aria-current="page"]')).toHaveText("Suivi par compte");
    await expect(ecrans.locator("a")).toHaveCount(2);
  });

  // Un chapitre à un seul écran n'affiche pas de seconde rangée : elle ne
  // proposerait qu'un onglet, déjà actif.
  test("un chapitre à un seul écran n'a pas de seconde rangée", async ({ page }) => {
    await page.goto("/dc/vision/visites");
    await expect(page.getByRole("navigation", { name: "Chapitres de la vue" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Écrans du chapitre" })).toHaveCount(0);
  });

  // Une section inventée doit tomber en 404 plutôt que rendre une page vide.
  test("une section inconnue répond 404", async ({ page }) => {
    const reponse = await page.goto("/dc/vision/section-inexistante");
    expect(reponse?.status()).toBe(404);
  });
});
