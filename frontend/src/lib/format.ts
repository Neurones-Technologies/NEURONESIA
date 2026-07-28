/** Les montants du backend sont toujours en XOF bruts (jamais formatés) —
 * cf. note du rapport d'intégration : diviser par 1 000 000 pour "M FCFA". */
export function mFcfa(xof: number | null | undefined): number {
  return Math.round((xof ?? 0) / 1_000_000);
}

const NUMBER_FORMAT = new Intl.NumberFormat("fr-FR");

export function formatNumber(value: number): string {
  return NUMBER_FORMAT.format(Math.round(value));
}

export function formatMFcfa(xof: number | null | undefined): string {
  return formatNumber(mFcfa(xof));
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

export function signed(value: number): string {
  return value >= 0 ? `+${formatNumber(value)}` : formatNumber(value);
}
