import { test, expect, type Cookie } from "@playwright/test";

// Nécessite un backend joignable (BACKEND_URL) avec les comptes démo seedés
// via `python backend/scripts/seed_demo_users.py` — même prérequis que
// auth-vision-flow.spec.ts et dc-sections.spec.ts.
//
// Le cockpit DAF est, comme le DC, en navigation PAR ROUTE : chaque onglet est une
// page distincte, et une entrée de `VISION_SECTIONS.df` sans entrée correspondante
// dans le registre `DF_SECTIONS` (ou l'inverse) produit un 404 que rien ne signale
// au développement. Ce test parcourt les onglets déclarés et vérifie qu'ils rendent
// tous — c'est la seule protection contre un menu qui pointe dans le vide.
//
// Les onglets DAF appellent le backend en composant serveur : une page qui rend son
// `main.canvas` prouve que l'appel a abouti ET que la désérialisation a tenu. Les
// endpoints financiers agrègent 2 957 factures, 2 133 achats et 2 408 dossiers en
// Python : ce test est aussi le garde-fou contre une régression qui ferait tomber
// l'un de ces calculs sur les données réelles.

const SECTIONS = ["encours", "budget", "relation-commerciale", "tresorerie"] as const;

test.describe("Cockpit DAF — les onglets rendent tous", () => {
  // Exécution SÉRIELLE, et c'est la seule raison : `beforeAll` est rejoué par
  // chaque worker Playwright, or `/v1/auth/login` est limité à 5 appels par minute
  // et par IP côté backend (cf. api/v1/auth.py). En parallèle, ce fichier ouvrait
  // autant de sessions que de workers et le cinquième cas tombait sur un 429 qui
  // n'avait rien à voir avec les pages testées. En sériel, une seule connexion est
  // ouverte pour tout le fichier.
  test.describe.configure({ mode: "serial" });

  let session: Cookie[] = [];

  test.beforeAll(async ({ playwright, baseURL }) => {
    const api = await playwright.request.newContext({ baseURL });
    const reponse = await api.post("/api/auth/login", {
      data: { email: "cdjereke@neuronestech.com", password: "neurones2026" },
    });
    expect(reponse.ok(), "connexion du compte démo DAF").toBeTruthy();
    session = (await api.storageState()).cookies;
    await api.dispose();
  });

  test.beforeEach(async ({ context }) => {
    await context.addCookies(session);
  });

  for (const section of SECTIONS) {
    test(`/df/vision/${section} rend son contenu`, async ({ page }) => {
      const reponse = await page.goto(`/df/vision/${section}`);
      expect(reponse?.status(), `statut HTTP de /df/vision/${section}`).toBe(200);
      await expect(page.locator("main.canvas")).toBeVisible();
      // Une tuile au moins : une page qui rendrait un canvas vide passerait
      // l'assertion précédente sans rien afficher.
      await expect(page.locator(".tile, .brief").first()).toBeVisible();
    });
  }

  // L'atterrissage a été demandé « sur une vue calendaire » : la grille de mois est
  // la forme livrée, pas un tableau. Si elle disparaît, la demande n'est plus servie.
  test("l'atterrissage rend une grille calendaire de mois", async ({ page }) => {
    await page.goto("/df/vision/tresorerie");
    const calendrier = page.locator(".daf-cal");
    await expect(calendrier).toBeVisible();
    // Douze mois d'exercice au minimum (l'horizon peut en ajouter au-delà).
    expect(await calendrier.locator(".daf-m").count()).toBeGreaterThanOrEqual(12);
    // Le mois en cours est distingué du mesuré et du projeté : c'est ce marquage
    // qui empêche de lire une prévision comme un constat.
    await expect(calendrier.locator(".daf-m--c")).toHaveCount(1);
  });

  // Les graphes sont du SVG rendu par le SERVEUR : s'ils disparaissent, c'est que
  // la série n'est plus servie par l'API ou que le composant a cessé de rendre —
  // dans les deux cas la page reste « verte » sur les tests précédents, puisque
  // ses tuiles s'affichent toujours. D'où ce cas, qui compte les tracés.
  test("les séries temporelles rendent leurs graphes", async ({ page }) => {
    await page.goto("/df/vision/relation-commerciale");
    // Courbe d'encours par ancienneté + courbe de DSO glissant.
    await expect(page.locator(".cht-svg")).toHaveCount(2);
    // Une légende accompagne toute pile de séries : l'identité ne doit jamais
    // reposer sur la seule couleur.
    await expect(page.locator(".cht-lg").first()).toBeVisible();

    await page.goto("/df/vision/budget");
    // Burn-down, marge par exercice, Pareto des charges.
    await expect(page.locator(".cht-svg")).toHaveCount(3);

    await page.goto("/df/vision/tresorerie");
    await expect(page.locator(".cht-svg")).toHaveCount(1);
  });

  // L'exercice vit dans l'URL : il doit survivre à un rechargement et rester
  // partageable par lien (c'est sa raison d'être face à un état client).
  //
  // Le sélecteur n'est rendu QUE si le miroir porte au moins deux exercices
  // (cf. df/exercice-nav.tsx : `proposes.length <= 1` ne rend rien). Sur une base
  // vide — le cas du CI, qui ne seed que les comptes démo — il est donc absent, et
  // ce cas échouait sur un « element(s) not found » qui ne disait rien de la
  // fonctionnalité. On lit les exercices réellement proposés plutôt que d'en coder
  // un en dur, et on ne teste la sélection que s'il y a un sélecteur à tester.
  test("l'exercice est porté par l'URL", async ({ page }) => {
    const exercice = page.getByRole("navigation", { name: "Exercice" });

    await page.goto("/df/vision/budget");
    await expect(page.locator(".tile, .brief").first()).toBeVisible();
    const annees = await exercice.locator("a").allInnerTexts();
    test.skip(annees.length === 0, "aucun exercice proposé : miroir sans données");

    // Un exercice AUTRE que celui par défaut, pour que la sélection prouve quelque
    // chose : viser le défaut passerait même si `?annee=` était ignoré.
    const defaut = await exercice.locator('a[aria-current="page"]').innerText();
    const cible = annees.find((a) => a !== defaut) ?? defaut;
    await page.goto(`/df/vision/budget?annee=${cible}`);
    await expect(exercice.locator('a[aria-current="page"]')).toHaveText(cible);

    // Une année absurde retombe sur le défaut serveur (exercice courant) plutôt
    // que de vider l'écran sans explication.
    await page.goto("/df/vision/budget?annee=1899");
    await expect(page.locator(".tile, .brief").first()).toBeVisible();
    await expect(exercice.locator('a[aria-current="page"]')).not.toHaveText("1899");
  });

  // Une section inventée doit tomber en 404 plutôt que rendre une page vide.
  test("une section inconnue répond 404", async ({ page }) => {
    const reponse = await page.goto("/df/vision/section-inexistante");
    expect(reponse?.status()).toBe(404);
  });

  // « Formation et qualité » a été retiré du cockpit. Le retirer du seul menu
  // l'aurait masqué à l'œil en laissant l'URL servir la page : ce cas vérifie les
  // deux faces du retrait — plus d'onglet, et plus de route.
  test("le volet formation n'est ni affiché ni atteignable", async ({ page }) => {
    await page.goto("/df/vision/encours");
    await expect(page.getByRole("link", { name: /formation/i })).toHaveCount(0);

    const reponse = await page.goto("/df/vision/formation");
    expect(reponse?.status(), "statut HTTP de /df/vision/formation").toBe(404);
  });

  // `/df/vision` n'est plus une page : elle redirige vers la première section.
  test("la racine du cockpit DAF redirige vers la première section", async ({ page }) => {
    await page.goto("/df/vision");
    await expect(page).toHaveURL(/\/df\/vision\/encours$/);
  });
});
