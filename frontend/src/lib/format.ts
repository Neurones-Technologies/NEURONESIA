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
