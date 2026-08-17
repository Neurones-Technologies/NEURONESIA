import {
  getPerformanceAnalysis,
  getPerformanceSummary,
  getRevenueBySalesperson,
} from "@/lib/api/dashboard";
import { formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, HintLine, Lst, StatTile, Tile } from "@/components/ui/bento";
import { AnalysisSlot } from "@/components/ui/analysis-slot";
import { DcMixOffreTuiles } from "./DcMixOffre";

/** Onglet « Diagnostic » : sur quoi on se positionne, pourquoi on perd, qui porte
 * le chiffre.
 *
 * Le bandeau d'ouverture annonce les trois blocs dans l'ordre où l'écran les
 * développe — positionnement, pertes, dépendance commerciale. La narration ferme
 * l'écran : elle commente des chiffres que les blocs ont déjà posés, et l'ouvrir
 * dessus faisait lire la conclusion avant les mesures. */
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

  // Écart entre le taux de victoire en NOMBRE et en VALEUR : le diagnostic que
  // l'écran développe ensuite. Positif, il signifie qu'on gagne les petits
  // dossiers et qu'on perd les gros.
  const win = performance?.win_rate;
  const ecartWin = win ? win.taux_nb_pct - win.taux_valeur_pct : null;
  const perteMoyenne =
    performance && performance.lost_deals.nb_total > 0
      ? performance.lost_deals.montant_total_xof / performance.lost_deals.nb_total
      : null;
  const premier = topSalespeople[0];
  const partPremier = totalCaEquipe && topSalesCa ? (topSalesCa / totalCaEquipe) * 100 : null;

  return (
    <>
      {/* Bandeau d'ouverture : un indicateur par bloc de l'écran, dans l'ordre où
          ils sont développés. L'écart de victoire est en rang principal — c'est le
          diagnostic de l'onglet, les deux autres le situent. Même structure que
          les autres onglets DC (cf. DcPipeQualite). */}
      <div className="kpi-row">
        <StatTile
          span={4}
          rang="principal"
          label="Écart de victoire nombre / valeur"
          aide="La différence entre le nombre d'affaires gagnées et l'argent qu'elles représentent. Gagner souvent mais petit, ou rarement mais gros : l'écart dit lequel des deux vous faites."
          value={ecartWin !== null ? `${ecartWin > 0 ? "+" : ""}${formatPct(ecartWin, 0)}` : "—"}
          unit="points"
          reading={
            win
              ? `${formatPct(win.taux_nb_pct, 0)} % des affaires gagnées, ${formatPct(win.taux_valeur_pct, 0)} % de la valeur`
              : "taux de victoire indisponible"
          }
          readingVariant={ecartWin !== null && ecartWin > 10 ? "neg" : undefined}
          detail={{
            kicker: "Indicateur · transformation",
            title: "Écart entre victoire en nombre et en valeur",
            tag: ecartWin !== null ? `${formatPct(ecartWin, 0)} points` : "—",
            tagVariant: ecartWin !== null && ecartWin > 10 ? "r" : "a",
            body: win
              ? [
                  `${formatNumber(win.gagnees_nb)} affaires gagnées sur ${formatNumber(win.gagnees_nb + win.perdues_nb)} closes, soit ${formatPct(win.taux_nb_pct, 0)} % en nombre. En valeur, ${formatMFcfa(win.gagnees_valeur_xof)} M FCFA gagnés contre ${formatMFcfa(win.perdues_valeur_xof)} M perdus, soit ${formatPct(win.taux_valeur_pct, 0)} %.`,
                  ecartWin !== null && ecartWin > 0
                    ? "Gagner en nombre plus qu'en valeur, c'est remporter les petits dossiers et perdre les gros. Ce n'est pas un problème de volume commercial : c'est un problème de qualification ou de prix sur les grandes opportunités."
                    : "Le taux en valeur suit le taux en nombre : la taille du dossier ne dégrade pas la transformation.",
                  "Les blocs ci-dessous développent ce diagnostic : sur quelles familles d'offre on se positionne, où se concentrent les pertes, et qui porte le chiffre.",
                ]
              : ["Le taux de victoire n'est pas disponible pour ce profil."],
            kv: win
              ? [
                  ["Taux en nombre", `${formatPct(win.taux_nb_pct, 0)} %`],
                  ["Taux en valeur", `${formatPct(win.taux_valeur_pct, 0)} %`],
                  ["Affaires gagnées", formatNumber(win.gagnees_nb)],
                  ["Affaires perdues", formatNumber(win.perdues_nb)],
                  ["Valeur gagnée", `${formatMFcfa(win.gagnees_valeur_xof)} M FCFA`],
                  ["Valeur perdue", `${formatMFcfa(win.perdues_valeur_xof)} M FCFA`],
                ]
              : [],
          }}
        />
        <StatTile
          span={4}
          label="Valeur perdue"
          aide="Le montant total des affaires que vous n'avez pas remportées. C'est le manque à gagner sur lequel travailler, pas une fatalité."
          value={performance ? formatMFcfa(performance.lost_deals.montant_total_xof) : "—"}
          unit="M FCFA"
          reading={
            performance
              ? `${formatNumber(performance.lost_deals.nb_total)} affaires${perteMoyenne !== null ? ` · ${formatMFcfa(perteMoyenne)} M en moyenne` : ""}`
              : "indisponible"
          }
          readingVariant="neg"
          detail={{
            kicker: "Indicateur · pertes",
            title: "Valeur des affaires perdues",
            tag: performance ? `${formatNumber(performance.lost_deals.nb_total)} affaires` : "—",
            tagVariant: "r",
            body: performance
              ? [
                  `${formatMFcfa(performance.lost_deals.montant_total_xof)} M FCFA perdus sur ${formatNumber(performance.lost_deals.nb_total)} opportunités closes en échec${perteMoyenne !== null ? `, soit ${formatMFcfa(perteMoyenne)} M FCFA par dossier raté` : ""}.`,
                  "Le bloc « Où se concentrent les pertes » ventile ce montant par client : une concentration sur un même compte interroge le positionnement, pas la performance individuelle.",
                  "Le motif de perte n'est exploitable que s'il a été renseigné dans Odoo — le cockpit ne le devine pas.",
                ]
              : ["Les affaires perdues ne sont pas accessibles depuis ce profil."],
            kv: performance
              ? [
                  ["Valeur perdue", `${formatMFcfa(performance.lost_deals.montant_total_xof)} M FCFA`],
                  ["Affaires perdues", formatNumber(performance.lost_deals.nb_total)],
                  ["Perte moyenne", perteMoyenne !== null ? `${formatMFcfa(perteMoyenne)} M FCFA` : "—"],
                  ["Clients concernés", formatNumber(performance.lost_deals.by_client.length)],
                ]
              : [],
          }}
        />
        <StatTile
          span={4}
          label="Premier contributeur"
          aide="Le client qui pèse le plus lourd dans votre chiffre d'affaires. Plus sa part est grosse, plus son départ ferait mal : c'est une mesure de dépendance."
          value={premier ? premier.commercial : "—"}
          unit={partPremier !== null ? `${formatPct(partPremier, 0)} % du CA équipe` : ""}
          reading={
            partPremier !== null && partPremier > 40
              ? "dépendance : plus de 40 % du chiffre sur une personne"
              : `${formatNumber(topSalespeople.length)} commerciaux rattachés`
          }
          readingVariant={partPremier !== null && partPremier > 40 ? "wat" : undefined}
          detail={{
            kicker: "Indicateur · dépendance commerciale",
            title: premier ? premier.commercial : "Premier contributeur",
            tag: partPremier !== null ? `${formatPct(partPremier, 0)} % du CA équipe` : "—",
            tagVariant: partPremier !== null && partPremier > 40 ? "w" : "a",
            body: premier
              ? [
                  `${premier.commercial} a réalisé ${formatMFcfa(topSalesCa)} M FCFA, soit ${formatPct(partPremier ?? 0, 0)} % des ${formatMFcfa(totalCaEquipe)} M FCFA de l'équipe.`,
                  partPremier !== null && partPremier > 40
                    ? "Au-delà de 40 %, la performance devient une dépendance : l'absence de cette personne déplacerait le résultat commercial."
                    : "Le poids du premier portefeuille reste dans la moyenne de l'équipe.",
                  "Le bloc « Coaching de portefeuille » détaille la répartition complète.",
                ]
              : ["Aucun commercial rattaché sur la période."],
            kv: premier
              ? [
                  ["CA réalisé", `${formatMFcfa(topSalesCa)} M FCFA`],
                  ["Part du CA équipe", partPremier !== null ? `${formatPct(partPremier, 0)} %` : "—"],
                  ["CA de l'équipe", `${formatMFcfa(totalCaEquipe)} M FCFA`],
                  ["Commerciaux", formatNumber(topSalespeople.length)],
                ]
              : [],
          }}
        />
      </div>

      <Bento>
        {/* Mix d'offre, replié ici depuis sa page dédiée (dont l'entrée de menu est
            commentée, cf. lib/data/sections.ts). Ses deux tuiles arrivent sans
            grille propre et partagent la première rangée : elles cadrent le
            positionnement avant que l'écran n'explique les pertes. */}
        <DcMixOffreTuiles />

        {performance && (
          <>
            <Tile
              span={7}
              title="Où se concentrent les pertes"
              kick={`${formatNumber(performance.lost_deals.nb_total)} affaires`}
              aide="À quel moment et pour quelle raison vous perdez le plus d'affaires. Perdre tôt coûte peu ; perdre juste avant la signature coûte tout le travail engagé."
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

            <Tile
              span={5}
              title="Plus grosses affaires perdues"
              kick="par montant"
              aide="Les échecs qui ont coûté le plus cher, un par un. Ce sont ceux dont il vaut la peine de comprendre la raison."
            >
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
          <Tile
            span={12}
            title="Coaching de portefeuille"
            kick="CA par commercial"
            aide="Le poids de chaque commercial dans le chiffre d'affaires. Sert à repérer qui aurait besoin d'appui, et si l'activité tient sur trop peu de personnes."
          >
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

        {/* La narration ferme l'écran : cf. l'en-tête du composant. */}
        <Tile
          span={12}
          title="Analyse des motifs de perte"
          kick="narration"
          aide="La lecture d'ensemble de vos échecs : ce qui revient le plus souvent et ce qu'on peut y faire."
        >
          <AnalysisSlot load={getPerformanceAnalysis} />
        </Tile>
      </Bento>
    </>
  );
}
