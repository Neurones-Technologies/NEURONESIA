import { test, expect, type Cookie } from "@playwright/test";
import { DEMO_EMAILS, demoPassword } from "./support/demo-credentials";

// Nécessite un backend joignable (BACKEND_URL) avec les comptes démo seedés
// via `python backend/scripts/seed_demo_users.py` — même prérequis que
// df-sections.spec.ts et dc-sections.spec.ts.
//
// Le cockpit DG est passé en navigation PAR ROUTE : chaque onglet est une page
// distincte, et une entrée de `VISION_SECTIONS.dg` sans entrée correspondante
// dans le registre `DG_SECTIONS` (ou l'inverse) produit un 404 que rien ne
// signale au développement. Ce test parcourt les onglets déclarés et vérifie
// qu'ils rendent tous — c'est la seule protection contre un menu qui pointe
// dans le vide.

const SECTIONS = ["tableau-de-bord", "trajectoire", "pilotage", "factures"] as const;

test.describe("Cockpit DG — les onglets rendent tous", () => {
  // Sériel pour la même raison que df-sections.spec.ts : `/v1/auth/login` est
  // limité à 5 appels par minute et par IP côté backend.
  test.describe.configure({ mode: "serial" });

  let session: Cookie[] = [];

  test.beforeAll(async ({ playwright, baseURL }) => {
    const api = await playwright.request.newContext({ baseURL });
    const reponse = await api.post("/api/auth/login", {
      data: { email: DEMO_EMAILS.dg, password: demoPassword() },
    });
    expect(reponse.ok(), "connexion du compte démo DG").toBeTruthy();
    session = (await api.storageState()).cookies;
    await api.dispose();
  });

  test.beforeEach(async ({ context }) => {
    await context.addCookies(session);
  });

  for (const section of SECTIONS) {
    test(`/dg/vision/${section} rend son contenu`, async ({ page }) => {
      const reponse = await page.goto(`/dg/vision/${section}`);
      expect(reponse?.status(), `statut HTTP de /dg/vision/${section}`).toBe(200);
      await expect(page.locator("main.canvas")).toBeVisible();
      // Une tuile au moins : une page qui rendrait un canvas vide passerait
      // l'assertion précédente sans rien afficher.
      await expect(page.locator(".tile, .brief").first()).toBeVisible();
    });
  }

  // Seule la page d'ouverture porte le briefing du jour : un second panneau
  // sombre ailleurs signalerait une page qui se prend pour l'écran d'accueil.
  test("le briefing n'apparaît que sur le tableau de bord", async ({ page }) => {
    await page.goto("/dg/vision/tableau-de-bord");
    await expect(page.locator(".brief")).toHaveCount(1);

    await page.goto("/dg/vision/trajectoire");
    await expect(page.locator(".tile").first()).toBeVisible();
    await expect(page.locator(".brief")).toHaveCount(0);
  });

  // Une section inventée doit tomber en 404 plutôt que rendre une page vide.
  test("une section inconnue répond 404", async ({ page }) => {
    const reponse = await page.goto("/dg/vision/section-inexistante");
    expect(reponse?.status()).toBe(404);
  });

  // « Dépendances et risques » n'est plus un onglet : ses deux tuiles vivent
  // dans le Tableau de bord. Ce cas vérifie les deux faces du déplacement —
  // plus d'onglet, plus de route, et les tuiles visibles sur la page d'accueil.
  test("les dépendances vivent dans le tableau de bord, plus dans un onglet", async ({ page }) => {
    await page.goto("/dg/vision/tableau-de-bord");
    await expect(page.getByRole("heading", { name: "Top 5 des clients à risque" })).toBeVisible();
    await expect(page.getByRole("link", { name: /dépendances et risques/i })).toHaveCount(0);

    const reponse = await page.goto("/dg/vision/risques");
    expect(reponse?.status(), "statut HTTP de /dg/vision/risques").toBe(404);
  });

  // `/dg/vision` n'est plus une page : elle redirige vers la première section.
  test("la racine du cockpit DG redirige vers la première section", async ({ page }) => {
    await page.goto("/dg/vision");
    await expect(page).toHaveURL(/\/dg\/vision\/tableau-de-bord$/);
  });
});
