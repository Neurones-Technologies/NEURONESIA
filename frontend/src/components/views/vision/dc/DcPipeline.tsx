import {
  getAccountActivity,
  getForecastAnalysis,
  getForecastPipelineWeighted,
  getPerformanceSummary,
} from "@/lib/api/dashboard";
import { formatDate, formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, HintLine, Lst, StatTile, Tile } from "@/components/ui/bento";
import { AnalysisSlot } from "@/components/ui/analysis-slot";
import { Note } from "@/components/ui/primitives";

/** « Pipeline et forecast » — chapitre 4 du compte-rendu DC : le bandeau des trois
 * indicateurs de cadrage, puis le forecast lui-même.
 *
 * Le bandeau croise trois sources (dormance, performance, forecast) : c'est un
 * choix assumé de garder les trois chiffres côte à côte, au prix de deux appels
 * dont cet onglet n'utilise qu'une valeur chacun.
 *
 * PAS DE PANNEAU D'OUVERTURE ici, contrairement à l'écran d'entrée du cockpit. Le
 * briefing du jour se lit sur « Tendances et marché », premier onglet du premier
 * chapitre ; un second panneau sombre sur cet écran redisait en prose ce que les
 * trois indicateurs et la tuile « Répartition du forecast par étape » montrent
 * déjà chiffré. L'écran commence donc directement par ses indicateurs. */
export async function DcPipeline() {
  const [forecast, performance, dormance] = await Promise.all([
    getForecastPipelineWeighted(),
    getPerformanceSummary(),
    getAccountActivity(),
  ]);

  const opportunitesAtRisk = forecast.opportunities.filter((o) => o.at_risk);
  const nbAtRisk = opportunitesAtRisk.length;
  const atRisk = opportunitesAtRisk
    .slice()
    .sort((a, b) => b.weighted_xof - a.weighted_xof)
    .slice(0, 5);
  const atRiskTotal = opportunitesAtRisk.reduce((s, o) => s + o.weighted_xof, 0);

  const byStage = forecast.by_stage ?? [];
  const topStageValue = byStage[0]?.weighted_xof ?? 0;
  // by_stage ne porte que le montant pondéré côté backend — le nombre
  // d'opportunités par étape se recompte ici sur la liste détaillée.
  const stageCounts = forecast.opportunities.reduce<Record<string, number>>((acc, o) => {
    acc[o.stage] = (acc[o.stage] ?? 0) + 1;
    return acc;
  }, {});

  const dormanceSegments = dormance.segments.filter((s) => s.nb_comptes > 0);

  return (
    <>
      {/* Bandeau d'indicateurs hors section : les trois chiffres de cadrage du
          cockpit, repris du motif de l'écran Arbitrages (.kpi-row force
          span:auto sur ses tuiles).

          Tête de rangée : l'état de la base installée, pas le forecast — décision
          DC du 05/08/2026. Le pipeline pondéré reste lisible dans la tuile
          « Répartition du forecast par étape », qui le donne étape par étape. */}
      <div className="kpi-row">
        {dormanceSegments.length > 0 && (
          <StatTile
            span={4}
            label="Portefeuille en sommeil"
            value={formatMFcfa(dormance.sommeil.ca_historique_xof)}
            unit="M FCFA historiques"
            reading={`${formatNumber(dormance.sommeil.nb_comptes)} comptes sans commande depuis plus de 12 mois`}
            readingVariant="neg"
            detail={{
              kicker: "Indicateur · base installée",
              title: "Chiffre d'affaires des comptes sortis du radar",
              tag: `${formatPct(dormance.sommeil.part_ca_pct, 0)} % du CA historique`,
              tagVariant: "r",
              body: [
                `${formatNumber(dormance.sommeil.nb_comptes)} comptes n'ont plus commandé depuis plus de 12 mois. Ils représentent ${formatMFcfa(dormance.sommeil.ca_historique_xof)} M FCFA de chiffre d'affaires cumulé sur toute leur histoire, soit ${formatPct(dormance.sommeil.part_ca_pct, 0)} % du CA historique du portefeuille.`,
                `Ce montant est un CUMUL HISTORIQUE, pas un manque à gagner de l'exercice : il mesure ce que ces comptes ont pesé au total, pas ce qu'ils auraient rapporté cette année. Le chiffre à suivre pour le pilotage est plutôt les ${formatMFcfa(dormance.totaux.ca_a_risque_xof)} M FCFA des ${formatNumber(dormance.totaux.nb_decroches)} comptes qui viennent de décrocher (6 à 24 mois de silence) — eux sont encore récupérables.`,
                dormance.dormants_avec_impaye.nb_comptes > 0
                  ? `${formatNumber(dormance.dormants_avec_impaye.nb_comptes)} de ces comptes silencieux portent un impayé échu (${formatMFcfa(dormance.dormants_avec_impaye.impaye_xof)} M FCFA au total). Une relance commerciale sur ces comptes se prépare avec la Direction Financière, pas seule.`
                  : "Aucun de ces comptes silencieux ne porte d'impayé échu.",
              ],
              kv: [
                ["CA en sommeil", `${formatMFcfa(dormance.sommeil.ca_historique_xof)} M FCFA`],
                ["Part du CA historique", `${formatPct(dormance.sommeil.part_ca_pct, 0)} %`],
                ["Comptes concernés", formatNumber(dormance.sommeil.nb_comptes)],
                ["Dont avec impayé échu", formatNumber(dormance.dormants_avec_impaye.nb_comptes)],
                ["CA récupérable (6-24 mois)", `${formatMFcfa(dormance.totaux.ca_a_risque_xof)} M FCFA`],
                ["Observé au", formatDate(dormance.as_of)],
              ],
              // note: "Le silence se mesure sur les commandes signées. Le détail par facture des impayés est réservé aux profils financiers.",
            }}
          />
        )}
        <StatTile
          span={4}
          label="Taux de victoire"
          value={`${formatPct(performance?.win_rate.taux_valeur_pct ?? null, 0)}`}
          unit="% en valeur"
          reading="historique complet du miroir"
          detail={{
            kicker: "Indicateur · transformation",
            title: "Taux de victoire en valeur",
            tag: "historique complet",
            tagVariant: "n",
            body: [
              `Sur l'ensemble de l'historique disponible, ${formatPct(performance?.win_rate.taux_valeur_pct ?? null, 0)} % de la valeur engagée dans le pipeline s'est transformée en commande.`,
              performance
                ? `Les affaires perdues représentent ${formatNumber(performance.lost_deals.nb_total)} opportunités pour ${formatMFcfa(performance.lost_deals.montant_total_xof)} M FCFA — le détail par client est dans l'onglet « Transformation ».`
                : "Le détail des affaires perdues n'est pas accessible depuis ce profil.",
            ],
            kv: [
              ["Taux en valeur", `${formatPct(performance?.win_rate.taux_valeur_pct ?? null, 0)} %`],
              ...(performance
                ? [
                    ["Affaires perdues", formatNumber(performance.lost_deals.nb_total)],
                    ["Valeur perdue", `${formatMFcfa(performance.lost_deals.montant_total_xof)} M FCFA`],
                  ]
                : []),
            ],
            // note: "Calculé sur les opportunités closes du miroir Odoo, gagnées comme perdues.",
          }}
        />
        <StatTile
          span={4}
          label="Opportunités à risque"
          value={formatNumber(nbAtRisk)}
          unit="échéance dépassée"
          reading={`${formatMFcfa(atRiskTotal)} M FCFA pondérés concernés`}
          readingVariant={nbAtRisk > 0 ? "neg" : undefined}
          detail={{
            kicker: "Indicateur · fiabilité des dates",
            title: "Opportunités dont l'échéance est dépassée",
            tag: nbAtRisk > 0 ? "à requalifier" : "aucune",
            tagVariant: nbAtRisk > 0 ? "r" : "s",
            body: [
              nbAtRisk > 0
                ? `${formatNumber(nbAtRisk)} opportunités portent une date de clôture déjà passée, pour ${formatMFcfa(atRiskTotal)} M FCFA pondérés encore comptés dans le forecast.`
                : "Aucune opportunité ouverte ne porte de date de clôture dépassée.",
              "Une date dépassée n'est pas une affaire perdue : c'est une affaire dont la date n'a pas été tenue à jour. Tant qu'elle n'est pas requalifiée, elle gonfle le forecast du trimestre en cours.",
            ],
            kv: [
              ["Opportunités concernées", formatNumber(nbAtRisk)],
              ["Valeur pondérée", `${formatMFcfa(atRiskTotal)} M FCFA`],
            ],
            // note: "Comparaison entre la date de clôture prévue dans Odoo et la date du jour.",
          }}
        />
      </div>

      <Bento>
        <Tile span={7} title="Répartition du forecast par étape" kick="pondéré">
          {byStage.length > 0 ? (
            <>
              <HintLine>Cliquez une étape pour son poids dans le forecast</HintLine>
              <Bars
                rows={byStage.slice(0, 6).map((s) => {
                  const part = forecast.scenarios.realiste_xof
                    ? (s.weighted_xof / forecast.scenarios.realiste_xof) * 100
                    : 0;
                  return {
                    name: s.stage,
                    sub: `${formatNumber(stageCounts[s.stage] ?? 0)} opportunités · ${formatPct(part, 0)} % du forecast`,
                    value: `${formatMFcfa(s.weighted_xof)} M`,
                    pct: topStageValue ? (s.weighted_xof / topStageValue) * 100 : 0,
                    variant: part > 40 ? ("w" as const) : undefined,
                    detail: {
                      kicker: "Étape du pipeline",
                      title: s.stage,
                      tag: `${formatPct(part, 0)} % du forecast`,
                      tagVariant: part > 40 ? ("w" as const) : ("a" as const),
                      body: [
                        `L'étape « ${s.stage} » regroupe ${formatNumber(stageCounts[s.stage] ?? 0)} opportunités pour ${formatMFcfa(s.weighted_xof)} M FCFA pondérés, soit ${formatPct(part, 0)} % du forecast réaliste.`,
                        part > 40
                          ? "Cette étape porte à elle seule plus de 40 % du forecast : si sa probabilité moyenne est mal calibrée, c'est tout le chiffre annoncé qui bouge."
                          : "Le poids de cette étape reste réparti, ce qui limite l'effet d'une erreur de calibrage sur une seule phase du cycle.",
                      ],
                      kv: [
                        ["Valeur pondérée", `${formatMFcfa(s.weighted_xof)} M FCFA`],
                        ["Opportunités", formatNumber(stageCounts[s.stage] ?? 0)],
                        ["Part du forecast", `${formatPct(part, 0)} %`],
                      ],
                      // note: "Étapes telles que définies dans le pipeline Odoo, sans regroupement par le cockpit.",
                    },
                  };
                })}
              />
            </>
          ) : (
            <Note style={{ marginTop: 0 }}>Aucune étape de pipeline exploitable dans le miroir.</Note>
          )}
        </Tile>

        <Tile span={5} title="Opportunités à requalifier" kick={`${atRisk.length} affichées`}>
          {atRisk.length > 0 ? (
            <Lst
              items={atRisk.map((o) => ({
                title: String(o.name),
                sub: `${o.client} · ${o.stage} · ${o.commercial}`,
                tag: `${formatMFcfa(o.weighted_xof)} M`,
                tagVariant: "r" as const,
                detail: {
                  kicker: "Opportunité · échéance dépassée",
                  title: String(o.name),
                  tag: "à requalifier",
                  tagVariant: "r" as const,
                  body: [
                    `Cette opportunité chez ${o.client} est portée par ${o.commercial}, à l'étape « ${o.stage} », pour ${formatMFcfa(o.weighted_xof)} M FCFA pondérés.`,
                    "Sa date de clôture prévue est déjà passée. Elle continue de peser dans le forecast tant que la date n'est pas révisée ou l'affaire close.",
                  ],
                  kv: [
                    ["Client", o.client],
                    ["Commercial", o.commercial],
                    ["Étape", o.stage],
                    ["Valeur pondérée", `${formatMFcfa(o.weighted_xof)} M FCFA`],
                  ],
                  // note: "Requalifier la date dans Odoo met à jour le forecast au prochain instantané. Le cockpit n'écrit jamais.",
                },
              }))}
            />
          ) : (
            <Note style={{ marginTop: 0 }}>
              Aucune opportunité ouverte n&apos;a d&apos;échéance dépassée actuellement.
            </Note>
          )}
        </Tile>

        <Tile span={12} title="Crédibilité du forecast" kick="narration · M5">
          <AnalysisSlot load={getForecastAnalysis} />
        </Tile>
      </Bento>
    </>
  );
}
