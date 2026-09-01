import { getObjectifs, Periode } from "@/lib/api/commercial";
import { formatFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, HintLine, Lst, Reste, StatTile, Tile } from "@/components/ui/bento";
import { Note } from "@/components/ui/primitives";
import { PeriodeNav } from "./periode-nav";
import { SourceNote, sourceKick } from "./source";
import { ChartNote, ColumnChart } from "@/components/ui/chart";
import { REPERE, SERIE_2 } from "@/components/ui/chart-palette";

/** Onglet « Objectifs et Gap » — §3 et §4 du compte-rendu DC.
 *
 * Écran à double régime, et c'est sa difficulté : le RÉALISÉ est mesuré sur les
 * commandes signées, l'OBJECTIF vient du référentiel de pilotage — et tant qu'il
 * n'y est pas saisi, d'un gabarit calculé sur l'exercice précédent. Chaque bloc
 * porte donc sa provenance, et la règle du gabarit est affichée en clair : le DC
 * doit pouvoir contester l'hypothèse, pas seulement le résultat.
 *
 * Trois pièges de lecture traités ici plutôt que laissés au lecteur :
 * - une période non commencée n'affiche pas de taux d'atteinte (un T4 à « 0 % »
 *   se lirait comme un échec) ;
 * - la période en cours affiche sa part écoulée, sans quoi l'écart se compare à
 *   un objectif plein ;
 * - la somme des objectifs individuels est inférieure à l'objectif d'équipe, et
 *   la différence est nommée : le CA porté par des entités non nominatives.
 */
export async function DcObjectifs({ periode, annee }: { periode: Periode; annee?: number }) {
  const gap = await getObjectifs(annee, periode);

  if (!gap) {
    return (
      <Bento>
        <Tile span={12} title="Objectifs et Gap">
          <Note style={{ marginTop: 0 }}>
            Le suivi des objectifs n&apos;est pas accessible depuis ce profil.
          </Note>
        </Tile>
      </Bento>
    );
  }

  const { equipe, couverture } = gap;
  const enRetard = equipe.ecart_xof < 0;
  const maxPeriode = Math.max(...gap.periodes.map((p) => Math.max(p.objectif_xof, p.realise_xof)), 1);
  const commerciauxAvecObjectif = gap.commerciaux.filter((c) => !c.objectif_absent);
  const sansObjectif = gap.commerciaux.filter((c) => c.objectif_absent);

  return (
    <>
      <PeriodeNav
        basePath="/dc/vision/objectifs"
        periode={gap.periode}
        annee={gap.annee}
        annees={gap.annees_disponibles}
      />

      <div className="kpi-row">
        <StatTile
          span={4}
          label={`Objectif ${gap.annee}`}
          aide="La cible de chiffre d'affaires de l'année. Tant qu'elle n'est pas saisie dans le référentiel, le cockpit en propose une, calculée sur l'exercice précédent."
          value={formatFcfa(equipe.objectif_annuel_xof)}
          unit="FCFA"
          reading={gap.source === "reel" ? "objectif saisi" : "gabarit · non validé"}
          readingVariant={gap.source === "reel" ? undefined : "wat"}
          detail={{
            kicker: "Indicateur · objectif d'exercice",
            title: `Objectif ${gap.annee} de l'équipe commerciale`,
            tag: gap.source === "reel" ? "saisi" : "gabarit",
            tagVariant: gap.source === "reel" ? "s" : "w",
            body: [
              `L'objectif retenu pour ${gap.annee} est de ${formatFcfa(equipe.objectif_annuel_xof)} FCFA. Origine : ${gap.origine_objectifs}.`,
              gap.regle_gabarit ??
                "Cet objectif est celui saisi dans le référentiel de pilotage : il fait foi et sert de base au calcul de l'écart.",
              `Le CA signé de l'exercice précédent s'est établi à ${formatFcfa(equipe.realise_annee_precedente_xof)} FCFA.`,
            ],
            kv: [
              ["Objectif annuel", `${formatFcfa(equipe.objectif_annuel_xof)} FCFA`],
              ["Réalisé N-1", `${formatFcfa(equipe.realise_annee_precedente_xof)} FCFA`],
              ["Origine", gap.source === "reel" ? "référentiel de pilotage" : "gabarit"],
              ["Somme des objectifs individuels", `${formatFcfa(couverture.somme_objectifs_individuels_xof)} FCFA`],
            ],
          }}
        />
        <StatTile
          span={4}
          label="Réalisé à date"
          aide="Ce qui a effectivement été signé depuis le début de l'année. Ce sont des commandes fermes, pas des affaires en cours."
          value={formatFcfa(equipe.realise_xof)}
          unit="FCFA signés"
          reading={
            equipe.part_ecoulee_annee_pct !== null
              ? `${formatPct(equipe.part_ecoulee_annee_pct, 0)} % de l'exercice écoulé`
              : "exercice complet"
          }
          detail={{
            kicker: "Indicateur · réalisé mesuré",
            title: "Chiffre d'affaires signé à date",
            tag: "mesuré",
            tagVariant: "s",
            body: [
              `${formatFcfa(equipe.realise_xof)} FCFA de commandes signées sur ${gap.annee}, dont ${formatFcfa(couverture.realise_nominatif_xof)} FCFA portés par un commercial nommé (${formatPct(couverture.part_nominative_pct, 0)} %).`,
              couverture.nb_porteurs_non_nominatifs > 0
                ? `Le reste est porté par ${formatNumber(couverture.nb_porteurs_non_nominatifs)} entité(s) non nominative(s) — un CA réel, mais imputable à aucune personne. C'est pourquoi la somme des lignes individuelles ne fait jamais le total de l'équipe.`
                : "La totalité du CA est rattachée à un commercial nommé.",
            ],
            kv: [
              ["Réalisé", `${formatFcfa(equipe.realise_xof)} FCFA`],
              ["Dont nominatif", `${formatFcfa(couverture.realise_nominatif_xof)} FCFA`],
              ["Part nominative", `${formatPct(couverture.part_nominative_pct, 0)} %`],
              ["Commerciaux suivis", formatNumber(couverture.nb_commerciaux)],
            ],
          }}
        />
        {/* Le gap donne son nom à l'écran : c'est le chiffre qu'on vient chercher.
            L'objectif et le réalisé sont ses deux termes de calcul.
            `signeNeutre` : le signe est déjà porté explicitement (« + » ou « − »)
            et la ligne de lecture qualifie l'écart — le colorer en rouge ferait
            doublon avec `readingVariant`, qui distingue avance et retard. */}
        <StatTile
          span={4}
          rang="principal"
          signeNeutre
          label="Gap vendu / objectif"
          aide="Ce qui reste à vendre pour tenir l'objectif de l'année. À rapprocher du temps qui reste : l'écart seul ne dit pas s'il est rattrapable."
          value={`${equipe.ecart_xof > 0 ? "+" : ""}${formatFcfa(equipe.ecart_xof)}`}
          unit="FCFA"
          reading={
            equipe.taux_pct !== null
              ? `${formatPct(equipe.taux_pct, 0)} % de l'objectif annuel`
              : "objectif non défini"
          }
          readingVariant={enRetard ? "neg" : "pos"}
          detail={{
            kicker: "Indicateur · écart",
            title: "Écart entre le vendu et l'objectif",
            tag: enRetard ? "en retard" : "au-dessus",
            tagVariant: enRetard ? "r" : "s",
            body: [
              `L'écart à date est de ${formatFcfa(equipe.ecart_xof)} FCFA, soit ${formatPct(equipe.taux_pct, 0)} % de l'objectif annuel atteint.`,
              equipe.part_ecoulee_annee_pct !== null
                ? `L'exercice est écoulé à ${formatPct(equipe.part_ecoulee_annee_pct, 0)} % : un objectif annuel comparé à un exercice incomplet produit mécaniquement un retard. La lecture à date comparable se fait période par période, dans le tableau ci-dessous.`
                : "L'exercice est complet : l'écart se lit sans correction.",
              gap.source !== "reel"
                ? "Cet écart dépend d'un objectif de démonstration : il mesure la forme de l'indicateur, pas la performance réelle de l'équipe."
                : "",
            ].filter(Boolean),
            kv: [
              ["Écart", `${formatFcfa(equipe.ecart_xof)} FCFA`],
              ["Taux d'atteinte", equipe.taux_pct !== null ? `${formatPct(equipe.taux_pct, 0)} %` : "—"],
              ["Part de l'exercice écoulée", equipe.part_ecoulee_annee_pct !== null ? `${formatPct(equipe.part_ecoulee_annee_pct, 0)} %` : "—"],
            ],
          }}
        />
      </div>

      <Bento>
        <Tile
          span={7}
          title="Objectif et réalisé par période"
          kick={sourceKick(gap.source, gap.periode === "mois" ? "mensuel" : gap.periode === "trimestre" ? "trimestriel" : "annuel")}
          aide="La cible et le réalisé côte à côte, période par période. Une période à venir n'affiche pas de taux d'atteinte : elle serait à zéro sans que ce soit un retard."
        >
          {/* Colonnes du réalisé, ligne de l'objectif — dans la MÊME unité, donc
              sans second axe (cf. l'avertissement de chart.tsx). Le classement en
              barres qui suit reste la vue cliquable, période par période : le
              graphe donne la trajectoire, les barres donnent le détail.
              Les périodes à venir sont atténuées : leur réalisé à zéro n'est pas
              un décrochage, c'est une période non commencée. */}
          <ColumnChart
            colonnes={gap.periodes.map((p) => ({
              x: p.libelle,
              y: p.realise_xof / 1_000_000,
              attenue: p.statut === "a_venir",
              info: `${p.libelle} · réalisé ${formatFcfa(p.realise_xof)} FCFA sur un objectif de ${formatFcfa(p.objectif_xof)} FCFA${
                p.taux_pct !== null ? ` (${formatPct(p.taux_pct, 0)} %)` : ""
              }`,
            }))}
            cumul={gap.periodes.map((p) => p.objectif_xof / 1_000_000)}
            couleurCumul={REPERE}
            libelleColonnes="Réalisé"
            libelleCumul="Objectif posé"
            couleur={SERIE_2}
            formatY={(v) => `${formatNumber(Math.round(v))} M`}
            hauteur={200}
          />
          <ChartNote>
            Les colonnes portent le réalisé mesuré, la ligne l&apos;objectif posé sur la période — même
            unité, donc pas de second axe. Les périodes à venir sont atténuées : leur réalisé nul ne se
            lit pas comme un écart.
          </ChartNote>
          <HintLine>Cliquez une période pour son écart détaillé</HintLine>
          <Bars
            rows={gap.periodes.map((p) => {
              const atteint = p.taux_pct !== null && p.taux_pct >= 100;
              return {
                name: p.libelle,
                sub: [
                  `objectif ${formatFcfa(p.objectif_xof)}`,
                  p.statut === "a_venir"
                    ? "période à venir"
                    : p.taux_pct !== null
                      ? `${formatPct(p.taux_pct, 0)} % atteint`
                      : "objectif non défini",
                  p.part_ecoulee_pct !== null ? `${formatPct(p.part_ecoulee_pct, 0)} % écoulé` : null,
                ]
                  .filter(Boolean)
                  .join(" · "),
                value: `${formatFcfa(p.realise_xof)}`,
                pct: (p.realise_xof / maxPeriode) * 100,
                variant: p.statut === "a_venir" ? undefined : atteint ? ("s" as const) : ("r" as const),
                detail: {
                  kicker:
                    p.statut === "en_cours"
                      ? "Période en cours"
                      : p.statut === "a_venir"
                        ? "Période à venir"
                        : "Période révolue",
                  title: p.libelle,
                  tag:
                    p.statut === "a_venir"
                      ? "pas encore commencée"
                      : p.taux_pct !== null
                        ? `${formatPct(p.taux_pct, 0)} % de l'objectif`
                        : "objectif non défini",
                  tagVariant: p.statut === "a_venir" ? "n" : atteint ? "s" : "r",
                  body: [
                    `Objectif de la période : ${formatFcfa(p.objectif_xof)} FCFA. Réalisé : ${formatFcfa(p.realise_xof)} FCFA sur ${formatNumber(p.nb_commandes)} commande(s), soit un écart de ${formatFcfa(p.ecart_xof)} FCFA.`,
                    p.statut === "a_venir"
                      ? "Aucun taux d'atteinte n'est publié sur une période non commencée : il afficherait 0 % et se lirait comme un échec."
                      : p.part_ecoulee_pct !== null
                        ? `Cette période est écoulée à ${formatPct(p.part_ecoulee_pct, 0)} % : l'écart doit se lire à date comparable, pas contre un objectif plein.`
                        : "Cette période est révolue : l'écart est définitif.",
                    gap.periode !== "annee"
                      ? "La répartition de l'objectif entre les périodes suit une saisonnalité et non un découpage égal — un début d'exercice structurellement creux ne doit pas se lire comme un décrochage."
                      : "",
                  ].filter(Boolean),
                  kv: [
                    ["Objectif", `${formatFcfa(p.objectif_xof)} FCFA`],
                    ["Réalisé", `${formatFcfa(p.realise_xof)} FCFA`],
                    ["Écart", `${formatFcfa(p.ecart_xof)} FCFA`],
                    ["Commandes", formatNumber(p.nb_commandes)],
                    ["Statut", p.statut === "en_cours" ? "en cours" : p.statut === "a_venir" ? "à venir" : "révolue"],
                  ],
                },
              };
            })}
          />
          <SourceNote source={gap.source} raison={gap.regle_gabarit} avertissement={gap.avertissement} />
        </Tile>

        <Tile
          span={5}
          title="Gap par commercial"
          kick={`${formatNumber(commerciauxAvecObjectif.length)} avec objectif`}
          aide="Ce qui reste à faire pour chaque commercial ayant une cible. Sert à voir où l'appui manque, pas à établir un palmarès."
        >
          {commerciauxAvecObjectif.length > 0 ? (
            <>
              <HintLine>Cliquez un commercial pour son écart</HintLine>
              <Lst
                items={commerciauxAvecObjectif.slice(0, 8).map((c) => {
                  const atteint = (c.taux_pct ?? 0) >= 100;
                  return {
                    title: c.display_name,
                    sub: `objectif ${formatFcfa(c.objectif_xof)} · réalisé ${formatFcfa(c.realise_xof)} · ${formatNumber(c.nb_commandes)} commandes`,
                    tag: c.taux_pct !== null ? `${formatPct(c.taux_pct, 0)} %` : "—",
                    tagVariant: atteint ? ("s" as const) : ("r" as const),
                    detail: {
                      kicker: "Commercial · écart à l'objectif",
                      title: c.display_name,
                      tag: c.taux_pct !== null ? `${formatPct(c.taux_pct, 0)} % de son objectif` : "objectif non défini",
                      tagVariant: atteint ? ("s" as const) : ("r" as const),
                      body: [
                        `${c.display_name} a signé ${formatFcfa(c.realise_xof)} FCFA sur ${formatNumber(c.nb_commandes)} commande(s) en ${gap.annee}, pour un objectif de ${formatFcfa(c.objectif_xof)} FCFA — un écart de ${formatFcfa(c.ecart_xof)} FCFA.`,
                        `Son portefeuille représente ${formatPct(c.part_ca_equipe_pct, 0)} % du CA de l'équipe sur l'exercice.`,
                        gap.source !== "reel"
                          ? "Son objectif est issu du gabarit (prorata de son réalisé de l'exercice précédent) : il n'a pas été négocié avec lui."
                          : "",
                      ].filter(Boolean),
                      kv: [
                        ["Objectif", `${formatFcfa(c.objectif_xof)} FCFA`],
                        ["Réalisé", `${formatFcfa(c.realise_xof)} FCFA`],
                        ["Écart", `${formatFcfa(c.ecart_xof)} FCFA`],
                        ["Part du CA équipe", `${formatPct(c.part_ca_equipe_pct, 0)} %`],
                        ["Commandes", formatNumber(c.nb_commandes)],
                      ],
                    },
                  };
                })}
              />
              <Reste
                affiches={Math.min(8, commerciauxAvecObjectif.length)}
                total={commerciauxAvecObjectif.length}
                nom="commerciaux"
              />
            </>
          ) : (
            <Note style={{ marginTop: 0 }}>
              Aucun commercial ne porte d&apos;objectif calculable sur cet exercice.
            </Note>
          )}
        </Tile>

        {sansObjectif.length > 0 && (
          <Tile
            span={6}
            title="Commerciaux sans objectif calculable"
            kick={`${formatNumber(sansObjectif.length)} à saisir`}
            aide="Les commerciaux pour lesquels aucune cible n'a été fixée. Leur activité compte dans le total de l'équipe, mais ne peut pas être comparée à un objectif."
          >
            <Lst
              items={sansObjectif.slice(0, 6).map((c) => ({
                title: c.display_name,
                sub: `${formatFcfa(c.realise_xof)} FCFA signés · ${formatNumber(c.nb_commandes)} commandes`,
                tag: "objectif à saisir",
                tagVariant: "w" as const,
                detail: {
                  kicker: "Commercial · objectif manquant",
                  title: c.display_name,
                  tag: "objectif à saisir",
                  tagVariant: "w" as const,
                  body: [
                    `${c.display_name} a signé ${formatFcfa(c.realise_xof)} FCFA en ${gap.annee}, mais aucun objectif ne lui est attribué.`,
                    c.motif_objectif_absent ??
                      "La règle du gabarit ne permet pas de lui en calculer un : il doit être saisi.",
                    "Lui affecter un objectif de zéro aurait produit un taux d'atteinte sans signification — c'est pourquoi il apparaît ici et non dans le classement.",
                  ],
                  kv: [
                    ["Réalisé", `${formatFcfa(c.realise_xof)} FCFA`],
                    ["Commandes", formatNumber(c.nb_commandes)],
                    ["Part du CA équipe", `${formatPct(c.part_ca_equipe_pct, 0)} %`],
                  ],
                },
              }))}
            />
            <Note style={{ marginTop: 14 }}>
              Ces commerciaux vendent sur l&apos;exercice sans avoir de réalisé sur le précédent : la règle
              du gabarit ne peut pas leur attribuer d&apos;objectif. C&apos;est précisément le cas qui impose
              une saisie manuelle des objectifs.
            </Note>
          </Tile>
        )}

        {gap.porteurs_non_nominatifs.length > 0 && (
          <Tile
            span={6}
            title="CA non imputable à une personne"
            kick={`${formatPct(100 - couverture.part_nominative_pct, 0)} % du CA`}
            aide="La part du chiffre d'affaires qu'on ne peut rattacher à personne, faute de commercial renseigné. Elle limite d'autant la lecture par commercial ci-dessus."
          >
            <Bars
              rows={gap.porteurs_non_nominatifs.map((p) => ({
                name: p.display_name,
                sub: `${p.nature === "technique" ? "compte technique de l'ERP" : "entité collective"} · ${formatNumber(p.nb_commandes)} commandes`,
                value: `${formatFcfa(p.realise_xof)}`,
                pct: p.part_ca_equipe_pct,
                variant: p.nature === "technique" ? ("r" as const) : ("w" as const),
                detail: {
                  kicker: "Porteur non nominatif",
                  title: p.display_name,
                  tag: `${formatPct(p.part_ca_equipe_pct, 0)} % du CA équipe`,
                  tagVariant: p.nature === "technique" ? ("r" as const) : ("w" as const),
                  body: [
                    `${p.display_name} porte ${formatFcfa(p.realise_xof)} FCFA sur ${formatNumber(p.nb_commandes)} commande(s), soit ${formatPct(p.part_ca_equipe_pct, 0)} % du CA de l'exercice.`,
                    p.nature === "technique"
                      ? "C'est un compte technique de l'ERP, pas un vendeur : sa présence signale des commandes saisies sans commercial rattaché. Le CA est réel, l'attribution est à corriger dans Odoo."
                      : "C'est une entité collective : le CA existe bel et bien, mais il n'est attribuable à aucune personne. L'exclure du classement individuel est correct ; l'exclure du total de l'équipe ne le serait pas.",
                  ],
                  kv: [
                    ["CA porté", `${formatFcfa(p.realise_xof)} FCFA`],
                    ["Part du CA équipe", `${formatPct(p.part_ca_equipe_pct, 0)} %`],
                    ["Commandes", formatNumber(p.nb_commandes)],
                    ["Nature", p.nature === "technique" ? "compte technique" : "entité collective"],
                  ],
                },
              }))}
            />
            <Note style={{ marginTop: 14 }}>
              Ce CA est mesuré et compté dans le total de l&apos;équipe, mais il ne peut entrer dans aucun
              classement individuel. C&apos;est la raison pour laquelle la somme des objectifs individuels
              ({formatFcfa(couverture.somme_objectifs_individuels_xof)} FCFA) reste inférieure à
              l&apos;objectif d&apos;équipe ({formatFcfa(equipe.objectif_annuel_xof)} FCFA).
            </Note>
          </Tile>
        )}

      </Bento>
    </>
  );
}
