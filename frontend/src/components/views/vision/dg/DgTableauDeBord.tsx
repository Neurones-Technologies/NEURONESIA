import { getBriefing } from "@/lib/api/briefing";
import {
  getBudgetVariance,
  getForecastPipelineWeighted,
  getKpis,
  getTopClients,
  getTopOrders,
} from "@/lib/api/dashboard";
import { formatDate, formatFcfa, formatNumber, formatPct, signedFcfa } from "@/lib/format";
import { Bars, Bento, Brief, HintLine, Lst, StatTile, Tile } from "@/components/ui/bento";
import { Section } from "@/components/ui/primitives";
import { MOIS_ABREV, toSpark } from "./commun";

/** Page d'ouverture du cockpit DG : le briefing du jour, les trois indicateurs
 * de cadrage, et les dépendances (comptes et commandes qui fragilisent
 * l'exercice). C'est la PREMIÈRE section déclarée (cf. lib/data/sections.ts) :
 * elle porte le `Brief` — les autres pages n'en ont pas, un cockpit n'a qu'un
 * panneau d'ouverture. */
export async function DgTableauDeBord() {
  const year = new Date().getFullYear();
  const [briefing, kpis, forecast, topClients, variance, topOrders] = await Promise.all([
    getBriefing(),
    getKpis(year),
    getForecastPipelineWeighted(),
    getTopClients(year, 10),
    getBudgetVariance(year),
    getTopOrders(year, 5),
  ]);

  const monthLabels = kpis.monthly.map((m) => MOIS_ABREV[m.mois - 1] ?? String(m.mois));
  const spark = toSpark(kpis.monthly.map((m) => m.ca_xof / 1_000_000));

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

  // Part du pondéré portée par des opportunités ouvertes à échéance DÉPASSÉE :
  // des affaires jamais mises à jour dans Odoo, comptées comme vivantes. Le
  // chiffre principal les inclut (elles sont ouvertes), mais la carte le dit —
  // sinon le pipeline se lit comme un carnet frais alors qu'une partie est à
  // requalifier ou à clore côté CRM.
  const oppsEchues = forecast.opportunities.filter((o) => o.at_risk);
  const pondereEchu = oppsEchues.reduce((s, o) => s + o.weighted_xof, 0);

  return (
    <Section id="tableau-de-bord">
      <Brief
        kicker={
          briefing?.generated_at
            ? `Briefing du ${formatDate(briefing.generated_at)} · chiffres arrêtés au ${formatDate(dateArret)}`
            : "Briefing de direction"
        }
        headline={
          `Exercice ${year} au ${formatDate(dateArret)} — ${formatFcfa(caArrete)} FCFA commandés`
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
        {/* `fill` sur les trois : seule la première porte une sparkline, sans
            lui les deux autres s'arrêtaient plus haut et la rangée se lisait
            comme trois cartes dépareillées. */}
        <StatTile
          span={4}
          fill
          label={`CA commandé ${year} au ${formatDate(dateArret)}`}
          aide="Ce que vos clients ont commandé depuis le 1er janvier. Ce sont des commandes fermes, pas des factures : l'argent n'est pas encore encaissé."
          value={formatFcfa(kpis.ytd.revenue_xof)}
          unit="FCFA"
          reading={
            revenueDeltaPct === null
              ? "pas de référence N-1"
              : `${revenueDeltaPct >= 0 ? "+" : ""}${formatPct(revenueDeltaPct)} % vs ${year - 1} à date comparable`
          }
          readingVariant={revenueDeltaPct === null ? undefined : revenueDeltaPct >= 0 ? "pos" : "neg"}
          spark={spark}
          sparkAxis={monthLabels}
          sparkLabels={kpis.monthly.map(
            (m) =>
              `${MOIS_ABREV[m.mois - 1] ?? m.mois} : ${formatFcfa(m.ca_xof)} FCFA (${formatNumber(m.nb_commandes)} commande(s))`
          )}
          detail={{
            kicker: "Indicateur · chiffre d'affaires",
            title: `CA commandé ${year} au ${formatDate(dateArret)}`,
            tag: revenueDeltaPct === null ? "sans référence" : revenueDeltaPct >= 0 ? "en hausse" : "en baisse",
            tagVariant: revenueDeltaPct === null ? "n" : revenueDeltaPct >= 0 ? "s" : "r",
            body: [
              `Cumul commandé au ${formatDate(dateArret)} : ${formatFcfa(kpis.ytd.revenue_xof)} FCFA, sur ${formatNumber(kpis.ytd.orders_count)} commandes et ${formatNumber(kpis.ytd.clients_with_orders)} clients ayant commandé.`,
              revenueDeltaPct === null
                ? "Aucun exercice précédent comparable dans le miroir, la variation ne peut pas être calculée."
                : `À la même date en ${year - 1}, le cumul était de ${formatFcfa(kpis.previous_ytd.revenue_xof)} FCFA, soit un écart de ${signedFcfa(kpis.ytd.revenue_xof - kpis.previous_ytd.revenue_xof)} FCFA.`,
            ],
            kv: [
              ["CA commandé", `${formatFcfa(kpis.ytd.revenue_xof)} FCFA`],
              [`${year - 1} à date comparable`, `${formatFcfa(kpis.previous_ytd.revenue_xof)} FCFA`],
              ["Commandes", formatNumber(kpis.ytd.orders_count)],
              ["Clients actifs", formatNumber(kpis.ytd.clients_with_orders)],
            ],
          }}
        />
        <StatTile
          span={4}
          fill
          label="Pipeline pondéré (réaliste)"
          aide="Ce que les affaires encore ouvertes devraient rapporter, en tenant compte de leurs chances d'aboutir. Les affaires gagnées, perdues ou abandonnées n'y entrent pas."
          value={formatFcfa(forecast.scenarios.realiste_xof)}
          unit="FCFA"
          reading={
            `probabilité moyenne ${formatPct(forecast.scenarios.avg_probability_pct, 0)} %` +
            (pondereEchu > 0
              ? ` · dont ${formatFcfa(pondereEchu)} à échéance dépassée (${formatNumber(oppsEchues.length)} opportunités à requalifier)`
              : "")
          }
          readingVariant={
            forecast.scenarios.realiste_xof && pondereEchu / forecast.scenarios.realiste_xof > 0.3
              ? "wat"
              : undefined
          }
          detail={{
            kicker: "Indicateur · pipeline",
            title: "Pipeline pondéré, scénario réaliste",
            tag: `${formatNumber(forecast.scenarios.nb_opportunites)} opportunités ouvertes`,
            tagVariant: "a",
            body: [
              `Le pipeline ouvert totalise ${formatFcfa(forecast.scenarios.total_pipeline_xof)} FCFA non pondérés. Pondéré par la probabilité déclarée sur chaque opportunité, il ressort à ${formatFcfa(forecast.scenarios.realiste_xof)} FCFA.`,
              `Le scénario bas (${formatFcfa(forecast.scenarios.pessimiste_xof)}) exclut les opportunités dont l'échéance est déjà dépassée ; le scénario haut (${formatFcfa(forecast.scenarios.optimiste_xof)}) retient l'ensemble des opportunités ouvertes.`,
              pondereEchu > 0
                ? `${formatNumber(oppsEchues.length)} opportunités encore ouvertes ont une échéance déjà dépassée, pour ${formatFcfa(pondereEchu)} FCFA pondérés. Ce ne sont pas des affaires vivantes tant qu'elles ne sont pas requalifiées dans Odoo : les compter sans le dire gonflerait le carnet.`
                : "",
            ].filter(Boolean),
            kv: [
              ["Pipeline non pondéré", `${formatFcfa(forecast.scenarios.total_pipeline_xof)} FCFA`],
              ["Scénario bas", `${formatFcfa(forecast.scenarios.pessimiste_xof)} FCFA`],
              ["Scénario réaliste", `${formatFcfa(forecast.scenarios.realiste_xof)} FCFA`],
              ["Scénario haut", `${formatFcfa(forecast.scenarios.optimiste_xof)} FCFA`],
              ["Probabilité moyenne", `${formatPct(forecast.scenarios.avg_probability_pct, 0)} %`],
              ["À échéance dépassée", `${formatFcfa(pondereEchu)} FCFA (${formatNumber(oppsEchues.length)} opp.)`],
            ],
          }}
        />
        <StatTile
          span={4}
          fill
          label="Concentration top 5"
          aide="La part de votre chiffre d'affaires portée par vos cinq plus gros clients. Plus elle est élevée, plus le départ de l'un d'eux serait difficile à absorber."
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
                ? `${top1.client} pèse à lui seul ${formatPct(top1Pct, 0)} % du CA commandé de l'exercice, pour ${formatFcfa(top1.ca_total_xof)} FCFA sur ${formatNumber(top1.nb_commandes)} commandes.`
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
              ["Base de calcul", `${formatFcfa(totalRevenue)} FCFA commandés`],
            ],
          }}
        />

        {/* Dépendances et risques — rapatrié de l'ancien onglet dédié : ces
            deux lectures cadrent la journée du DG au même titre que les trois
            indicateurs, elles se lisent donc dès l'ouverture. */}
        <Tile
          span={6}
          title="Top 5 des clients à risque"
          kick="part du CA commandé"
          aide="Le poids de chacun de vos plus gros clients. Sert à voir de qui votre activité dépend réellement."
        >
          <HintLine>Cliquez un compte pour son exposition</HintLine>
          <Bars
            rows={top5.map((c) => {
              const part = totalRevenue ? (c.ca_total_xof / totalRevenue) * 100 : 0;
              return {
                name: c.client,
                sub: `${c.pays} · ${formatNumber(c.nb_commandes)} commandes · ${formatPct(part, 0)} % du CA`,
                value: `${formatFcfa(c.ca_total_xof)}`,
                pct: top1 ? (c.ca_total_xof / top1.ca_total_xof) * 100 : 0,
                variant: part > 20 ? ("r" as const) : part > 10 ? ("w" as const) : undefined,
                detail: {
                  kicker: "Compte client",
                  title: c.client,
                  tag: part > 20 ? "dépendance forte" : part > 10 ? "à surveiller" : "exposition mesurée",
                  tagVariant: part > 20 ? ("r" as const) : part > 10 ? ("w" as const) : ("n" as const),
                  body: [
                    `${c.client} a commandé pour ${formatFcfa(c.ca_total_xof)} FCFA sur l'exercice, réparti sur ${formatNumber(c.nb_commandes)} commandes, soit ${formatPct(part, 0)} % du chiffre d'affaires total.`,
                    part > 20
                      ? "À ce niveau de poids, ce compte n'est plus un client parmi d'autres : son renouvellement conditionne l'atterrissage. Toute négociation le concernant est un arbitrage de direction, pas une décision commerciale."
                      : "Le poids de ce compte reste absorbable, mais il entre dans le calcul de concentration du top 5 suivi en tableau de bord.",
                  ],
                  kv: [
                    ["CA commandé", `${formatFcfa(c.ca_total_xof)} FCFA`],
                    ["Part du CA", `${formatPct(part, 0)} %`],
                    ["Commandes", formatNumber(c.nb_commandes)],
                    ["Pays", c.pays],
                  ],
                },
              };
            })}
          />
        </Tile>

        {/* La tuile ci-dessus classe des COMPTES ; celle-ci descend à la
            commande. Un compte modéré peut porter une affaire unique dont la
            perte se verrait à elle seule dans l'exercice — le classement par
            client ne la montre pas. */}
        {topOrders && topOrders.length > 0 && (
          <Tile
            span={6}
            title="Top 5 des plus grosses commandes de l'exercice"
            kick={`${year} · par montant signé`}
            aide="Les affaires les plus importantes prises une par une, et non regroupées par client. Une seule commande peut peser autant qu'un compte entier."
          >
            <HintLine>Cliquez une commande pour son poids dans l&apos;exercice</HintLine>
            <Lst
              items={topOrders.map((o) => {
                const part = totalRevenue ? (o.montant_xof / totalRevenue) * 100 : 0;
                return {
                  title: `${o.ref} · ${o.client}`,
                  sub: [
                    o.date ? `signée le ${formatDate(o.date)}` : "date non renseignée",
                    o.pays,
                    `${formatPct(part, 1)} % du CA de l'exercice`,
                  ].join(" · "),
                  tag: `${formatFcfa(o.montant_xof)}`,
                  tagVariant: part > 10 ? ("r" as const) : part > 5 ? ("w" as const) : ("n" as const),
                  detail: {
                    kicker: "Commande signée",
                    title: `${o.ref} · ${o.client}`,
                    tag:
                      part > 10 ? "affaire structurante" : part > 5 ? "affaire majeure" : "affaire notable",
                    tagVariant: part > 10 ? ("r" as const) : part > 5 ? ("w" as const) : ("n" as const),
                    body: [
                      `Cette commande de ${formatFcfa(o.montant_xof)} FCFA représente à elle seule ${formatPct(part, 1)} % du chiffre d'affaires commandé de l'exercice${o.date ? `, signée le ${formatDate(o.date)}` : ""}.`,
                      part > 10
                        ? "Une affaire unique de ce poids fait bouger l'atterrissage à elle seule : son exécution et son encaissement sont à suivre au niveau de la direction, pas seulement du compte."
                        : "Le poids de cette affaire reste absorbable, mais elle entre dans la concentration mesurée sur les comptes ci-dessus.",
                      "Le classement porte sur les commandes signées, sur la date de commande. Une commande peut donc apparaître dans cet exercice tout en portant une référence de l'exercice précédent.",
                    ],
                    kv: [
                      ["Montant", `${formatFcfa(o.montant_xof)} FCFA`],
                      ["Part du CA", `${formatPct(part, 1)} %`],
                      ["Client", o.client],
                      ["Référence", o.ref],
                      ["Date de commande", o.date ? formatDate(o.date) : "non renseignée"],
                      ["Pays", o.pays],
                    ],
                  },
                };
              })}
            />
          </Tile>
        )}
      </Bento>
    </Section>
  );
}
