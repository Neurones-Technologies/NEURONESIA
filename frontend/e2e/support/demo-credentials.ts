/**
 * Identifiants des comptes de démonstration utilisés par les tests e2e.
 *
 * Le mot de passe vient de l'environnement, JAMAIS du dépôt : c'est celui
 * fourni à `python backend/scripts/seed_demo_users.py` via
 * DEMO_USERS_PASSWORD. La CI en génère un jetable par run
 * (cf. .github/workflows/ci.yml) ; en local, exporter la même valeur qu'au
 * seed avant de lancer Playwright :
 *
 *     E2E_DEMO_PASSWORD='<valeur>' npx playwright test
 *
 * Les emails, eux, ne sont pas des secrets et restent en clair — c'est le
 * compte visé qui donne son sens au test.
 */
export const DEMO_EMAILS = {
  // Le seul compte `admin` du seed — seul à voir l'écran Comptes.
  admin: "oboyer@neuronestech.com",
  dg: "jmkouadio@neuronestech.com",
  dc: "pbourron@neuronestech.com",
  df: "cdjereke@neuronestech.com",
} as const;

/** Mot de passe démo, ou une erreur explicite s'il n'a pas été fourni. */
export function demoPassword(): string {
  const password = process.env.E2E_DEMO_PASSWORD;
  if (!password) {
    throw new Error(
      "E2E_DEMO_PASSWORD absente — exporte le mot de passe utilisé par " +
        "`python backend/scripts/seed_demo_users.py` (DEMO_USERS_PASSWORD) " +
        "avant de lancer Playwright."
    );
  }
  return password;
}
