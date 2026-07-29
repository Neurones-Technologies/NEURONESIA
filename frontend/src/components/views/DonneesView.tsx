import { daysBetween, getMirrorCoverage, hoursSince, isSnapshotStat } from "@/lib/api/donnees";
import type { MirrorSnapshotStat, MirrorTableStat } from "@/lib/api/donnees";
import { DOMAINS, engineFiability, ENGINES_BY_PROFILE, GAPS } from "@/lib/data/donnees";
import { formatDate, formatNumber } from "@/lib/format";
import { ProfileKey, Variant } from "@/lib/types";
import { Bento, FootNote, HintLine, Lst, Tile } from "@/components/ui/bento";
import { Clickable } from "@/components/ui/detail";
import { Tag } from "@/components/ui/primitives";

/** Vue Données — connectée au backend réel (`GET /v1/stats/mirror`) : effectif
 * et fraîcheur de chaque table du miroir, et profondeur d'historique des deux
 * journaux d'instantanés (pipeline/backlog). Ce que ce profil ne peut pas voir
 * (`GAPS`) et le rôle de chaque moteur restent éditoriaux — ce ne sont pas des
 * données à interroger — mais la fiabilité de M3/M5 est calculée en direct sur
 * la profondeur réelle d'historique. */

interface Resolved {
  source: string;
  fraicheur: string;
  etat: string;
  variant: Variant;
}

function resolveDomain(
  label: string,
  table: string | null,
  absentNote: string | undefined,
  tables: Record<string, MirrorTableStat | MirrorSnapshotStat>
): Resolved {
  if (table === null) {
    return { source: "—", fraicheur: "absent", etat: absentNote ?? "non instrumenté", variant: "r" };
  }
  const stat = tables[table];
  if (!stat) return { source: table, fraicheur: "absent", etat: "non instrumenté", variant: "r" };

  if (isSnapshotStat(stat)) {
    if (stat.count === 0 || !stat.first_date || !stat.last_date) {
      return { source: table, fraicheur: "absent", etat: "aucun instantané enregistré", variant: "r" };
    }
    const depth = daysBetween(stat.first_date, stat.last_date);
    const fraicheur = `depuis le ${formatDate(stat.first_date)}`;
    return depth < 60
      ? { source: table, fraicheur, etat: `historique en construction · ${depth} jour(s)`, variant: "w" }
      : { source: table, fraicheur, etat: `historique établi · ${depth} jours`, variant: "s" };
  }

  if (stat.count === 0 || !stat.last_synced_at) {
    return { source: table, fraicheur: "jamais", etat: "jamais synchronisé", variant: "r" };
  }
  const fraicheur = `synchronisé le ${formatDate(stat.last_synced_at)}`;
  return hoursSince(stat.last_synced_at) <= 48
    ? { source: table, fraicheur, etat: `complet · ${formatNumber(stat.count)} lignes`, variant: "s" }
    : { source: table, fraicheur, etat: `à resynchroniser · ${formatNumber(stat.count)} lignes`, variant: "w" };
}

export async function DonneesView({ profile }: { profile: ProfileKey }) {
  const coverage = await getMirrorCoverage();
  const domains = DOMAINS[profile];
  const gaps = GAPS[profile];
  const engines = ENGINES_BY_PROFILE[profile];

  const resolved = domains.map((d) => ({ ...d, ...resolveDomain(d.label, d.table, d.absentNote, coverage.tables) }));

  return (
    <Bento>
      <Tile span={7} title="Ce que le miroir contient" kick={`instantané du ${formatDate(coverage.generated_at)}`}>
        <HintLine>Cliquez une source pour son mode d&apos;accès</HintLine>
        <div style={{ overflowX: "auto" }}>
          <table className="tb">
            <thead>
              <tr>
                <th>Domaine</th>
                <th>Source</th>
                <th>Fraîcheur</th>
                <th>État</th>
              </tr>
            </thead>
            <tbody>
              {resolved.map((r) => (
                <Clickable
                  as="tr"
                  key={r.label}
                  detail={{
                    kicker: "Source de données",
                    title: r.label,
                    tag: r.etat,
                    tagVariant: r.variant,
                    body:
                      r.table === null
                        ? r.absentNote ?? "Aucune table du miroir ne couvre ce domaine."
                        : "Table répliquée en lecture seule depuis Odoo. Aucune écriture n'est possible depuis le cockpit.",
                    kv: [
                      ["Table", r.source],
                      ["Fraîcheur", r.fraicheur],
                      ["État", r.etat],
                      ["Mode d'accès", r.table === null ? "non instrumenté" : "lecture seule"],
                    ],
                    note: "Une ligne absente du miroir n'est pas une ligne à zéro : le cockpit préfère se taire plutôt qu'estimer.",
                  }}
                >
                  <td>{r.label}</td>
                  <td className="mono">{r.source}</td>
                  <td className="mono">{r.fraicheur}</td>
                  <td>
                    <Tag variant={r.variant}>{r.etat}</Tag>
                  </td>
                </Clickable>
              ))}
            </tbody>
          </table>
        </div>
        <FootNote>
          Effectif et fraîcheur lus en direct sur le miroir SQLite (`/v1/stats/mirror`). Aucune écriture, aucun accès
          direct à la base de production Odoo.
        </FootNote>
      </Tile>

      <Tile span={5} title="Ce que le cockpit ne peut pas dire" kick={`${gaps.length} limites`}>
        <Lst
          items={gaps.map((g) => ({
            title: g.question,
            sub: g.raison,
            tag: "limite",
            tagVariant: "n" as const,
            detail: {
              kicker: "Limite de couverture",
              title: g.question,
              tag: "limite",
              tagVariant: "n" as const,
              body: g.raison,
              kv: [
                ["Statut", "non instrumentée"],
                ["Cause", "donnée absente ou partielle du miroir"],
              ],
              note: "Le cockpit expose ses limites plutôt que de produire une estimation non sourçable.",
            },
          }))}
        />
      </Tile>

      <Tile span={12} title="Moteurs mobilisés par ce profil" kick={`${engines.length} moteurs`}>
        <HintLine>Cliquez un moteur pour sa méthode</HintLine>
        <div style={{ overflowX: "auto" }}>
          <table className="tb">
            <thead>
              <tr>
                <th>Moteur</th>
                <th>Ce qu&apos;il fait</th>
                <th>Nature</th>
                <th>Fiabilité</th>
              </tr>
            </thead>
            <tbody>
              {engines.map((e) => {
                const fiab = engineFiability(e, coverage.tables);
                return (
                  <Clickable
                    as="tr"
                    key={e.code}
                    detail={{
                      kicker: "Moteur",
                      title: e.nom,
                      tag: fiab.label,
                      tagVariant: fiab.variant,
                      body: e.methode,
                      kv: [
                        ["Nature", e.nature],
                        ["Fiabilité", fiab.label],
                        ["Sortie", "chiffrée, horodatée"],
                      ],
                      note: "Tous les moteurs tournent sur le miroir répliqué, jamais en direct sur la production Odoo.",
                    }}
                  >
                    <td style={{ fontWeight: 500 }}>{e.nom}</td>
                    <td style={{ color: "var(--t2)", fontSize: 12.5 }}>{e.role}</td>
                    <td>
                      <Tag variant="n">{e.nature}</Tag>
                    </td>
                    <td>
                      <Tag variant={fiab.variant}>{fiab.label}</Tag>
                    </td>
                  </Clickable>
                );
              })}
            </tbody>
          </table>
        </div>
        <FootNote>
          Seul le moteur de narration est génératif, et il ne calcule rien : il rédige à partir des sorties chiffrées
          des autres moteurs.
        </FootNote>
      </Tile>
    </Bento>
  );
}
