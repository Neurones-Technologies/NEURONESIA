import { test, expect } from "@playwright/test";

// Nécessite un backend joignable (BACKEND_URL) avec les comptes démo seedés
// via `python backend/scripts/seed_demo_users.py` — voir .github/workflows/ci.yml.
// En local sans backend, lancer par ex. `docker compose up backend` puis le seed.
test.describe("Connexion démo -> vision DG", () => {
  test("se connecte avec le profil DG et atterrit sur /dg/vision", async ({ page }) => {
    await page.goto("/login");

    // "dg" est le profil sélectionné par défaut du <select id="profile">.
    await page.locator("#password").fill("neurones2026");
    await page.getByRole("button", { name: "Se connecter" }).click();

    await page.waitForURL("**/dg/vision");
    await expect(page.locator("main.canvas")).toBeVisible();
  });
});
