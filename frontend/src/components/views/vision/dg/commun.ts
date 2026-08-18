/** Helpers partagés entre les pages du cockpit DG (cf. ./index.tsx). Extraits
 * de l'ancienne page unique DgVision lors du passage en navigation par route :
 * chaque onglet est devenu une page, mais les sparklines et les libellés de
 * mois doivent rester identiques d'une page à l'autre. */

export const MOIS_ABREV = [
  "Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sept", "Oct", "Nov", "Déc",
];

/** Ramène une série à des hauteurs en % du plus haut point — la maquette
 * affiche les sparklines en indice, jamais en valeur absolue. */
export function toSpark(values: number[]): number[] {
  const max = Math.max(...values, 0);
  if (!max) return values.map(() => 4);
  return values.map((v) => Math.round((v / max) * 100));
}
