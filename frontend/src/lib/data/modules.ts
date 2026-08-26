/** Libellés des modules de la matrice module × rôle.
 *
 * Les clés sont celles de `backend/config/permissions.py::DEFAULT_MODULE_ACCESS`,
 * qui est la source de vérité : c'est cette matrice que le serveur applique sur
 * chaque endpoint. Ce fichier ne fait que la rendre lisible.
 *
 * Deux écrans lisent ces libellés — Réglages (disponibilité des modules du compte
 * connecté) et Comptes (matrice éditable, périmètre d'un compte). Ils en avaient
 * chacun leur copie : la table de Réglages comptait onze modules quand la matrice
 * du backend en portait douze, si bien que « 6 modules autorisés sur 11 » se
 * calculait sur un dénominateur faux. Une seule table, donc.
 *
 * `moduleLabel` retombe sur la clé brute : un module ajouté côté backend
 * apparaît alors sous son identifiant technique — inélégant, mais visible, ce
 * qui vaut mieux qu'une ligne muette. */
export const MODULE_LABELS: Record<string, string> = {
  briefing: "Briefing quotidien",
  dashboard: "Tableau de bord",
  forecast: "Forecast pondéré",
  tresorerie: "Trésorerie / impayés",
  performance: "Performance & pertes",
  crosssell: "Montée en valeur (cross-sell)",
  portefeuille: "Portefeuille clients",
  couts: "Coûts & marges",
  clients: "Clients",
  partenaires: "Fournisseurs / partenaires",
  documents: "Documents (GED)",
  arbitrage: "Arbitrages",
};

export const ALL_MODULES = Object.keys(MODULE_LABELS);

export function moduleLabel(view: string): string {
  return MODULE_LABELS[view] ?? view;
}
