import { apiFetch } from "./client";

/** Table simple, fraîcheur lue sur sa colonne `synced_at`. */
export interface MirrorTableStat {
  count: number;
  last_synced_at: string | null;
}

/** Journal d'instantanés (append-only) : la fraîcheur pertinente est la
 * profondeur d'historique couverte, pas la dernière écriture. */
export interface MirrorSnapshotStat {
  count: number;
  first_date: string | null;
  last_date: string | null;
}

export interface MirrorCoverage {
  generated_at: string;
  tables: Record<string, MirrorTableStat | MirrorSnapshotStat>;
}

/** État réel du miroir Odoo (`/v1/stats/mirror`) — effectif et fraîcheur par
 * table, sourcés en direct sur la base SQLite locale. Une table jamais
 * synchronisée revient avec `count: 0`, ce n'est pas une erreur réseau.
 * Réservé aux administrateurs côté serveur — à utiliser uniquement depuis un
 * écran déjà protégé (cf. `[profile]/referentiel/page.tsx`). */
export async function getMirrorCoverage(): Promise<MirrorCoverage> {
  return apiFetch<MirrorCoverage>("/v1/stats/mirror");
}

/** Même appel, mais pour un écran ouvert à tous les rôles (Réglages) : un 403
 * (non-admin) redevient `null` plutôt qu'une erreur qui casserait la page. */
export async function getMirrorCoverageSafe(): Promise<MirrorCoverage | null> {
  return apiFetch<MirrorCoverage | null>("/v1/stats/mirror", { allowForbidden: true });
}

export function isSnapshotStat(stat: MirrorTableStat | MirrorSnapshotStat): stat is MirrorSnapshotStat {
  return "first_date" in stat;
}

export function hoursSince(iso: string): number {
  return (Date.now() - new Date(iso).getTime()) / 3_600_000;
}

/** Nombre de jours couverts par un journal d'instantanés, bornes incluses. */
export function daysBetween(first: string, last: string): number {
  return Math.round((new Date(last).getTime() - new Date(first).getTime()) / 86_400_000) + 1;
}
