import Link from "next/link";
import { getBriefing } from "@/lib/api/briefing";
import {
  getBudgetVariance,
  getForecastPipelineWeighted,
  getKpis,
  getMonthlyClients,
  getTopClients,
  getTrendAnalysis,
} from "@/lib/api/dashboard";
import { formatDate, formatMFcfa, formatNumber, formatPct, mFcfa, signed } from "@/lib/format";
import { Bars, Bento, Brief, FootNote, HintLine, StatTile, Tile } from "@/components/ui/bento";
import { Clickable } from "@/components/ui/detail";
import { Narr, Scen, ScenGrid, Section } from "@/components/ui/primitives";

// Les libellés du menu de sections vivent dans lib/data/sections.ts (importés
// par l'en-tête) ; ici seuls les `id` des <Section> doivent y correspondre.
const MOIS_ABREV = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sept", "Oct", "Nov", "Déc"];

/** Ramène une série à des hauteurs en % du plus haut point — la maquette
 * affiche les sparklines en indice, jamais en valeur absolue. */
function toSpark(values: number[]): number[] {
  const max = Math.max(...values, 0);
  if (!max) return values.map(() => 4);
  return values.map((v) => Math.round((v / max) * 100));
}

export async function DgVision() {
  const year = new Date().getFullYear();
  const [briefing, kpis, forecast, topClients, variance, monthlyClients] = await Promise.all([
    getBriefing(),
    getKpis(year),
    getForecastPipelineWeighted(),
    getTopClients(year, 10),
    getBudgetVariance(year),
    getMonthlyClients(year, 10),
  ]);

  const monthLabels = kpis.monthly.map((m) => MOIS_ABREV[m.mois - 1] ?? String(m.mois));
  const monthValuesM = kpis.monthly.map((m) => m.ca_xof / 1_000_000);
  const trendAnalysis = monthLabels.length >= 2 ? await getTrendAnalysis(monthLabels, monthValuesM) : null;
  const spark = toSpark(monthValuesM);

  // Comparaison à date comparable (même jour calendaire dans les deux années)
  // — kpis.year/previous_year comparent une année en cours à une année pleine,
  // ce qui produit un écart artificiel tant que l'exercice n'est pas clos.
  const revenueDeltaPct = kpis.previous_ytd.revenue_xof
    ? ((kpis.ytd.revenue_xof - kpis.previous_ytd.revenue_xof) / kpis.previous_ytd.revenue_xof) * 100
    : null;

  // Le titre lit le fait figé par le briefing (même source que ses puces),
  // avec repli sur le direct : titre et puces ne peuvent plus afficher deux
  // chiffres différents pour le même indicateur.
  const dgFacts = (briefing?.section?.facts ?? {}) as Record<string, unknown>;
  const caArrete = typeof dgFacts.ca_ytd_xof === "number" ? dgFacts.ca_ytd_xof : kpis.ytd.revenue_xof;
  const dateArret = typeof dgFacts.date_arret === "string" ? dgFacts.date_arret : kpis.ytd.as_of;

  const totalRevenue = kpis.year.revenue_xof;
  const top1 = topClients?.[0];
  const top5 = (topClients ?? []).slice(0, 5);
  const top5Sum = top5.reduce((s, c) => s + c.ca_total_xof, 0);
  const top10Sum = (topClients ?? []).reduce((s, c) => s + c.ca_total_xof, 0);
  const top1Pct = top1 && totalRevenue ? (top1.ca_total_xof / totalRevenue) * 100 : null;
  const top5Pct = totalRevenue ? (top5Sum / totalRevenue) * 100 : null;
  const top10Pct = totalRevenue ? (top10Sum / totalRevenue) * 100 : null;

  // Combien des 5 premiers comptes de l'exercice sont de nouveaux clients (pas
  // de commande l'année précédente) — un top5 gagné par la CA la plus haute
  // parmi les clients gagnés (top_clients_gagnes) contient nécessairement tout
  // client du top5 global qui est nouveau, donc ce chiffre est exact, pas une
  // estimation.
  const newClientNames = new Set(variance.top_clients_gagnes.map((c) => c.client));
  const nbTop5Nouveaux = top5.filter((c) => newClientNames.has(c.client)).length;

  // Résumé IA en 5 lignes en tête ; repli sur les faits bruts si le briefing
  // du jour a été généré avant l'ajout du résumé.
  const briefLines = briefing?.section?.resume?.length
    ? briefing.section.resume
    : (briefing?.section?.bullets ?? []).slice(0, 5);

  const maxMonth = Math.max(...monthValuesM, 0);

  return (
    <>
      <Section id="tableau-de-bord">
        <Brief
          kicker={
            briefing?.generated_at
              ? `Briefing du ${formatDate(briefing.generated_at)} · chiffres arrêtés au ${formatDate(dateArret)}`
              : "Briefing de direction"
          }
          headline={
            `Exercice ${year} au ${formatDate(dateArret)} — ${formatMFcfa(caArrete)} M FCFA commandés`
            + (revenueDeltaPct !== null
              ? `, ${revenueDeltaPct >= 0 ? "+" : ""}${formatPct(revenueDeltaPct, 0)} % vs ${year - 1} à date comparable`
              : "")
            + "."
          }
          lines={briefLines}
          paragraphs={
            briefLines.length ? undefined : ["Briefing pas encore généré pour ce profil."]
          }
          pills={[
            { label: `${formatNumber(kpis.ytd.orders_count)} commandes`, hot: false },
            { label: `${formatNumber(forecast.scenarios.nb_opportunites)} opportunités ouvertes`, hot: false },
            {
              label: top5Pct !== null ? `Top 5 · ${formatPct(top5Pct, 0)} % du CA` : "Concentration inconnue",
              hot: top5Pct !== null && top5Pct > 50,
            },
            { label: briefing?.triggered_by ? `Source · ${briefing.triggered_by}` : "Miroir Odoo", hot: false },
          ]}
        />

        <Bento>
          <StatTile
            span={4}
            label={`CA commandé ${year} au ${formatDate(dateArret)}`}
            value={formatMFcfa(kpis.ytd.revenue_xof)}
            unit="M FCFA"
            reading={
              revenueDeltaPct === null
                ? "pas de référence N-1"
                : `${revenueDeltaPct >= 0 ? "+" : ""}${formatPct(revenueDeltaPct)} % vs ${year - 1} à date comparable`
            }
            readingVariant={revenueDeltaPct === null ? undefined : revenueDeltaPct >= 0 ? "pos" : "neg"}
            spark={spark}
            sparkAxis={monthLabels}
            detail={{
              kicker: "Indicateur · chiffre d'affaires",
              title: `CA commandé ${year} au ${formatDate(dateArret)}`,
              tag: revenueDeltaPct === null ? "sans référence" : revenueDeltaPct >= 0 ? "en hausse" : "en baisse",
              tagVariant: revenueDeltaPct === null ? "n" : revenueDeltaPct >= 0 ? "s" : "r",
              body: [
                `Cumul commandé au ${formatDate(dateArret)} : ${formatMFcfa(kpis.ytd.revenue_xof)} M FCFA, sur ${formatNumber(kpis.ytd.orders_count)} commandes et ${formatNumber(kpis.ytd.clients_with_orders)} clients ayant commandé.`,
                revenueDeltaPct === null
                  ? "Aucun exercice précédent comparable dans le miroir, la variation ne peut pas être calculée."
                  : `À la même date en ${year - 1}, le cumul était de ${formatMFcfa(kpis.previous_ytd.revenue_xof)} M FCFA, soit un écart de ${signed(mFcfa(kpis.ytd.revenue_xof - kpis.previous_ytd.revenue_xof))} M FCFA.`,
              ],
              kv: [
                ["CA commandé", `${formatMFcfa(kpis.ytd.revenue_xof)} M FCFA`],
                [`${year - 1} à date comparable`, `${formatMFcfa(kpis.previous_ytd.revenue_xof)} M FCFA`],
                ["Commandes", formatNumber(kpis.ytd.orders_count)],
                ["Clients actifs", formatNumber(kpis.ytd.clients_with_orders)],
              ],
              note: "Somme des bons de commande confirmés (sale.order en état sale/done) du miroir Odoo, arrêtée au même jour calendaire que l'année précédente. Ce n'est pas du CA facturé : la facturation se suit en vue Trésorerie. Le cockpit lit, il n'écrit jamais.",
            }}
          />
          <StatTile
            span={4}
            label="Pipeline pondéré (réaliste)"
            value={formatMFcfa(forecast.scenarios.realiste_xof)}
            unit="M FCFA"
            reading={`probabilité moyenne ${formatPct(forecast.scenarios.avg_probability_pct, 0)} %`}
            detail={{
              kicker: "Indicateur · pipeline",
              title: "Pipeline pondéré, scénario réaliste",
              tag: `${formatNumber(forecast.scenarios.nb_opportunites)} opportunités`,
              tagVariant: "a",
              body: [
                `Le pipeline ouvert totalise ${formatMFcfa(forecast.scenarios.total_pipeline_xof)} M FCFA non pondérés. Pondéré par la probabilité déclarée sur chaque opportunité, il ressort à ${formatMFcfa(forecast.scenarios.realiste_xof)} M FCFA.`,
                `Le scénario bas (${formatMFcfa(forecast.scenarios.pessimiste_xof)} M) exclut les opportunités dont l'échéance est déjà dépassée ; le scénario haut (${formatMFcfa(forecast.scenarios.optimiste_xof)} M) retient l'ensemble des opportunités ouvertes.`,
              ],
              kv: [
                ["Pipeline non pondéré", `${formatMFcfa(forecast.scenarios.total_pipeline_xof)} M FCFA`],
                ["Scénario bas", `${formatMFcfa(forecast.scenarios.pessimiste_xof)} M FCFA`],
                ["Scénario réaliste", `${formatMFcfa(forecast.scenarios.realiste_xof)} M FCFA`],
                ["Scénario haut", `${formatMFcfa(forecast.scenarios.optimiste_xof)} M FCFA`],
                ["Probabilité moyenne", `${formatPct(forecast.scenarios.avg_probability_pct, 0)} %`],
              ],
              note: "Probabilité issue du champ renseigné sur l'opportunité Odoo (crm.lead), jamais recalculée par le cockpit.",
            }}
          />
          <StatTile
            span={4}
            label="Concentration top 5"
            value={top5Pct !== null ? `${formatPct(top5Pct, 0)}` : "—"}
            unit={top5Pct !== null ? "% du CA" : undefined}
            reading={
              top5Pct === null
                ? "concentration non calculable"
                : top5Pct > 50
                  ? "au-delà du seuil de 50 %"
                  : "sous le seuil de 50 %"
            }
            readingVariant={top5Pct !== null && top5Pct > 50 ? "neg" : "wat"}
            detail={{
              kicker: "Indicateur · dépendance client",
              title: "Concentration du chiffre d'affaires",
              tag: top5Pct !== null && top5Pct > 50 ? "risque structurel" : "à surveiller",
              tagVariant: top5Pct !== null && top5Pct > 50 ? "r" : "w",
              body: [
                top1 && top1Pct !== null
                  ? `${top1.client} pèse à lui seul ${formatPct(top1Pct, 0)} % du CA commandé de l'exercice, pour ${formatMFcfa(top1.ca_total_xof)} M FCFA sur ${formatNumber(top1.nb_commandes)} commandes.`
                  : "Aucun client n'a commandé sur l'exercice.",
                top5Pct !== null && top5Pct > 50
                  ? "Plus de la moitié du chiffre d'affaires dépend de cinq comptes. À ce niveau, la perte d'un seul client déplace l'atterrissage de l'exercice : c'est une exposition à arbitrer, pas une statistique à consulter."
                  : "La concentration reste sous le seuil de 50 %, mais mérite un suivi à chaque renouvellement de contrat cadre.",
                ...(nbTop5Nouveaux > 0
                  ? [
                      `${nbTop5Nouveaux} des ${top5.length} premiers comptes sont de nouveaux clients en ${year} : la concentration est faible parce que le portefeuille historique s'est arrêté, pas parce qu'il s'est élargi.`,
                    ]
                  : []),
              ],
              kv: [
                ["Top 1", top1Pct !== null ? `${formatPct(top1Pct, 0)} %` : "—"],
                ["Top 5 cumulé", top5Pct !== null ? `${formatPct(top5Pct, 0)} %` : "—"],
                ["Top 10 cumulé", top10Pct !== null ? `${formatPct(top10Pct, 0)} %` : "—"],
                ["Base de calcul", `${formatMFcfa(totalRevenue)} M FCFA commandés`],
              ],
              note: "Part calculée sur le CA commandé de l'exercice en cours, pas sur le carnet de commandes.",
            }}
          />

        </Bento>
      </Section>

      <Section id="trajectoire" title="Trajectoire financière" subtitle="Où atterrit l'exercice, et pourquoi">
        <Bento>
          <Tile span={7} title="Atterrissage et scénarios" kick="pipeline pondéré Odoo">
            <ScenGrid>
              <Scen
                label="Scénario bas"
                value={formatMFcfa(forecast.scenarios.pessimiste_xof)}
                detail={<>M FCFA · hors opportunités à risque</>}
              />
              <Scen
                mid
                label="Réaliste · retenu"
                value={formatMFcfa(forecast.scenarios.realiste_xof)}
                detail={<>M FCFA · probabilité moyenne {formatPct(forecast.scenarios.avg_probability_pct, 0)} %</>}
              />
              <Scen
                label="Scénario haut"
                value={formatMFcfa(forecast.scenarios.optimiste_xof)}
                detail={<>M FCFA · {formatNumber(forecast.scenarios.nb_opportunites)} opportunités</>}
              />
            </ScenGrid>
            {/* <FootNote>
              Pipeline total non pondéré : {formatMFcfa(forecast.scenarios.total_pipeline_xof)} M FCFA. Le scénario bas
              exclut les opportunités dont l&apos;échéance est déjà dépassée.
            </FootNote> */}
          </Tile>

          <Tile span={5} title="Commandes par mois" kick={`exercice ${year}`}>
            <HintLine>Cliquez un mois pour son détail</HintLine>
            <Bars
              rows={kpis.monthly.map((m, i) => {
                const clients = monthlyClients.months[String(m.mois)] ?? [];
                return {
                  name: monthLabels[i],
                  sub: `${formatMFcfa(m.ca_xof)} M FCFA commandés`,
                  value: `${formatMFcfa(m.ca_xof)} M`,
                  pct: maxMonth ? (m.ca_xof / 1_000_000 / maxMonth) * 100 : 0,
                  detail: {
                    kicker: `Commandes · ${monthLabels[i]} ${year}`,
                    title: `${monthLabels[i]} ${year}`,
                    tag: `${formatMFcfa(m.ca_xof)} M FCFA`,
                    tagVariant: "a" as const,
                    body: [
                      `Le mois de ${monthLabels[i].toLowerCase()} totalise ${formatMFcfa(m.ca_xof)} M FCFA de commandes confirmées, soit ${maxMonth ? formatPct((m.ca_xof / 1_000_000 / maxMonth) * 100, 0) : "0"} % du meilleur mois de l'exercice.`,
                    ],
                    kv: clients.length
                      ? clients.map((c) => [`${c.nb_commandes} commande${c.nb_commandes > 1 ? "s" : ""}`, c.client] as const)
                      : [["Aucune commande", "—"] as const],
                    note: "Top clients du mois par nombre de commandes confirmées (sale.order), miroir Odoo.",
                  },
                };
              })}
            />
          </Tile>

          {/* <Tile span={12} title="Lecture de la trajectoire" kick="narration · M5">
            {trendAnalysis ? (
              <AnalysisNarr text={trendAnalysis.analysis} />
            ) : (
              <Note style={{ marginTop: 0 }}>Historique mensuel insuffisant pour une analyse de tendance.</Note>
            )}
          </Tile> */}

          <Tile span={12} title="Explication d'écart budgétaire" kick={`${variance.annee} vs ${variance.annee_precedente}`}>
            <HintLine>Cliquez un effet pour les clients concernés</HintLine>
            <div style={{ overflowX: "auto" }}>
              <table className="tb">
                <thead>
                  <tr>
                    <th>Effet</th>
                    <th className="r">M FCFA</th>
                    <th>Lecture</th>
                  </tr>
                </thead>
                <tbody>
                  <Clickable
                    as="tr"
                    detail={{
                      kicker: "Effet · clients retenus",
                      title: "Clients actifs les deux exercices",
                      tag: variance.effet_clients_retenus_xof >= 0 ? "contribution positive" : "contribution négative",
                      tagVariant: variance.effet_clients_retenus_xof >= 0 ? "s" : "r",
                      body: [
                        `${formatNumber(variance.nb_clients_retenus)} clients ont commandé sur les deux exercices. Leur contribution nette à l'écart est de ${signed(mFcfa(variance.effet_clients_retenus_xof))} M FCFA.`,
                        "C'est l'effet le plus actionnable des trois : ces comptes existent déjà et la relation est ouverte, contrairement aux clients perdus qu'il faut reconquérir.",
                      ],
                      kv: [
                        ["Effet net", `${signed(mFcfa(variance.effet_clients_retenus_xof))} M FCFA`],
                        ["Clients concernés", formatNumber(variance.nb_clients_retenus)],
                      ],
                      note: variance.note,
                    }}
                  >
                    <td>Clients retenus</td>
                    <td className={`r mono ${variance.effet_clients_retenus_xof >= 0 ? "up" : "dn"}`}>
                      {signed(mFcfa(variance.effet_clients_retenus_xof))}
                    </td>
                    <td>{formatNumber(variance.nb_clients_retenus)} clients actifs les deux années</td>
                  </Clickable>
                  <Clickable
                    as="tr"
                    detail={{
                      kicker: "Effet · clients gagnés",
                      title: `Nouveaux clients ${variance.annee}`,
                      tag: "acquisition",
                      tagVariant: "s",
                      body: [
                        `${formatNumber(variance.nb_clients_gagnes)} clients ont commandé pour la première fois en ${variance.annee}, apportant ${formatMFcfa(variance.effet_clients_gagnes_xof)} M FCFA.`,
                        variance.top_clients_gagnes[0]
                          ? `Le plus important est ${variance.top_clients_gagnes[0].client}, pour ${formatMFcfa(variance.top_clients_gagnes[0].ca_xof)} M FCFA.`
                          : "Aucun nouveau client identifié sur l'exercice.",
                      ],
                      kv: [
                        ["Apport", `+${formatMFcfa(variance.effet_clients_gagnes_xof)} M FCFA`],
                        ["Clients gagnés", formatNumber(variance.nb_clients_gagnes)],
                        ...variance.top_clients_gagnes.slice(0, 3).map(
                          (c) => [c.client, `${formatMFcfa(c.ca_xof)} M FCFA`] as [string, string]
                        ),
                      ],
                      note: variance.note,
                    }}
                  >
                    <td>Clients gagnés</td>
                    <td className="r mono up">+{formatMFcfa(variance.effet_clients_gagnes_xof)}</td>
                    <td>
                      {formatNumber(variance.nb_clients_gagnes)} nouveaux clients {variance.annee}
                    </td>
                  </Clickable>
                  <Clickable
                    as="tr"
                    detail={{
                      kicker: "Effet · clients perdus",
                      title: `Clients silencieux depuis ${variance.annee_precedente}`,
                      tag: "à reconquérir",
                      tagVariant: "r",
                      body: [
                        `${formatNumber(variance.nb_clients_perdus)} clients actifs en ${variance.annee_precedente} n'ont plus commandé en ${variance.annee}, soit ${signed(mFcfa(variance.effet_clients_perdus_xof))} M FCFA de manque.`,
                        variance.top_clients_perdus[0]
                          ? `Le premier d'entre eux, ${variance.top_clients_perdus[0].client}, pesait ${formatMFcfa(variance.top_clients_perdus[0].ca_xof)} M FCFA. Un silence de cette taille sur un compte déjà servi mérite un appel avant d'être traité comme une perte définitive.`
                          : "Aucun client perdu identifié sur l'exercice.",
                      ],
                      kv: [
                        ["Manque", `${signed(mFcfa(variance.effet_clients_perdus_xof))} M FCFA`],
                        ["Clients perdus", formatNumber(variance.nb_clients_perdus)],
                        ...variance.top_clients_perdus.slice(0, 3).map(
                          (c) => [c.client, `${formatMFcfa(c.ca_xof)} M FCFA`] as [string, string]
                        ),
                      ],
                      note: variance.note,
                    }}
                  >
                    <td>Clients perdus</td>
                    <td className="r mono dn">{signed(mFcfa(variance.effet_clients_perdus_xof))}</td>
                    <td>
                      {formatNumber(variance.nb_clients_perdus)} clients actifs {variance.annee_precedente}, silencieux
                      depuis
                    </td>
                  </Clickable>
                </tbody>
              </table>
            </div>
            <Narr style={{ marginTop: 16 }}>
              <p>
                Écart total {variance.annee} vs {variance.annee_precedente} :{" "}
                <b className={variance.ecart_total_xof >= 0 ? "up" : "dn"}>
                  {signed(mFcfa(variance.ecart_total_xof))} M FCFA
                </b>
                . Premier client perdu : {variance.top_clients_perdus[0]?.client ?? "—"} (
                {formatMFcfa(variance.top_clients_perdus[0]?.ca_xof)} M). Premier client gagné :{" "}
                {variance.top_clients_gagnes[0]?.client ?? "—"} (
                {formatMFcfa(variance.top_clients_gagnes[0]?.ca_xof)} M).
              </p>
            </Narr>
            {/* <FootNote>{variance.note}</FootNote> */}
          </Tile>
        </Bento>
      </Section>

      <Section id="risques" title="Dépendances et risques" subtitle="Ce qui fragilise l'entreprise">
        <Bento>
          <Tile span={7} title="Où se concentre le risque client" kick="part du CA commandé">
            <HintLine>Cliquez un compte pour son exposition</HintLine>
            <Bars
              rows={(topClients ?? []).slice(0, 5).map((c) => {
                const part = totalRevenue ? (c.ca_total_xof / totalRevenue) * 100 : 0;
                return {
                  name: c.client,
                  sub: `${c.pays} · ${formatNumber(c.nb_commandes)} commandes · ${formatPct(part, 0)} % du CA`,
                  value: `${formatMFcfa(c.ca_total_xof)} M`,
                  pct: top1 ? (c.ca_total_xof / top1.ca_total_xof) * 100 : 0,
                  variant: part > 20 ? ("r" as const) : part > 10 ? ("w" as const) : undefined,
                  detail: {
                    kicker: "Compte client",
                    title: c.client,
                    tag: part > 20 ? "dépendance forte" : part > 10 ? "à surveiller" : "exposition mesurée",
                    tagVariant: part > 20 ? ("r" as const) : part > 10 ? ("w" as const) : ("n" as const),
                    body: [
                      `${c.client} a commandé pour ${formatMFcfa(c.ca_total_xof)} M FCFA sur l'exercice, réparti sur ${formatNumber(c.nb_commandes)} commandes, soit ${formatPct(part, 0)} % du chiffre d'affaires total.`,
                      part > 20
                        ? "À ce niveau de poids, ce compte n'est plus un client parmi d'autres : son renouvellement conditionne l'atterrissage. Toute négociation le concernant est un arbitrage de direction, pas une décision commerciale."
                        : "Le poids de ce compte reste absorbable, mais il entre dans le calcul de concentration du top 5 suivi en tableau de bord.",
                    ],
                    kv: [
                      ["CA commandé", `${formatMFcfa(c.ca_total_xof)} M FCFA`],
                      ["Part du CA", `${formatPct(part, 0)} %`],
                      ["Commandes", formatNumber(c.nb_commandes)],
                      ["Pays", c.pays],
                    ],
                    note: "Chiffres issus des bons de commande du miroir Odoo. Le détail par dossier est accessible depuis le Copilote.",
                  },
                };
              })}
            />
            {/* <FootNote>
              {top5Pct !== null
                ? `Les cinq premiers comptes cumulent ${formatPct(top5Pct, 0)} % du CA facturé${top5Pct > 50 ? " — au-delà du seuil de 50 %, la dépendance devient un risque structurel." : "."}`
                : "Concentration non calculable sur cet exercice."}
            </FootNote> */}
          </Tile>

          <Tile span={5} title="Paliers de concentration" kick="cumul du CA">
            <Bars
              rows={[
                ...(top1Pct !== null && top1
                  ? [
                      {
                        name: `Top 1 · ${top1.client}`,
                        sub: "premier compte du portefeuille",
                        value: `${formatPct(top1Pct, 0)} %`,
                        pct: top1Pct,
                        variant: top1Pct > 20 ? ("r" as const) : ("w" as const),
                      },
                    ]
                  : []),
                ...(top5Pct !== null
                  ? [
                      {
                        name: "Top 5 cumulé",
                        sub: "seuil interne de vigilance : 50 %",
                        value: `${formatPct(top5Pct, 0)} %`,
                        pct: top5Pct,
                        variant: top5Pct > 50 ? ("r" as const) : ("w" as const),
                      },
                    ]
                  : []),
                ...(top10Pct !== null
                  ? [
                      {
                        name: "Top 10 cumulé",
                        sub: "reste du portefeuille au-delà",
                        value: `${formatPct(top10Pct, 0)} %`,
                        pct: top10Pct,
                        variant: "w" as const,
                      },
                    ]
                  : []),
              ]}
            />
            {/* <FootNote>
              La dépendance fournisseur et le poids de la sous-traitance ne sont pas accessibles depuis ce profil — cf.
              Direction des opérations.
            </FootNote> */}
          </Tile>
        </Bento>
      </Section>

      {/* <Section id="copilote" title="Copilote" subtitle="Poser une question directement">
        <Bento>
          <Tile span={12} quiet title="Interrogation en langage naturel" kick="sémantique · M5">
            <p style={{ margin: "0 0 4px", fontSize: 14, color: "var(--t2)", lineHeight: 1.6 }}>
              Le Copilote interroge le même miroir Odoo, avec les outils réels (CRM, factures, statistiques) — jamais de
              donnée inventée. Si une donnée manque, il le dit plutôt que de l&apos;estimer.
            </p>
            <div className="acts">
              <Link className="btn btn--p" href="/dg/copilot">
                Ouvrir Mon Copilote
              </Link>
            </div>
          </Tile>
        </Bento>
      </Section> */}
    </>
  );
}
