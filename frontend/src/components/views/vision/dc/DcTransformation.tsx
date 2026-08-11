import {
  getPerformanceAnalysis,
  getPerformanceSummary,
  getRevenueBySalesperson,
} from "@/lib/api/dashboard";
import { formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, HintLine, Lst, Tile } from "@/components/ui/bento";
import { AnalysisSlot } from "@/components/ui/analysis-slot";

/** Onglet « Transformation » : pourquoi on gagne, pourquoi on perd. La narration
 * des motifs de perte ouvre l'onglet, ses données la suivent immédiatement. */
export async function DcTransformation() {
  const [performance, salespeople] = await Promise.all([
    getPerformanceSummary(),
    getRevenueBySalesperson(),
  ]);

  const topSalespeople = (salespeople ?? [])
    .slice()
    .sort((a, b) => Number(b.ca_total_xof) - Number(a.ca_total_xof));
  const totalCaEquipe = topSalespeople.reduce((s, p) => s + Number(p.ca_total_xof), 0);
  const topSalesCa = topSalespeople[0] ? Number(topSalespeople[0].ca_total_xof) : 0;

  return (
    <Bento>
      <Tile span={12} title="Analyse des motifs de perte" kick="narration">
        <AnalysisSlot load={getPerformanceAnalysis} />
      </Tile>

      {performance && (
        <>
          <Tile
            span={7}
            title="Où se concentrent les pertes"
            kick={`${formatNumber(performance.lost_deals.nb_total)} affaires`}
          >
            <HintLine>Cliquez un client pour ses affaires perdues</HintLine>
            <Bars
              rows={performance.lost_deals.by_client.slice(0, 5).map((c) => {
                const part = performance.lost_deals.montant_total_xof
                  ? (c.montant_xof / performance.lost_deals.montant_total_xof) * 100
                  : 0;
                return {
                  name: c.client,
                  sub: `${formatPct(part, 0)} % de la valeur perdue`,
                  value: `${formatMFcfa(c.montant_xof)} M`,
                  pct: part,
                  variant: "r" as const,
                  detail: {
                    kicker: "Client · affaires perdues",
                    title: c.client,
                    tag: `${formatMFcfa(c.montant_xof)} M perdus`,
                    tagVariant: "r" as const,
                    body: [
                      `${c.client} concentre ${formatMFcfa(c.montant_xof)} M FCFA d'affaires perdues, soit ${formatPct(part, 0)} % de la valeur perdue totale.`,
                      "Une concentration de pertes sur un même compte se lit rarement comme un problème de prix isolé : elle interroge le positionnement sur ce client ou la qualification en amont.",
                    ],
                    kv: [
                      ["Valeur perdue", `${formatMFcfa(c.montant_xof)} M FCFA`],
                      ["Part du total perdu", `${formatPct(part, 0)} %`],
                    ],
                    // note: "Opportunités marquées perdues dans Odoo, historique complet du miroir.",
                  },
                };
              })}
            />
          </Tile>

          <Tile span={5} title="Plus grosses affaires perdues" kick="par montant">
            <Lst
              items={performance.lost_deals.top_deals.slice(0, 5).map((d) => ({
                title: String(d.name),
                sub: `${d.client} · ${d.commercial}`,
                tag: `${formatMFcfa(Number(d.montant_xof))} M`,
                tagVariant: "r" as const,
                detail: {
                  kicker: "Affaire perdue",
                  title: String(d.name),
                  tag: `${formatMFcfa(Number(d.montant_xof))} M FCFA`,
                  tagVariant: "r" as const,
                  body: [
                    `Affaire chez ${d.client}, portée par ${d.commercial}, perdue pour un montant de ${formatMFcfa(Number(d.montant_xof))} M FCFA.`,
                    "Le motif de perte n'est exploitable que s'il a été renseigné dans Odoo — le cockpit ne le devine pas.",
                  ],
                  kv: [
                    ["Client", d.client],
                    ["Commercial", String(d.commercial)],
                    ["Montant", `${formatMFcfa(Number(d.montant_xof))} M FCFA`],
                  ],
                  // note: "Opportunité close en perte dans le miroir Odoo.",
                },
              }))}
            />
          </Tile>
        </>
      )}

      {topSalespeople.length > 0 && (
        <Tile span={12} title="Coaching de portefeuille" kick="CA par commercial">
          <HintLine>Cliquez un commercial pour son portefeuille</HintLine>
          <Bars
            rows={topSalespeople.slice(0, 8).map((s) => {
              const ca = Number(s.ca_total_xof);
              const part = totalCaEquipe ? (ca / totalCaEquipe) * 100 : 0;
              return {
                name: s.commercial,
                sub: `${formatNumber(Number(s.nb_commandes))} commandes · ${formatNumber(Number(s.nb_clients_distincts))} clients · panier ${formatMFcfa(Number(s.panier_moyen_xof))} M`,
                value: `${formatMFcfa(ca)} M`,
                pct: topSalesCa ? (ca / topSalesCa) * 100 : 0,
                variant: part > 40 ? ("w" as const) : undefined,
                detail: {
                  kicker: "Commercial",
                  title: s.commercial,
                  tag: `${formatPct(part, 0)} % du CA équipe`,
                  tagVariant: part > 40 ? ("w" as const) : ("a" as const),
                  body: [
                    `${s.commercial} a réalisé ${formatMFcfa(ca)} M FCFA sur ${formatNumber(Number(s.nb_commandes))} commandes auprès de ${formatNumber(Number(s.nb_clients_distincts))} clients distincts, pour un panier moyen de ${formatMFcfa(Number(s.panier_moyen_xof))} M FCFA.`,
                    part > 40
                      ? "Ce commercial porte plus de 40 % du chiffre de l'équipe. C'est une performance, et simultanément une dépendance : son départ ou son absence déplacerait le résultat commercial."
                      : "Le poids de ce portefeuille reste dans la moyenne de l'équipe.",
                  ],
                  kv: [
                    ["CA réalisé", `${formatMFcfa(ca)} M FCFA`],
                    ["Part du CA équipe", `${formatPct(part, 0)} %`],
                    ["Commandes", formatNumber(Number(s.nb_commandes))],
                    ["Clients distincts", formatNumber(Number(s.nb_clients_distincts))],
                    ["Panier moyen", `${formatMFcfa(Number(s.panier_moyen_xof))} M FCFA`],
                  ],
                  // note: "CA rattaché au commercial renseigné sur la commande Odoo.",
                },
              };
            })}
          />
        </Tile>
      )}
    </Bento>
  );
}
