import { test, expect } from "@playwright/test";

// Smoke test volontairement sans backend : /login se rend entièrement côté
// client, seul le clic sur "Se connecter" appelle l'API.
test.describe("Page de connexion", () => {
  test("affiche le formulaire de connexion", async ({ page }) => {
    await page.goto("/login");

    await expect(page.getByRole("heading", { name: "Connexion" })).toBeVisible();
    // Un champ email, pas un sélecteur de persona : le profil découle du rôle
    // du compte authentifié, il n'est plus choisi côté client.
    await expect(page.locator("#email")).toBeVisible();
    await expect(page.locator("#password")).toBeVisible();
    await expect(page.getByRole("button", { name: "Se connecter" })).toBeVisible();
  });

  test("refuse la soumission sans identifiants", async ({ page }) => {
    await page.goto("/login");

    // #email et #password sont `required` : le navigateur bloque la soumission
    // nativement avant même le handler React, donc pas de navigation ni d'appel
    // réseau (ce test ne consomme rien du budget rate-limit de /auth/login).
    await page.getByRole("button", { name: "Se connecter" }).click();

    await expect(page).toHaveURL(/\/login$/);
  });

  // Le proxy ajoute `?next=` sur toute page protégée demandée sans session ; le
  // formulaire doit survivre au paramètre, y compris quand il est hostile.
  test("se rend avec un paramètre next", async ({ page }) => {
    await page.goto("/login?next=%2Fdc%2Farbitrage");

    await expect(page.getByRole("heading", { name: "Connexion" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Se connecter" })).toBeVisible();
  });

  test("se rend avec un next hors domaine", async ({ page }) => {
    await page.goto("/login?next=https%3A%2F%2Fevil.tld");

    await expect(page.getByRole("heading", { name: "Connexion" })).toBeVisible();
  });
});
