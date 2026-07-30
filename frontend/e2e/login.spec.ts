import { test, expect } from "@playwright/test";

// Smoke test volontairement sans backend : /login se rend entièrement côté
// client, seul le clic sur "Se connecter" appelle l'API.
test.describe("Page de connexion", () => {
  test("affiche le formulaire de connexion", async ({ page }) => {
    await page.goto("/login");

    await expect(page.getByRole("heading", { name: "Connexion" })).toBeVisible();
    await expect(page.locator("#profile")).toBeVisible();
    await expect(page.locator("#password")).toBeVisible();
    await expect(page.getByRole("button", { name: "Se connecter" })).toBeVisible();
  });

  test("refuse la soumission sans mot de passe", async ({ page }) => {
    await page.goto("/login");

    // Le champ #password est `required` : le navigateur bloque la soumission
    // nativement avant même le handler React, donc pas de navigation.
    await page.getByRole("button", { name: "Se connecter" }).click();

    await expect(page).toHaveURL(/\/login$/);
  });
});
