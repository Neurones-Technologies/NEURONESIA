import {
  getBudgetVariance,
  getForecastPipelineWeighted,
  getKpis,
  getMonthlyClients,
} from "@/lib/api/dashboard";
import { formatFcfa, formatNumber, formatPct, signedFcfa } from "@/lib/format";
import { Bars, Bento, HintLine, Tile } from "@/components/ui/bento";
import { Clickable } from "@/components/ui/detail";
import { Narr, Section } from "@/components/ui/primitives";
import { ScenPanel } from "@/components/ui/scen-panel";
import { MOIS_ABREV } from "./commun";

/** Trajectoire financière du DG : scénarios d'atterrissage, rythme des
 * commandes et explication d'écart budgétaire. */
export async function DgTrajectoire() {
  const year = new Date().getFullYear();
  const [kpis, forecast, variance, monthlyClients] = await Promise.all([
    getKpis(year),
    getForecastPipelineWeighted(),
    getBudgetVariance(year),
    getMonthlyClients(year, 10),
  ]);

  const monthLabels = kpis.monthly.map((m) => MOIS_ABREV[m.mois - 1] ?? String(m.mois));
  const monthValuesM = kpis.monthly.map((m) => m.ca_xof / 1_000_000);
  const maxMonth = Math.max(...monthValuesM, 0);

  // Détail des scénarios : recalculé côté vue pour donner un "pourquoi" chiffré
  // au clic, à partir des mêmes opportunités que le backend
  // (uc_forecast/aggregation.py) — jamais une approximation inventée dans la vue.
  const oppsAtRisque = forecast.opportunities.filter((o) => o.probability_pct < 50);
  const nbAtRisque = oppsAtRisque.length;
  const pondereAtRisque = oppsAtRisque.reduce((sum, o) => sum + o.weighted_xof, 0);
  const bonusHaut = forecast.scenarios.optimiste_xof - forecast.scenarios.realiste_xof;

  return (
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
                value: formatFcfa(forecast.scenarios.pessimiste_xof),
                detail: <>FCFA · hors opportunités à risque</>,
                narrative: {
                  kicker: "Méthode de calcul · scénario bas",
                  title: "Scénario bas",
                  tag: "plancher",
                  tagVariant: "w",
                  body: [
                    `Ce scénario ne retient que les opportunités dont la probabilité de conversion Odoo est d'au moins 50 %, pondérées par cette probabilité. Les ${formatNumber(nbAtRisque)} opportunités sous ce seuil (${formatFcfa(pondereAtRisque)} FCFA pondérés dans le scénario réaliste) en sont entièrement exclues, pas seulement décotées.`,
                    "C'est un plancher volontairement pessimiste : si aucune opportunité incertaine n'aboutit, c'est le chiffre qu'on peut sécuriser sans hypothèse supplémentaire.",
                  ],
                  kv: [
                    ["Opportunités retenues (≥ 50 %)", formatNumber(forecast.scenarios.nb_opportunites - nbAtRisque)],
                    ["Opportunités exclues (< 50 %)", formatNumber(nbAtRisque)],
                    ["Écart avec le réaliste", `-${formatFcfa(forecast.scenarios.realiste_xof - forecast.scenarios.pessimiste_xof)} FCFA`],
                  ],
                },
              },
              {
                mid: true,
                label: "Réaliste · retenu",
                value: formatFcfa(forecast.scenarios.realiste_xof),
                detail: <>FCFA · probabilité moyenne {formatPct(forecast.scenarios.avg_probability_pct, 0)} %</>,
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
                    ["Pipeline brut (non pondéré)", `${formatFcfa(forecast.scenarios.total_pipeline_xof)} FCFA`],
                    ["Pipeline pondéré retenu", `${formatFcfa(forecast.scenarios.realiste_xof)} FCFA`],
                    ["Taux de pondération global", forecast.scenarios.total_pipeline_xof ? `${formatPct((forecast.scenarios.realiste_xof / forecast.scenarios.total_pipeline_xof) * 100, 0)} %` : "—"],
                  ],
                },
              },
              {
                label: "Scénario haut",
                value: formatFcfa(forecast.scenarios.optimiste_xof),
                detail: <>FCFA · {formatNumber(forecast.scenarios.nb_opportunites)} opportunités</>,
                narrative: {
                  kicker: "Méthode de calcul · scénario haut",
                  title: "Scénario haut",
                  tag: "hypothèse optimiste",
                  tagVariant: "n",
                  body: [
                    `Part du même socle que le scénario réaliste (${formatFcfa(forecast.scenarios.realiste_xof)} FCFA), puis ajoute un bonus sur les ${formatNumber(nbAtRisque)} opportunités sous 50 % de probabilité : chacune est recomptée à 50 % de sa valeur au lieu de sa probabilité réelle, souvent plus faible.`,
                    "Ce n'est pas une probabilité mesurée qui remonte à 50 % — c'est une hypothèse forfaitaire volontairement optimiste sur les dossiers incertains, à ne pas annoncer comme un chiffre plus fiable que le réaliste.",
                  ],
                  kv: [
                    ["Socle réaliste", `${formatFcfa(forecast.scenarios.realiste_xof)} FCFA`],
                    ["Bonus opportunités < 50 %", `+${formatFcfa(bonusHaut)} FCFA`],
                    ["Opportunités concernées", formatNumber(nbAtRisque)],
                  ],
                },
              },
            ]}
          />
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
                sub: `${formatNumber(m.nb_commandes)} commande${m.nb_commandes > 1 ? "s" : ""} · ${formatFcfa(m.ca_xof)} FCFA commandés`,
                value: `${formatFcfa(m.ca_xof)}`,
                pct: maxMonth ? (m.ca_xof / 1_000_000 / maxMonth) * 100 : 0,
                detail: {
                  kicker: `Commandes · ${monthLabels[i]} ${year}`,
                  title: `${monthLabels[i]} ${year}`,
                  tag: `${formatFcfa(m.ca_xof)} FCFA`,
                  tagVariant: "a" as const,
                  body: [
                    `Le mois de ${monthLabels[i].toLowerCase()} totalise ${formatFcfa(m.ca_xof)} FCFA de commandes confirmées, soit ${maxMonth ? formatPct((m.ca_xof / 1_000_000 / maxMonth) * 100, 0) : "0"} % du meilleur mois de l'exercice.`,
                  ],
                  kv: clients.length
                    ? clients.map((c) => [c.client, `${formatFcfa(c.ca_xof)} FCFA`] as const)
                    : [["Aucune commande", "—"] as const],
                },
              };
            })}
          />
        </Tile>

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
                  <th className="r">FCFA</th>
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
                      `${formatNumber(variance.nb_clients_retenus)} clients ont commandé sur les deux exercices. Leur contribution nette à l'écart est de ${signedFcfa(variance.effet_clients_retenus_xof)} FCFA.`,
                      "C'est l'effet le plus actionnable des trois : ces comptes existent déjà et la relation est ouverte, contrairement aux clients perdus qu'il faut reconquérir.",
                    ],
                    kv: [
                      ["Effet net", `${signedFcfa(variance.effet_clients_retenus_xof)} FCFA`],
                      ["Clients concernés", formatNumber(variance.nb_clients_retenus)],
                    ],
                  }}
                >
                  <td>Clients retenus</td>
                  <td className={`r mono ${variance.effet_clients_retenus_xof >= 0 ? "up" : "dn"}`}>
                    {signedFcfa(variance.effet_clients_retenus_xof)}
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
                      `${formatNumber(variance.nb_clients_gagnes)} clients ont commandé pour la première fois en ${variance.annee}, apportant ${formatFcfa(variance.effet_clients_gagnes_xof)} FCFA.`,
                      variance.top_clients_gagnes[0]
                        ? `Le plus important est ${variance.top_clients_gagnes[0].client}, pour ${formatFcfa(variance.top_clients_gagnes[0].ca_xof)} FCFA.`
                        : "Aucun nouveau client identifié sur l'exercice.",
                    ],
                    kv: [
                      ["Apport", `+${formatFcfa(variance.effet_clients_gagnes_xof)} FCFA`],
                      ["Clients gagnés", formatNumber(variance.nb_clients_gagnes)],
                      ...variance.top_clients_gagnes.slice(0, 3).map(
                        (c) => [c.client, `${formatFcfa(c.ca_xof)} FCFA`] as [string, string]
                      ),
                    ],
                  }}
                >
                  <td>Clients gagnés</td>
                  <td className="r mono up">+{formatFcfa(variance.effet_clients_gagnes_xof)}</td>
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
                      `${formatNumber(variance.nb_clients_perdus)} clients actifs en ${variance.annee_precedente} n'ont plus commandé en ${variance.annee}, soit ${signedFcfa(variance.effet_clients_perdus_xof)} FCFA de manque.`,
                      variance.top_clients_perdus[0]
                        ? `Le premier d'entre eux, ${variance.top_clients_perdus[0].client}, pesait ${formatFcfa(variance.top_clients_perdus[0].ca_xof)} FCFA. Un silence de cette taille sur un compte déjà servi mérite un appel avant d'être traité comme une perte définitive.`
                        : "Aucun client perdu identifié sur l'exercice.",
                    ],
                    kv: [
                      ["Manque", `${signedFcfa(variance.effet_clients_perdus_xof)} FCFA`],
                      ["Clients perdus", formatNumber(variance.nb_clients_perdus)],
                      ...variance.top_clients_perdus.slice(0, 3).map(
                        (c) => [c.client, `${formatFcfa(c.ca_xof)} FCFA`] as [string, string]
                      ),
                    ],
                  }}
                >
                  <td>Clients perdus</td>
                  <td className="r mono dn">{signedFcfa(variance.effet_clients_perdus_xof)}</td>
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
                {signedFcfa(variance.ecart_total_xof)} FCFA
              </b>
              . Premier client perdu : {variance.top_clients_perdus[0]?.client ?? "—"} (
              {formatFcfa(variance.top_clients_perdus[0]?.ca_xof)}). Premier client gagné :{" "}
              {variance.top_clients_gagnes[0]?.client ?? "—"} (
              {formatFcfa(variance.top_clients_gagnes[0]?.ca_xof)}).
            </p>
          </Narr>
        </Tile>
      </Bento>
    </Section>
  );
}
