import { test, expect } from "@playwright/test";
import { DEMO_EMAILS, demoPassword } from "./support/demo-credentials";

// Nécessite un backend joignable (BACKEND_URL) avec les comptes démo seedés
// via `python backend/scripts/seed_demo_users.py` — voir .github/workflows/ci.yml.
// En local sans backend, lancer par ex. `docker compose up backend` puis le seed.
// Le mot de passe vient de E2E_DEMO_PASSWORD (cf. support/demo-credentials.ts).
test.describe("Connexion", () => {
  // SÉRIEL et volontairement limité à DEUX connexions : `/v1/auth/login` est
  // rate-limité à 5/minute par IP (api/v1/auth.py), et les tentatives ÉCHOUÉES
  // comptent aussi. Le reste de la suite en consomme deux autres
  // (dc-sections, df-sections) → budget total 4/5. Toute connexion ajoutée
  // ailleurs fera tomber la suite sur des 429 sans rapport avec le test.
  test.describe.configure({ mode: "serial" });

  // Le cas qui protège la vérification elle-même : avant la correction, le
  // formulaire envoyait un mot de passe codé en dur au lieu de celui saisi —
  // n'importe quelle valeur ouvrait une session. Ce test échouerait aussitôt.
  test("refuse un mot de passe erroné", async ({ page }) => {
    await page.goto("/login");

    await page.locator("#email").fill(DEMO_EMAILS.dg);
    await page.locator("#password").fill("mot-de-passe-invalide");
    await page.getByRole("button", { name: "Se connecter" }).click();

    await expect(page.getByText("Email ou mot de passe incorrect")).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test("se connecte avec le compte DG et atterrit sur /dg/vision", async ({ page }) => {
    await page.goto("/login");

    // Le profil n'est plus choisi côté client : il découle du rôle du compte
    // authentifié, tel que renvoyé par le backend.
    await page.locator("#email").fill(DEMO_EMAILS.dg);
    await page.locator("#password").fill(demoPassword());
    await page.getByRole("button", { name: "Se connecter" }).click();

    await page.waitForURL("**/dg/vision");
    await expect(page.locator("main.canvas")).toBeVisible();
  });
});
