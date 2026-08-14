import { test, expect, type Cookie } from "@playwright/test";

// Nécessite un backend joignable (BACKEND_URL) avec les comptes démo seedés
// via `python backend/scripts/seed_demo_users.py` — même prérequis que
// auth-vision-flow.spec.ts.
//
// Le cockpit DC est en navigation PAR ROUTE : chaque page est une route distincte,
// et une entrée de `VISION_SECTIONS.dc` sans entrée correspondante dans le registre
// `DC_SECTIONS` (ou l'inverse) produit un 404 que rien ne signale au développement.
// Ce test parcourt les pages déclarées et vérifie qu'elles rendent toutes — c'est la
// seule protection contre un menu qui pointe dans le vide.
//
// Les pages DC appellent le backend en composant serveur : une page qui rend son
// `main.canvas` prouve que l'appel a abouti ET que la désérialisation a tenu.

// Les sept pages servies. Toutes doivent rendre, y compris celles qui ne sont
// plus au menu : leur URL a circulé en lien et ne doit pas tomber en 404.
const PAGES = [
  "marche",
  "portefeuille",
  "pipeline",
  "objectifs",
  "mix-offre",
  "transformation",
  "visites",
] as const;

// Les pages VISIBLES dans le menu. « Mix d'offre » et « Fichier de visite » n'y
// figurent plus : leurs entrées sont commentées (cf. lib/data/sections.ts) — le
// mix parce que ses tuiles sont affichées dans « Diagnostic », le fichier de
// visite parce qu'il n'est plus proposé. Leurs pages restent servies, d'où
// l'écart avec `PAGES`.
const HORS_MENU = ["mix-offre", "visites"];
const PAGES_MENU = PAGES.filter((p) => !HORS_MENU.includes(p));

// Les quatorze vues, par la page qui les porte. Chacune doit rendre son contenu :
// c'est ce qui garantit que le regroupement en sept pages n'a rien perdu.
const VUES: ReadonlyArray<readonly [page: string, vue: string]> = [
  ["portefeuille", "comptes"],
  ["portefeuille", "pics"],
  ["portefeuille", "base-installee"],
  ["pipeline", "pipeline"],
  ["pipeline", "pipe-qualite"],
  ["pipeline", "cycle-vie"],
  ["objectifs", "objectifs"],
  ["objectifs", "efficacite"],
  ["objectifs", "prospection"],
  ["marche", "marche"],
  ["marche", "secteurs"],
  ["mix-offre", "mix-offre"],
  ["transformation", "transformation"],
  ["visites", "visites"],
];

// Anciennes URL de section → page qui porte désormais leur contenu. Ces liens ont
// circulé (revues, messages) et ne doivent pas tomber en 404.
const REDIRECTIONS: ReadonlyArray<readonly [ancienne: string, page: string]> = [
  ["comptes", "portefeuille"],
  ["pics", "portefeuille"],
  ["base-installee", "portefeuille"],
  ["pipe-qualite", "pipeline"],
  ["cycle-vie", "pipeline"],
  ["efficacite", "objectifs"],
  ["prospection", "objectifs"],
  ["secteurs", "marche"],
];

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

  for (const page_ of PAGES) {
    test(`/dc/vision/${page_} rend son contenu`, async ({ page }) => {
      const reponse = await page.goto(`/dc/vision/${page_}`);
      expect(reponse?.status(), `statut HTTP de /dc/vision/${page_}`).toBe(200);
      await expect(page.locator("main.canvas")).toBeVisible();
      // Une tuile au moins : une page qui rendrait un canvas vide passerait
      // l'assertion précédente sans rien afficher.
      await expect(page.locator(".tile, .brief").first()).toBeVisible();
    });
  }

  // Chaque vue doit rendre : c'est ce qui prouve que le regroupement de quatorze
  // écrans en sept pages n'a retiré aucun contenu.
  for (const [page_, vue] of VUES) {
    test(`la vue « ${vue} » de /dc/vision/${page_} rend son contenu`, async ({ page }) => {
      const reponse = await page.goto(`/dc/vision/${page_}?vue=${vue}`);
      expect(reponse?.status()).toBe(200);
      await expect(page.locator(".tile, .brief").first()).toBeVisible();
    });
  }

  // Les anciennes URL de section mènent toujours à leur écran, via `?vue=`.
  for (const [ancienne, page_] of REDIRECTIONS) {
    test(`/dc/vision/${ancienne} redirige vers sa page`, async ({ page }) => {
      await page.goto(`/dc/vision/${ancienne}`);
      await expect(page).toHaveURL(new RegExp(`/dc/vision/${page_}\\?vue=${ancienne}$`));
      await expect(page.locator(".tile, .brief").first()).toBeVisible();
    });
  }

  // Une vue inconnue dans l'URL ouvre la page sur sa première vue : un lien mal
  // recopié ne doit pas produire un écran vide.
  test("une vue inconnue retombe sur la première de la page", async ({ page }) => {
    const reponse = await page.goto("/dc/vision/portefeuille?vue=nimportequoi");
    expect(reponse?.status()).toBe(200);
    const vues = page.getByRole("navigation", { name: "Vues de la page" });
    await expect(vues.locator('a[aria-current="page"]')).toHaveText("Comptes par ventes");
  });

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

  // Le menu tient sur UNE rangée depuis le regroupement en sept pages. C'est ce qui
  // permet de rétablir le préchargement au montage (cf. Header.tsx) : le second
  // niveau de menu, avec ses onze liens visibles, l'avait rendu trop coûteux.
  test("le menu tient sur une seule rangée", async ({ page }) => {
    await page.goto("/dc/vision/portefeuille");
    await expect(page.locator("header.hdr")).toBeVisible();
    await expect(page.locator("header.hdr--stacked")).toHaveCount(0);
    await expect(page.getByRole("navigation", { name: "Chapitres de la vue" })).toHaveCount(0);
    await expect(page.locator(".hdr-nav a")).toHaveCount(PAGES_MENU.length);
  });

  // « Marché » est l'écran d'ouverture du cockpit DC : le profil doit y atterrir
  // sans avoir à cliquer, et l'onglet doit être surligné à l'arrivée. Le test porte
  // sur les DEUX points d'entrée — l'URL de vue nue et la racine du profil — parce
  // qu'ils passent par des redirections distinctes (vision/page.tsx et
  // [profile]/page.tsx). L'onglet actif se lit sur la rangée de sections, à ne pas
  // confondre avec les vues internes de la page (« Tendances et marché »).
  test("le cockpit DC ouvre sur Marché, onglet actif", async ({ page }) => {
    const sections = page.getByRole("navigation", { name: "Sections de la vue" });

    await page.goto("/dc/vision");
    await expect(page).toHaveURL(/\/dc\/vision\/marche$/);
    await expect(sections.locator('a[aria-current="page"]')).toHaveText("Marché");
    // Premier de la rangée, pas seulement actif.
    await expect(sections.locator("a").first()).toHaveText("Marché");

    await page.goto("/dc");
    await expect(page).toHaveURL(/\/dc\/vision\/marche$/);
    await expect(sections.locator('a[aria-current="page"]')).toHaveText("Marché");
  });

  // Les onglets internes portent la vue : le surlignage doit suivre `?vue=`, y
  // compris atteint par lien direct.
  test("l'onglet actif suit la vue ouverte", async ({ page }) => {
    const vues = page.getByRole("navigation", { name: "Vues de la page" });

    await page.goto("/dc/vision/portefeuille?vue=pics");
    await expect(vues.locator("a")).toHaveText([
      "Comptes par ventes",
      "Pics et alertes",
      "Animation de compte",
    ]);
    await expect(vues.locator('a[aria-current="page"]')).toHaveText("Pics et alertes");

    // Sans `?vue=`, c'est la première vue déclarée.
    await page.goto("/dc/vision/marche");
    await expect(vues.locator("a")).toHaveCount(2);
    await expect(vues.locator('a[aria-current="page"]')).toHaveText("Tendances et marché");
  });

  // Une page à vue unique n'affiche pas d'onglets : ils ne proposeraient qu'une
  // entrée, déjà active. L'exemple porte sur « Diagnostic », page à vue unique
  // TOUJOURS au menu — « Fichier de visite » servait avant, mais une page hors
  // menu est un mauvais témoin pour une règle d'affichage du menu.
  test("une page à vue unique n'a pas d'onglets internes", async ({ page }) => {
    await page.goto("/dc/vision/transformation");
    await expect(page.locator("main.canvas")).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Vues de la page" })).toHaveCount(0);
  });

  // La cadence doit reconduire la vue : sans cela, changer de cadence depuis
  // « Indice d'efficacité » ramenait sur « Écart vendu / objectif ».
  test("changer de cadence conserve la vue ouverte", async ({ page }) => {
    await page.goto("/dc/vision/objectifs?vue=efficacite");
    const cadence = page.getByRole("navigation", { name: "Cadence de lecture" });
    await cadence.getByText("Annuel").click();
    await expect(page).toHaveURL(/vue=efficacite/);
    await expect(page).toHaveURL(/periode=annee/);
    const vues = page.getByRole("navigation", { name: "Vues de la page" });
    await expect(vues.locator('a[aria-current="page"]')).toHaveText("Indice d'efficacité");
  });

  // Une section inventée doit tomber en 404 plutôt que rendre une page vide.
  test("une section inconnue répond 404", async ({ page }) => {
    const reponse = await page.goto("/dc/vision/section-inexistante");
    expect(reponse?.status()).toBe(404);
  });
});
