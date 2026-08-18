import Link from "next/link";
import { getBriefing } from "@/lib/api/briefing";
import {
  getBudgetVariance,
  getForecastPipelineWeighted,
  getKpis,
  getMonthlyClients,
  getPilotageDg,
  getTopClients,
  getTopOrders,
} from "@/lib/api/dashboard";
import { formatDate, formatMFcfa, formatNumber, formatPct, mFcfa, signed } from "@/lib/format";
import { Bars, Bento, Brief, /* FootNote, */ HintLine, Lst, StatTile, Tile } from "@/components/ui/bento";
import { Clickable } from "@/components/ui/detail";
import { Narr, Section } from "@/components/ui/primitives";
import { ScenPanel } from "@/components/ui/scen-panel";

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
  const [briefing, kpis, forecast, topClients, topOrders, variance, monthlyClients, pilotage] =
    await Promise.all([
      getBriefing(),
      getKpis(year),
      getForecastPipelineWeighted(),
      getTopClients(year, 10),
      getTopOrders(year, 5),
      getBudgetVariance(year),
      getMonthlyClients(year, 10),
      getPilotageDg(year),
    ]);

  const monthLabels = kpis.monthly.map((m) => MOIS_ABREV[m.mois - 1] ?? String(m.mois));
  const monthValuesM = kpis.monthly.map((m) => m.ca_xof / 1_000_000);

  // Détail des scénarios (Trajectoire financière) : recalculé côté vue pour donner
  // un "pourquoi" chiffré au clic, à partir des mêmes opportunités que le backend
  // (uc_forecast/aggregation.py) — jamais une approximation inventée dans la vue.
  const oppsAtRisque = forecast.opportunities.filter((o) => o.probability_pct < 50);
  const nbAtRisque = oppsAtRisque.length;
  const pondereAtRisque = oppsAtRisque.reduce((sum, o) => sum + o.weighted_xof, 0);
  const bonusHaut = forecast.scenarios.optimiste_xof - forecast.scenarios.realiste_xof;
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

  // ── Pilotage de l'activité (vue 360) — dérivés calculés une fois ──────────
  // `pilotage` est null si le module `dashboard` est refusé au rôle (403 absorbé).
  const meilleureAnnee =
    pilotage && pilotage.ca_annuel.length
      ? pilotage.ca_annuel.reduce((a, b) => (b.ca_xof > a.ca_xof ? b : a))
      : null;
  const anneeCourante =
    pilotage && pilotage.ca_annuel.length
      ? pilotage.ca_annuel[pilotage.ca_annuel.length - 1]
      : null;
  const partMeilleurePct =
    meilleureAnnee && anneeCourante && meilleureAnnee.ca_xof
      ? (anneeCourante.ca_xof / meilleureAnnee.ca_xof) * 100
      : null;
  // Le DSO peut revenir en `{error}` quand le miroir n'a aucune facture.
  const encaissement =
    pilotage && !("error" in pilotage.encaissement) ? pilotage.encaissement : null;
  const commerciauxActifs = (pilotage?.commerciaux ?? []).filter((c) => c.ca_total_xof > 0);
  const commerciauxTotal = commerciauxActifs.reduce((s, c) => s + c.ca_total_xof, 0);
  const maxCommercial = Math.max(...commerciauxActifs.map((c) => c.ca_total_xof), 0);
  const maxMensuel = Math.max(...(pilotage?.mensuel ?? []).map((m) => m.ca_xof), 0);
  const prochaineEcheance = pilotage?.echeances.prochaines[0] ?? null;

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
            aide="Ce que vos clients ont commandé depuis le 1er janvier. Ce sont des commandes fermes, pas des factures : l'argent n'est pas encore encaissé."
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
              // note: "Somme des bons de commande confirmés (sale.order en état sale/done) du miroir Odoo, arrêtée au même jour calendaire que l'année précédente. Ce n'est pas du CA facturé : la facturation se suit en vue Trésorerie. Le cockpit lit, il n'écrit jamais.",
            }}
          />
          <StatTile
            span={4}
            label="Pipeline pondéré (réaliste)"
            aide="Ce que les affaires en cours devraient rapporter, en tenant compte de leurs chances d'aboutir. Le scénario médian, ni optimiste ni prudent."
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
              // note: "Probabilité issue du champ renseigné sur l'opportunité Odoo (crm.lead), jamais recalculée par le cockpit.",
            }}
          />
          <StatTile
            span={4}
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
              // note: "Part calculée sur le CA commandé de l'exercice en cours, pas sur le carnet de commandes.",
            }}
          />

        </Bento>
      </Section>

      <Section id="trajectoire" title="Trajectoire financière" subtitle="Où atterrit l'exercice, et pourquoi">
        <Bento>
          <Tile
            span={7}
            title="Atterrissage et scénarios"
            kick="pipeline pondéré Odoo"
            aide="Où devrait finir l'année selon trois hypothèses : prudente, réaliste, optimiste. L'écart entre les trois dit à quel point la fin d'exercice est incertaine."
          >
            <ScenPanel
              items={[
                {
                  label: "Scénario bas",
                  value: formatMFcfa(forecast.scenarios.pessimiste_xof),
                  detail: <>M FCFA · hors opportunités à risque</>,
                  narrative: {
                    kicker: "Méthode de calcul · scénario bas",
                    title: "Scénario bas",
                    tag: "plancher",
                    tagVariant: "w",
                    body: [
                      `Ce scénario ne retient que les opportunités dont la probabilité de conversion Odoo est d'au moins 50 %, pondérées par cette probabilité. Les ${formatNumber(nbAtRisque)} opportunités sous ce seuil (${formatMFcfa(pondereAtRisque)} M FCFA pondérés dans le scénario réaliste) en sont entièrement exclues, pas seulement décotées.`,
                      "C'est un plancher volontairement pessimiste : si aucune opportunité incertaine n'aboutit, c'est le chiffre qu'on peut sécuriser sans hypothèse supplémentaire.",
                    ],
                    kv: [
                      ["Opportunités retenues (≥ 50 %)", formatNumber(forecast.scenarios.nb_opportunites - nbAtRisque)],
                      ["Opportunités exclues (< 50 %)", formatNumber(nbAtRisque)],
                      ["Écart avec le réaliste", `-${formatMFcfa(forecast.scenarios.realiste_xof - forecast.scenarios.pessimiste_xof)} M FCFA`],
                    ],
                  },
                },
                {
                  mid: true,
                  label: "Réaliste · retenu",
                  value: formatMFcfa(forecast.scenarios.realiste_xof),
                  detail: <>M FCFA · probabilité moyenne {formatPct(forecast.scenarios.avg_probability_pct, 0)} %</>,
                  narrative: {
                    kicker: "Méthode de calcul · scénario retenu",
                    title: "Scénario réaliste",
                    tag: "retenu en comité",
                    tagVariant: "a",
                    body: [
                      `Chaque opportunité ouverte pèse pour sa valeur multipliée par sa probabilité de conversion Odoo — sans exclusion ni bonus. C'est la somme pondérée sur les ${formatNumber(forecast.scenarios.nb_opportunites)} opportunités du pipeline, probabilité moyenne ${formatPct(forecast.scenarios.avg_probability_pct, 0)} %.`,
                      "C'est ce chiffre qui sert de référence d'atterrissage, parce qu'il ne fait ni l'hypothèse optimiste que les dossiers incertains se débloquent, ni l'hypothèse pessimiste qu'ils n'aboutiront jamais.",
                    ],
                    kv: [
                      ["Pipeline brut (non pondéré)", `${formatMFcfa(forecast.scenarios.total_pipeline_xof)} M FCFA`],
                      ["Pipeline pondéré retenu", `${formatMFcfa(forecast.scenarios.realiste_xof)} M FCFA`],
                      ["Taux de pondération global", forecast.scenarios.total_pipeline_xof ? `${formatPct((forecast.scenarios.realiste_xof / forecast.scenarios.total_pipeline_xof) * 100, 0)} %` : "—"],
                    ],
                  },
                },
                {
                  label: "Scénario haut",
                  value: formatMFcfa(forecast.scenarios.optimiste_xof),
                  detail: <>M FCFA · {formatNumber(forecast.scenarios.nb_opportunites)} opportunités</>,
                  narrative: {
                    kicker: "Méthode de calcul · scénario haut",
                    title: "Scénario haut",
                    tag: "hypothèse optimiste",
                    tagVariant: "n",
                    body: [
                      `Part du même socle que le scénario réaliste (${formatMFcfa(forecast.scenarios.realiste_xof)} M FCFA), puis ajoute un bonus sur les ${formatNumber(nbAtRisque)} opportunités sous 50 % de probabilité : chacune est recomptée à 50 % de sa valeur au lieu de sa probabilité réelle, souvent plus faible.`,
                      "Ce n'est pas une probabilité mesurée qui remonte à 50 % — c'est une hypothèse forfaitaire volontairement optimiste sur les dossiers incertains, à ne pas annoncer comme un chiffre plus fiable que le réaliste.",
                    ],
                    kv: [
                      ["Socle réaliste", `${formatMFcfa(forecast.scenarios.realiste_xof)} M FCFA`],
                      ["Bonus opportunités < 50 %", `+${formatMFcfa(bonusHaut)} M FCFA`],
                      ["Opportunités concernées", formatNumber(nbAtRisque)],
                    ],
                  },
                },
              ]}
            />
            {/* <FootNote>
              Pipeline total non pondéré : {formatMFcfa(forecast.scenarios.total_pipeline_xof)} M FCFA. Le scénario bas
              exclut les opportunités dont l&apos;échéance est déjà dépassée.
            </FootNote> */}
          </Tile>

          <Tile
            span={5}
            title="Commandes par mois"
            kick={`exercice ${year}`}
            aide="Le rythme des commandes mois par mois. Fait apparaître la saisonnalité et les mois creux."
          >
            <HintLine>Cliquez un mois pour son détail</HintLine>
            <Bars
              rows={kpis.monthly.map((m, i) => {
                const clients = monthlyClients.months[String(m.mois)] ?? [];
                return {
                  name: monthLabels[i],
                  sub: `${formatNumber(m.nb_commandes)} commande${m.nb_commandes > 1 ? "s" : ""} · ${formatMFcfa(m.ca_xof)} M FCFA commandés`,
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
                      ? clients.map((c) => [c.client, `${formatMFcfa(c.ca_xof)} M FCFA`] as const)
                      : [["Aucune commande", "—"] as const],
                    // note: "Top clients du mois par nombre de commandes confirmées (sale.order), miroir Odoo.",
                  },
                };
              })}
            />
          </Tile>

          {/* Tuile désactivée. Pour la remettre, décommenter tel quel : l'appel
              LLM (12 s au premier passage) vit dans <AnalysisSlot>, donc il ne
              retarde plus l'affichage du reste du cockpit. Ne PAS revenir à un
              `await getTrendAnalysis(...)` dans le corps de la vue — c'est ce
              qui faisait mettre 12 s à la page pour un texte non affiché. */}
          {/* <Tile span={12} title="Lecture de la trajectoire" kick="narration · M5">
            <AnalysisSlot
              load={() => getTrendAnalysis(monthLabels, monthValuesM)}
              empty="Historique mensuel insuffisant pour une analyse de tendance."
            />
          </Tile> */}

          <Tile
            span={12}
            title="Explication d'écart budgétaire"
            kick={`${variance.annee} vs ${variance.annee_precedente}`}
            aide="Pourquoi votre chiffre d'affaires a changé depuis l'an dernier : clients gagnés, clients perdus, clients qui commandent plus ou moins. Décompose l'écart au lieu de le constater."
          >
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
                      // note: variance.note,
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
                      // note: variance.note,
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
                      // note: variance.note,
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
          <Tile
            span={7}
            title="Où se concentre le risque client"
            kick="part du CA commandé"
            aide="Le poids de chacun de vos plus gros clients. Sert à voir de qui votre activité dépend réellement."
          >
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
                    // note: "Chiffres issus des bons de commande du miroir Odoo. Le détail par dossier est accessible depuis le Copilote.",
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

          <Tile
            span={5}
            title="Paliers de concentration"
            kick="cumul du CA"
            aide="Combien de clients faut-il additionner pour atteindre la moitié, puis les trois quarts de votre chiffre. Peu de clients pour beaucoup de chiffre signale une dépendance forte."
          >
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

          {/* Les deux tuiles ci-dessus classent des COMPTES ; celle-ci descend à la
              commande. Un compte modéré peut porter une affaire unique dont la
              perte se verrait à elle seule dans l'exercice — le classement par
              client ne la montre pas. */}
          {topOrders && topOrders.length > 0 && (
            <Tile
              span={12}
              title="Les plus grosses commandes de l'exercice"
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
                    tag: `${formatMFcfa(o.montant_xof)} M`,
                    tagVariant: part > 10 ? ("r" as const) : part > 5 ? ("w" as const) : ("n" as const),
                    detail: {
                      kicker: "Commande signée",
                      title: `${o.ref} · ${o.client}`,
                      tag:
                        part > 10 ? "affaire structurante" : part > 5 ? "affaire majeure" : "affaire notable",
                      tagVariant: part > 10 ? ("r" as const) : part > 5 ? ("w" as const) : ("n" as const),
                      body: [
                        `Cette commande de ${formatMFcfa(o.montant_xof)} M FCFA représente à elle seule ${formatPct(part, 1)} % du chiffre d'affaires commandé de l'exercice${o.date ? `, signée le ${formatDate(o.date)}` : ""}.`,
                        part > 10
                          ? "Une affaire unique de ce poids fait bouger l'atterrissage à elle seule : son exécution et son encaissement sont à suivre au niveau de la direction, pas seulement du compte."
                          : "Le poids de cette affaire reste absorbable, mais elle entre dans la concentration mesurée sur les comptes ci-dessus.",
                        "Le classement porte sur les commandes signées, sur la date de commande. Une commande peut donc apparaître dans cet exercice tout en portant une référence de l'exercice précédent.",
                      ],
                      kv: [
                        ["Montant", `${formatMFcfa(o.montant_xof)} M FCFA`],
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

      {/* Miroir de l'onglet Réglages : les dix éléments « vue 360 » du débrief
          DG lisent les MÊMES agrégats (GET /v1/dashboard/pilotage ↔
          uc_briefing/facts.py blocs 10-19) — jamais deux calculs différents
          pour le même indicateur. */}
      <Section
        id="pilotage"
        title="Pilotage de l'activité"
        subtitle="La vue 360 pour décider — trajectoire, efficacité commerciale, encaissement"
      >
        {pilotage && meilleureAnnee && anneeCourante ? (
          <Bento>
            <StatTile
              span={4}
              rang="principal"
              label="CA pluriannuel"
              aide="Le CA commandé des cinq derniers exercices. Il situe l'année en cours dans la trajectoire, plutôt que de la juger seule."
              value={formatMFcfa(meilleureAnnee.ca_xof)}
              unit={`M FCFA · meilleure année ${meilleureAnnee.annee}`}
              reading={
                meilleureAnnee.annee === anneeCourante.annee
                  ? "l'exercice en cours est déjà le meilleur des cinq"
                  : partMeilleurePct !== null
                    ? `exercice en cours (incomplet) : ${formatMFcfa(anneeCourante.ca_xof)} M FCFA, soit ${formatPct(partMeilleurePct, 0)} % de la meilleure année`
                    : undefined
              }
              spark={toSpark(pilotage.ca_annuel.map((a) => a.ca_xof))}
              sparkAxis={pilotage.ca_annuel.map((a) => String(a.annee))}
            />
            <StatTile
              span={4}
              label={`Atterrissage ${pilotage.atterrissage.trimestre ?? "du trimestre"}`}
              aide="Le CA déjà commandé sur le trimestre en cours, prolongé par la tendance des six derniers mois. Une projection, pas une promesse."
              value={formatMFcfa(pilotage.atterrissage.projection_fin_trimestre?.realiste_xof ?? 0)}
              unit="M FCFA en scénario réaliste"
              reading={`déjà commandé : ${formatMFcfa(pilotage.atterrissage.realise_a_ce_jour_xof ?? 0)} M FCFA · fourchette ${formatMFcfa(pilotage.atterrissage.projection_fin_trimestre?.pessimiste_xof ?? 0)} à ${formatMFcfa(pilotage.atterrissage.projection_fin_trimestre?.optimiste_xof ?? 0)} M FCFA`}
            />
            <StatTile
              span={4}
              label="Transformation commerciale"
              aide="La part des opportunités gagnées. Le taux en valeur pèse les montants : perdre une grosse affaire y compte plus que perdre trois petites."
              value={formatPct(pilotage.transformation.win_rate?.taux_nb_pct ?? null, 0)}
              unit="% des affaires gagnées en nombre"
              reading={
                `${formatPct(pilotage.transformation.win_rate?.taux_valeur_pct ?? null, 0)} % en valeur` +
                (pilotage.transformation.pertes?.by_client?.[0]
                  ? ` · ${pilotage.transformation.pertes.by_client[0].client} concentre le plus de pertes (${formatMFcfa(pilotage.transformation.pertes.by_client[0].montant_xof)} M FCFA)`
                  : "")
              }
              readingVariant={
                (pilotage.transformation.win_rate?.taux_valeur_pct ?? 100) < 30 ? "neg" : undefined
              }
            />

            <StatTile
              span={4}
              label={`Marge ${pilotage.annee}`}
              aide="La marge des dossiers ouverts sur l'exercice : annoncée à l'ouverture (provisoire), puis constatée à l'arrêté (définitive)."
              value={formatMFcfa(pilotage.marge?.marge_provisoire_total ?? 0)}
              unit={`M FCFA provisoires · moy. ${formatPct(pilotage.marge?.perc_marge_provisoire_moyen ?? null, 1)} %`}
              reading={`définitive constatée : ${formatMFcfa(pilotage.marge?.marge_definitive_total ?? 0)} M FCFA (moy. ${formatPct(pilotage.marge?.perc_marge_definitive_moyen ?? null, 1)} %) sur ${formatNumber(pilotage.marge?.nb_dossiers ?? 0)} dossiers`}
            />
            <StatTile
              span={4}
              label="Délai d'encaissement"
              aide="Le temps réel entre l'émission d'une facture et son paiement. Chaque jour de plus est de la trésorerie immobilisée."
              value={
                encaissement?.delai_moyen_recouvrement_reel_jours !== null &&
                encaissement?.delai_moyen_recouvrement_reel_jours !== undefined
                  ? formatNumber(encaissement.delai_moyen_recouvrement_reel_jours)
                  : "—"
              }
              unit="jours en moyenne"
              reading={
                encaissement
                  ? `${formatPct(encaissement.taux_recouvrement_pct, 0)} % des factures recouvrées · ${formatMFcfa(encaissement.montant_en_attente_xof)} M FCFA en attente · retard moyen des impayés ${formatNumber(encaissement.retard_moyen_impayes_jours)} j`
                  : "aucune facture dans le miroir"
              }
              readingVariant={
                encaissement && encaissement.retard_moyen_impayes_jours > 90 ? "neg" : undefined
              }
            />
            <StatTile
              span={4}
              label="Affaires à échéance"
              aide="Les opportunités encore ouvertes dont la date de clôture tombe dans les 60 prochains jours — celles qui se décident maintenant."
              value={formatNumber(pilotage.echeances.nb)}
              unit={`sous ${pilotage.echeances.fenetre_jours} jours · ${formatMFcfa(pilotage.echeances.montant_xof)} M FCFA`}
              reading={
                prochaineEcheance
                  ? `la plus proche : ${prochaineEcheance.opportunite} (${prochaineEcheance.client}) le ${formatDate(prochaineEcheance.deadline)}`
                  : "aucune échéance dans la fenêtre"
              }
            />

            {commerciauxActifs.length > 0 && (
              <Tile
                span={6}
                title="CA par commercial"
                kick={`${pilotage.annee} · réalisé`}
                aide="La répartition du CA commandé de l'exercice entre commerciaux. Aucun objectif n'étant saisi en base, c'est une répartition du réalisé, pas un taux d'atteinte."
              >
                <Bars
                  replierApres={5}
                  nom="commerciaux"
                  rows={commerciauxActifs.map((co) => ({
                    name: co.commercial,
                    sub: `${formatNumber(co.nb_commandes)} commande(s) · ${formatPct(commerciauxTotal ? (co.ca_total_xof / commerciauxTotal) * 100 : null, 0)} % du réalisé`,
                    value: `${formatMFcfa(co.ca_total_xof)} M`,
                    pct: maxCommercial ? (co.ca_total_xof / maxCommercial) * 100 : 0,
                  }))}
                />
              </Tile>
            )}

            {pilotage.mensuel.length > 0 && (
              <Tile
                span={6}
                title="Rythme mensuel"
                kick={`${pilotage.annee} · CA commandé par mois`}
                aide="Le CA commandé mois par mois. Un essoufflement se voit ici des mois avant de se voir au bilan — le mois en cours est toujours incomplet."
              >
                <Bars
                  rows={pilotage.mensuel.map((m) => ({
                    name: MOIS_ABREV[m.mois - 1] ?? String(m.mois),
                    sub: `${formatNumber(m.nb_commandes)} commande(s)`,
                    value: `${formatMFcfa(m.ca_xof)} M`,
                    pct: maxMensuel ? (m.ca_xof / maxMensuel) * 100 : 0,
                  }))}
                />
              </Tile>
            )}

          </Bento>
        ) : (
          <Bento>
            <Tile span={12} quiet title="Pilotage de l'activité">
              <Narr>
                Les indicateurs de pilotage ne sont pas accessibles depuis ce profil, ou le backend
                ne les expose pas encore — rechargez la page après redémarrage du serveur.
              </Narr>
            </Tile>
          </Bento>
        )}
      </Section>

      {/* <Section id="copilote" title="Copilote" subtitle="Poser une question directement">
        <Bento>
          <Tile
            span={12}
            quiet
            title="Interrogation en langage naturel"
            kick="sémantique · M5"
            aide="Poser une question sur vos données en français, sans passer par un tableau ni un filtre."
          >
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
