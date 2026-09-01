/** Les montants du backend sont toujours en XOF bruts (jamais formatés) —
 * cf. note du rapport d'intégration : diviser par 1 000 000 pour "M FCFA". */
export function mFcfa(xof: number | null | undefined): number {
  return Math.round((xof ?? 0) / 1_000_000);
}

const NUMBER_FORMAT = new Intl.NumberFormat("fr-FR");

export function formatNumber(value: number): string {
  return NUMBER_FORMAT.format(Math.round(value));
}

/** Nombre de décimales, choisi pour garder ~3 chiffres significatifs une fois
 * le montant ramené à son échelle. « 6,13 Md » et « 111 M » se lisent tous deux
 * d'un coup d'œil ; « 6,128571 Md » et « 111,0 M » non — l'un noie le lecteur,
 * l'autre affiche une précision qu'on n'a pas. */
function _decimales(valeur: number): number {
  const abs = Math.abs(valeur);
  if (abs < 10) return 2;
  if (abs < 100) return 1;
  return 0;
}

/** Montant en FCFA, à l'échelle qui lui convient — et à elle seule.
 *
 *     850 000        → « 850 000 »      (sous le million : chiffres entiers)
 *     6 128 000      → « 6,13 M »
 *     111 000 000    → « 111 M »
 *     6 128 000 000  → « 6,13 Md »
 *
 * Le seuil est porté par le montant LUI-MÊME, jamais par l'écran : deux lignes
 * d'un même tableau peuvent s'afficher l'une en M et l'autre en Md, et c'est
 * voulu — une échelle imposée à toute une colonne écrase soit les petits
 * montants à « 0 », soit les gros en une file de zéros illisible.
 *
 * L'unité monétaire n'est PAS incluse : les appelants ajoutent « FCFA » (ou le
 * portent dans le libellé de la tuile). Le suffixe d'échelle, lui, est collé au
 * nombre — c'est ce qui empêche un montant d'être recopié sans son ordre de
 * grandeur et de devenir faux d'un facteur mille.
 *
 * `mFcfa` reste réservé au NUMÉRIQUE (mise à l'échelle d'un graphe, comparaison
 * à un seuil exprimé en millions), jamais à l'affichage. */
export function formatFcfa(xof: number | null | undefined): string {
  const v = xof ?? 0;
  const abs = Math.abs(v);

  // Sous le million, aucune abréviation : « 0,85 M » se lit moins bien que
  // « 850 000 », et arrondir un petit montant à l'échelle du million le noie.
  if (abs < 1_000_000) return formatNumber(v);

  const rendre = (div: number, suffixe: string) => {
    const x = v / div;
    const d = _decimales(x);
    return `${x.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d })}${suffixe}`;
  };

  // L'ARRONDI peut promouvoir l'échelle, et c'est le nombre affiché qu'il faut
  // tester, pas le nombre brut : 999 999 999 vaut 999,999999 M, que zéro
  // décimale rend « 1 000 M » — une unité qu'on lit de travers alors que
  // « 1,00 Md » est le même montant, correctement nommé. Le seuil brut
  // (`abs >= 1e9`) laisserait passer tout l'intervalle 999,5 M – 999,999 M.
  const enM = v / 1_000_000;
  if (Math.abs(Number(enM.toFixed(_decimales(enM)))) < 1_000) return rendre(1_000_000, " M");
  return rendre(1_000_000_000, " Md");
}

/** `formatFcfa` pour une valeur DÉJÀ EXPRIMÉE EN MILLIONS.
 *
 * Certains champs arrivent du backend en millions (`*_m_fcfa`, le seuil de
 * mandat DG, le coût de report) et d'autres écrans en dérivent localement via
 * `mFcfa` pour comparer à un seuil. Ces valeurs ne doivent JAMAIS passer par
 * `formatFcfa`, qui les afficherait mille fois trop petites — l'erreur est
 * silencieuse et parfaitement crédible à l'écran. */
export function formatFcfaDepuisM(millions: number | null | undefined): string {
  return formatFcfa((millions ?? 0) * 1_000_000);
}

/** `formatFcfa` avec signe explicite — pour les écarts, où « +2 M » et « 2 M »
 * ne disent pas la même chose. Le signe précède le nombre ET son échelle. */
export function signedFcfa(xof: number | null | undefined): string {
  const v = xof ?? 0;
  return v >= 0 ? `+${formatFcfa(v)}` : formatFcfa(v);
}

export function formatPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("fr-FR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" });
  } catch {
    return iso;
  }
}

/** Date ET heure — pour ce qui se lit à la minute plutôt qu'au jour : le journal
 * d'administration, où deux actions du même jour doivent s'ordonner à l'œil.
 *
 * Les horodatages du backend sont écrits en UTC dans des colonnes sans fuseau,
 * donc relus sans suffixe (`2026-08-24T10:12:00`). Le navigateur les interprète
 * alors comme locaux : sans conséquence sur le fuseau de déploiement (Abidjan,
 * UTC+0), à savoir si l'application est un jour servie ailleurs. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function signed(value: number): string {
  return value >= 0 ? `+${formatNumber(value)}` : formatNumber(value);
}
