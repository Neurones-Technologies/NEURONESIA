import { getBriefing } from "@/lib/api/briefing";
import { getCrossSellAnalysis, getCrossSellSignals } from "@/lib/api/crosssell";
import {
  getForecastAnalysis,
  getForecastPipelineWeighted,
  getPerformanceAnalysis,
  getPerformanceSummary,
  getRevenueBySalesperson,
} from "@/lib/api/dashboard";
import { formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, Brief, FootNote, HintLine, Lst, StatTile, Tile } from "@/components/ui/bento";
import { AnalysisSlot } from "@/components/ui/analysis-slot";
import { Note } from "@/components/ui/primitives";

export async function DcVision() {
  // Les narrations LLM (`get*Analysis`) sont volontairement ABSENTES de ce
  // Promise.all : figées à la journée côté backend elles sont immédiates, mais
  // leur calcul de secours coûte 10-20 s et bloquerait tout le HTML de la vue.
  // Elles sont rendues en parallèle par <AnalysisSlot> (cf.
  // components/ui/analysis-slot.tsx).
  const [forecast, crosssell, performance, salespeople, briefing] = await Promise.all([
    getForecastPipelineWeighted(),
    getCrossSellSignals(),
    getPerformanceSummary(),
    getRevenueBySalesperson(),
    getBriefing(),
  ]);

  const briefLines = briefing?.section?.resume?.length
    ? briefing.section.resume
    : (briefing?.section?.bullets ?? []).slice(0, 5);

  const atRisk = forecast.opportunities
    .filter((o) => o.at_risk)
    .sort((a, b) => b.weighted_xof - a.weighted_xof)
    .slice(0, 5);

  const atRiskTotal = forecast.opportunities
    .filter((o) => o.at_risk)
    .reduce((s, o) => s + o.weighted_xof, 0);

  const spreadPct = forecast.scenarios.realiste_xof
    ? ((forecast.scenarios.optimiste_xof - forecast.scenarios.pessimiste_xof) / forecast.scenarios.realiste_xof) * 100
    : null;

  const topSalespeople = (salespeople ?? [])
    .slice()
    .sort((a, b) => Number(b.ca_total_xof) - Number(a.ca_total_xof));
  const totalCaEquipe = topSalespeople.reduce((s, p) => s + Number(p.ca_total_xof), 0);
  const top1Part =
    topSalespeople[0] && totalCaEquipe ? (Number(topSalespeople[0].ca_total_xof) / totalCaEquipe) * 100 : null;
  const bottomSalesperson = topSalespeople[topSalespeople.length - 1];
  const topSalesCa = topSalespeople[0] ? Number(topSalespeople[0].ca_total_xof) : 0;

  const byStage = forecast.by_stage ?? [];
  const topStageValue = byStage[0]?.weighted_xof ?? 0;
  // by_stage ne porte que le montant pondéré côté backend — le nombre
  // d'opportunités par étape se recompte ici sur la liste détaillée.
  const stageCounts = forecast.opportunities.reduce<Record<string, number>>((acc, o) => {
    acc[o.stage] = (acc[o.stage] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <>
      <Brief
        kicker="Pipeline · pondéré sur la probabilité déclarée"
        headline={`${formatMFcfa(forecast.scenarios.realiste_xof)} M FCFA de pipeline pondéré, sur ${formatMFcfa(forecast.scenarios.total_pipeline_xof)} M annoncés.`}
        lines={briefLines}
        paragraphs={
          briefLines.length
            ? undefined
            : [
                `Le pipeline ouvert compte ${formatNumber(forecast.scenarios.nb_opportunites)} opportunités pour ${formatMFcfa(forecast.scenarios.realiste_xof)} M FCFA pondérés. Le briefing du jour n'est pas encore généré pour ce profil.`,
              ]
        }
        pills={[
          { label: `${formatNumber(forecast.scenarios.nb_opportunites)} opportunités ouvertes` },
          { label: `${formatNumber(atRisk.length ? forecast.opportunities.filter((o) => o.at_risk).length : 0)} à échéance dépassée`, hot: atRisk.length > 0 },
          { label: `Probabilité moyenne ${formatPct(forecast.scenarios.avg_probability_pct, 0)} %` },
          { label: `Taux de victoire ${formatPct(performance?.win_rate.taux_valeur_pct ?? null, 0)} %` },
        ]}
      />

      <Bento>
        <StatTile
          span={4}
          label="Pipeline pondéré"
          value={formatMFcfa(forecast.scenarios.realiste_xof)}
          unit="M FCFA"
          reading={`sur ${formatMFcfa(forecast.scenarios.total_pipeline_xof)} M bruts`}
          readingVariant="wat"
          detail={{
            kicker: "Indicateur · forecast",
            title: "Pipeline pondéré, scénario réaliste",
            tag: `${formatNumber(forecast.scenarios.nb_opportunites)} opportunités`,
            tagVariant: "a",
            body: [
              `Le pipeline brut annoncé est de ${formatMFcfa(forecast.scenarios.total_pipeline_xof)} M FCFA. Pondéré par la probabilité déclarée sur chaque opportunité Odoo, il ressort à ${formatMFcfa(forecast.scenarios.realiste_xof)} M FCFA.`,
              `L'écart entre scénario bas (${formatMFcfa(forecast.scenarios.pessimiste_xof)} M) et haut (${formatMFcfa(forecast.scenarios.optimiste_xof)} M) représente ${spreadPct !== null ? formatPct(spreadPct, 0) : "—"} % du réaliste : c'est l'amplitude d'incertitude à annoncer en comité, pas un chiffre unique.`,
            ],
            kv: [
              ["Pipeline brut", `${formatMFcfa(forecast.scenarios.total_pipeline_xof)} M FCFA`],
              ["Scénario bas", `${formatMFcfa(forecast.scenarios.pessimiste_xof)} M FCFA`],
              ["Scénario réaliste", `${formatMFcfa(forecast.scenarios.realiste_xof)} M FCFA`],
              ["Scénario haut", `${formatMFcfa(forecast.scenarios.optimiste_xof)} M FCFA`],
              ["Amplitude", spreadPct !== null ? `${formatPct(spreadPct, 0)} % du réaliste` : "—"],
            ],
            note: "Probabilité issue du champ Odoo de l'opportunité (crm.lead), jamais recalculée par le cockpit.",
          }}
        />
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
                ? `Les affaires perdues représentent ${formatNumber(performance.lost_deals.nb_total)} opportunités pour ${formatMFcfa(performance.lost_deals.montant_total_xof)} M FCFA — le détail par client est dans la tuile « Motifs de perte ».`
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
            note: "Calculé sur les opportunités closes du miroir Odoo, gagnées comme perdues.",
          }}
        />
        <StatTile
          span={4}
          label="Opportunités à risque"
          value={formatNumber(forecast.opportunities.filter((o) => o.at_risk).length)}
          unit="échéance dépassée"
          reading={`${formatMFcfa(atRiskTotal)} M FCFA pondérés concernés`}
          readingVariant={atRisk.length > 0 ? "neg" : undefined}
          detail={{
            kicker: "Indicateur · fiabilité des dates",
            title: "Opportunités dont l'échéance est dépassée",
            tag: atRisk.length > 0 ? "à requalifier" : "aucune",
            tagVariant: atRisk.length > 0 ? "r" : "s",
            body: [
              atRisk.length > 0
                ? `${formatNumber(forecast.opportunities.filter((o) => o.at_risk).length)} opportunités portent une date de clôture déjà passée, pour ${formatMFcfa(atRiskTotal)} M FCFA pondérés encore comptés dans le forecast.`
                : "Aucune opportunité ouverte ne porte de date de clôture dépassée.",
              "Une date dépassée n'est pas une affaire perdue : c'est une affaire dont la date n'a pas été tenue à jour. Tant qu'elle n'est pas requalifiée, elle gonfle le forecast du trimestre en cours.",
            ],
            kv: [
              ["Opportunités concernées", formatNumber(forecast.opportunities.filter((o) => o.at_risk).length)],
              ["Valeur pondérée", `${formatMFcfa(atRiskTotal)} M FCFA`],
            ],
            note: "Comparaison entre la date de clôture prévue dans Odoo et la date du jour.",
          }}
        />

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
                      note: "Étapes telles que définies dans le pipeline Odoo, sans regroupement par le cockpit.",
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
                  note: "Requalifier la date dans Odoo met à jour le forecast au prochain instantané. Le cockpit n'écrit jamais.",
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
          <FootNote>
            Amplitude bas/haut : {spreadPct !== null ? `${formatPct(spreadPct, 0)} %` : "—"} du scénario réaliste. Le
            calibrage de fiabilité par commercial démarre sa collecte de snapshots — un taux individuel sera disponible
            après quelques semaines d&apos;historique.
          </FootNote>
        </Tile>

        <Tile span={12} title="Ciblage cross-sell et renouvellement" kick="M1 · narration">
          <AnalysisSlot load={getCrossSellAnalysis} />
          {crosssell && (
            <div style={{ marginTop: 18 }}>
              <HintLine>Cliquez un compte pour le signal détaillé</HintLine>
              <Lst
                items={[
                  ...crosssell.renouvellement.slice(0, 3).map((it) => ({
                    title: it.client,
                    sub: it.detail,
                    tag: it.titre,
                    tagVariant: "w" as const,
                    detail: {
                      kicker: "Signal · renouvellement probable",
                      title: it.client,
                      tag: it.titre,
                      tagVariant: "w" as const,
                      body: [it.detail, `Montant historique associé : ${formatMFcfa(it.montant_xof)} M FCFA.`],
                      kv: [
                        ["Montant", `${formatMFcfa(it.montant_xof)} M FCFA`],
                        ["Type de signal", it.titre],
                      ],
                      note: "Signal calculé sur les lignes de commande réelles (catégories déjà achetées et ancienneté).",
                    },
                  })),
                  ...[...crosssell.cross_sell, ...crosssell.up_sell]
                    .sort((a, b) => b.montant_xof - a.montant_xof)
                    .slice(0, 3)
                    .map((it) => ({
                      title: it.client,
                      sub: it.detail,
                      tag: it.titre,
                      tagVariant: "a" as const,
                      detail: {
                        kicker: "Signal · vente additionnelle",
                        title: it.client,
                        tag: it.titre,
                        tagVariant: "a" as const,
                        body: [it.detail, `Montant historique associé : ${formatMFcfa(it.montant_xof)} M FCFA.`],
                        kv: [
                          ["Montant", `${formatMFcfa(it.montant_xof)} M FCFA`],
                          ["Type de signal", it.titre],
                        ],
                        note: "Comparaison de catégories achetées entre comptes de profil voisin, sur les commandes réelles.",
                      },
                    })),
                ]}
              />
            </div>
          )}
        </Tile>

        <Tile span={12} title="Analyse des motifs de perte" kick="narration">
          <AnalysisSlot load={getPerformanceAnalysis} />
        </Tile>

        {performance && (
          <>
            <Tile span={7} title="Où se concentrent les pertes" kick={`${formatNumber(performance.lost_deals.nb_total)} affaires`}>
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
                      note: "Opportunités marquées perdues dans Odoo, historique complet du miroir.",
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
                    note: "Opportunité close en perte dans le miroir Odoo.",
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
                    note: "CA rattaché au commercial renseigné sur la commande Odoo.",
                  },
                };
              })}
            />
            <FootNote>
              {topSalespeople[0].commercial} porte{" "}
              {top1Part !== null ? `${formatPct(top1Part, 0)} %` : "une large part"} du CA de l&apos;équipe
              {bottomSalesperson && bottomSalesperson.commercial !== topSalespeople[0].commercial
                ? ` ; ${bottomSalesperson.commercial} ferme le classement avec ${formatMFcfa(Number(bottomSalesperson.ca_total_xof))} M FCFA — à vérifier si c'est un portefeuille plus petit par construction ou une couverture insuffisante.`
                : "."}
            </FootNote>
          </Tile>
        )}
      </Bento>
    </>
  );
}
