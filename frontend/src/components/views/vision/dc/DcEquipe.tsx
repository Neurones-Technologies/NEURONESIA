import { getEquipeDc, Periode } from "@/lib/api/commercial";
import { formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, HintLine, Lst, StatTile, Tile } from "@/components/ui/bento";
import { Note } from "@/components/ui/primitives";
import { PeriodeNav } from "./periode-nav";
import { SourceNote, sourceKick } from "./source";

/** Onglet « Équipe commerciale » — §3 du compte-rendu DC.
 *
 * Deux indicateurs demandés ensemble, de faisabilité opposée :
 *
 * - l'INDICE D'EFFICACITÉ est mesurable. Ce qui manquait n'était pas la donnée
 *   mais une identité stable par commercial : le CRM ne stocke que du texte libre.
 * - l'INDICE DE PROSPECTION ne l'est pas. Il compte un FLUX d'opportunités
 *   générées, et les dates de création du miroir sont des dates d'import.
 *
 * L'indice d'efficacité expose ses trois composantes séparément, à dessein : le
 * cadrage laisse ouvertes les questions 25 à 28 (quel numérateur, faut-il pondérer
 * par le montant, faut-il neutraliser le portefeuille hérité). Trancher à la place
 * du DC produirait un classement que personne ne pourrait discuter.
 *
 * La fiabilité du référentiel est affichée AVANT le classement, et non en note de
 * bas de page : tant que les alias ne sont pas validés, le palmarès est indicatif,
 * et l'ordre de lecture doit le dire.
 */
export async function DcEquipe({ periode, annee }: { periode: Periode; annee?: number }) {
  const equipe = await getEquipeDc(annee, periode);

  if (!equipe) {
    return (
      <Bento>
        <Tile span={12} title="Équipe commerciale">
          <Note style={{ marginTop: 0 }}>
            Le suivi de performance n&apos;est pas accessible depuis ce profil.
          </Note>
        </Tile>
      </Bento>
    );
  }

  const { efficacite: eff, prospection: prosp, referentiel: ref } = equipe;
  const fi = eff.fiabilite;
  const maxCa = Math.max(...eff.commerciaux.map((c) => c.ca_signe_xof), 1);
  const maxProsp = Math.max(...prosp.lignes.map((l) => l.nb_opportunites), 1);

  return (
    <>
      <PeriodeNav basePath="/dc/vision/equipe" periode={prosp.periode} annee={eff.annee} />

      <div className="kpi-row">
        <StatTile
          span={4}
          label="Commerciaux identifiés"
          value={formatNumber(fi.nb_personnes)}
          unit={`sur ${formatNumber(fi.nb_orthographes_observees)} orthographes`}
          reading={`${formatNumber(fi.nb_alias_non_confirmes)} rattachements non encore validés`}
          readingVariant={fi.nb_alias_non_confirmes > 0 ? "wat" : "pos"}
          detail={{
            kicker: "Indicateur · fiabilité du référentiel",
            title: "Identités reconstituées à partir du texte libre",
            tag: fi.nb_alias_non_confirmes > 0 ? "à valider" : "validé",
            tagVariant: fi.nb_alias_non_confirmes > 0 ? "w" : "s",
            body: [
              `Le CRM ne stocke le commercial qu'en texte libre : ${formatNumber(fi.nb_orthographes_observees)} orthographes distinctes ont été observées, ramenées à ${formatNumber(fi.nb_personnes)} personnes et ${formatNumber(fi.nb_non_nominatifs)} porteurs non nominatifs.`,
              `${formatNumber(fi.nb_doublons_orthographe)} personne(s) apparaissaient sous plusieurs écritures — les compter séparément coupait leur portefeuille en deux.`,
              fi.avertissement,
            ],
            kv: [
              ["Orthographes observées", formatNumber(fi.nb_orthographes_observees)],
              ["Personnes", formatNumber(fi.nb_personnes)],
              ["Porteurs non nominatifs", formatNumber(fi.nb_non_nominatifs)],
              ["Doublons d'orthographe", formatNumber(fi.nb_doublons_orthographe)],
              ["Alias non confirmés", formatNumber(fi.nb_alias_non_confirmes)],
            ],
          }}
        />
        <StatTile
          span={4}
          label="CA rattaché à une personne"
          value={formatPct(fi.part_ca_nominative_pct, 0)}
          unit="% du CA de l'exercice"
          reading={`${formatNumber(fi.nb_commandes_sans_commercial)} commandes et ${formatNumber(fi.nb_opportunites_sans_commercial)} opportunités sans commercial`}
          readingVariant={fi.part_ca_nominative_pct < 70 ? "neg" : undefined}
          detail={{
            kicker: "Indicateur · couverture du classement",
            title: "Part du chiffre imputable à une personne nommée",
            tag: `${formatPct(fi.part_ca_nominative_pct, 0)} %`,
            tagVariant: fi.part_ca_nominative_pct < 70 ? "r" : "s",
            body: [
              `Seuls ${formatPct(fi.part_ca_nominative_pct, 0)} % du CA de l'exercice sont portés par un commercial nommé. Le reste est rattaché à des comptes techniques de l'ERP ou à des entités collectives.`,
              "C'est la limite la plus importante de cet écran : un classement individuel ne peut pas expliquer plus que cette fraction du chiffre. La taire donnerait l'illusion d'un palmarès exhaustif.",
              `${formatNumber(fi.nb_opportunites_sans_commercial)} opportunités et ${formatNumber(fi.nb_commandes_sans_commercial)} commandes n'ont aucun commercial renseigné.`,
            ],
            kv: [
              ["Part nominative du CA", `${formatPct(fi.part_ca_nominative_pct, 0)} %`],
              ["Opportunités sans commercial", formatNumber(fi.nb_opportunites_sans_commercial)],
              ["Commandes sans commercial", formatNumber(fi.nb_commandes_sans_commercial)],
            ],
          }}
        />
        <StatTile
          span={4}
          label="Indice de prospection"
          value={formatNumber(prosp.totaux.nb_opportunites)}
          unit={`opportunités générées · objectif ${formatNumber(prosp.objectif_annuel_nb)}`}
          reading="données statiques — flux non mesurable"
          readingVariant="wat"
          detail={{
            kicker: "Indicateur · prospection (gabarit)",
            title: "Opportunités générées sur l'exercice",
            tag: "donnée statique",
            tagVariant: "n",
            body: [
              `Le gabarit pose ${formatNumber(prosp.totaux.nb_opportunites)} opportunités générées pour un objectif de ${formatNumber(prosp.objectif_annuel_nb)}, soit ${formatPct(prosp.totaux.taux_atteinte_pct, 0)} % d'atteinte.`,
              prosp.raison,
              prosp.note,
            ],
            kv: [
              ["Opportunités générées (gabarit)", formatNumber(prosp.totaux.nb_opportunites)],
              ["Objectif annuel", formatNumber(prosp.objectif_annuel_nb)],
              ["Nouveaux comptes (gabarit)", formatNumber(prosp.totaux.nb_nouveaux_comptes)],
              ["Montant généré (gabarit)", `${formatMFcfa(prosp.totaux.montant_genere_xof)} M FCFA`],
            ],
          }}
        />
      </div>

      <Bento>
        <Tile
          span={12}
          title="Indice d'efficacité par commercial"
          kick={`${formatNumber(eff.commerciaux.length)} classés · ${eff.periodes_mesure.ca_signe}`}
        >
          <HintLine>Cliquez un commercial pour ouvrir le calcul de son indice</HintLine>
          <Bars
            rows={eff.commerciaux.map((c) => ({
              name: `#${c.rang} ${c.display_name}`,
              sub: [
                `indice ${c.indice_efficacite !== null ? formatPct(c.indice_efficacite, 0) : "—"}`,
                `${formatNumber(c.nb_gagnees)} gagnées / ${formatNumber(c.nb_perdues)} perdues`,
                c.taux_valeur_pct !== null
                  ? `transformation ${formatPct(c.taux_valeur_pct, 0)} %${c.taux_significatif ? "" : " (non significatif)"}`
                  : "aucune affaire close",
                `panier ${formatMFcfa(c.panier_moyen_xof)} M`,
              ].join(" · "),
              value: `${formatMFcfa(c.ca_signe_xof)} M`,
              pct: (c.ca_signe_xof / maxCa) * 100,
              variant: c.taux_significatif ? undefined : ("w" as const),
              detail: {
                kicker: "Commercial · indice d'efficacité",
                title: c.display_name,
                tag: c.indice_efficacite !== null ? `indice ${formatPct(c.indice_efficacite, 0)}` : "non classé",
                tagVariant: c.taux_significatif ? ("a" as const) : ("w" as const),
                body: [
                  `Indice composé de trois rangs : transformation en valeur ${c.composantes.transformation !== null ? formatPct(c.composantes.transformation, 0) : "non retenue"}, volume signé ${c.composantes.volume_signe !== null ? formatPct(c.composantes.volume_signe, 0) : "—"}, taille moyenne des affaires gagnées ${c.composantes.taille_affaire !== null ? formatPct(c.composantes.taille_affaire, 0) : "—"}.`,
                  `Sur l'historique complet : ${formatNumber(c.nb_gagnees)} affaires gagnées (${formatMFcfa(c.montant_gagne_xof)} M FCFA) contre ${formatNumber(c.nb_perdues)} perdues (${formatMFcfa(c.montant_perdu_xof)} M FCFA). Pipe ouvert porté : ${formatNumber(c.nb_ouvertes)} affaires pour ${formatMFcfa(c.pipe_ouvert_xof)} M FCFA.`,
                  c.taux_significatif
                    ? `Son taux de transformation en valeur (${formatPct(c.taux_valeur_pct, 0)} %) porte sur ${formatNumber(c.nb_closes)} affaires closes : il entre dans l'indice.`
                    : `Son taux de transformation ne porte que sur ${formatNumber(c.nb_closes)} affaires closes, sous le seuil de ${formatNumber(eff.seuil_significativite_closes)} retenu : il reste affiché mais n'entre PAS dans l'indice. Un 100 % obtenu sur trois affaires n'est pas une performance mesurée.`,
                  `Sur ${eff.annee} : ${formatMFcfa(c.ca_signe_xof)} M FCFA signés sur ${formatNumber(c.nb_commandes)} commandes, panier moyen ${formatMFcfa(c.panier_moyen_xof)} M FCFA.`,
                  "Deux périodes cohabitent sur cette ligne : la transformation porte sur l'historique complet (les opportunités n'ont pas de date fiable), le CA signé sur l'exercice affiché.",
                ],
                kv: [
                  ["Indice", c.indice_efficacite !== null ? formatPct(c.indice_efficacite, 0) : "—"],
                  ["Rang", `#${c.rang}`],
                  ["Affaires gagnées", formatNumber(c.nb_gagnees)],
                  ["Affaires perdues", formatNumber(c.nb_perdues)],
                  ["Transformation en valeur", c.taux_valeur_pct !== null ? `${formatPct(c.taux_valeur_pct, 0)} %` : "—"],
                  ["Transformation en nombre", c.taux_nb_pct !== null ? `${formatPct(c.taux_nb_pct, 0)} %` : "—"],
                  ["Ticket moyen gagné", `${formatMFcfa(c.ticket_moyen_gagne_xof)} M FCFA`],
                  ["CA signé", `${formatMFcfa(c.ca_signe_xof)} M FCFA`],
                  ["Commandes", formatNumber(c.nb_commandes)],
                  ["Pipe ouvert porté", `${formatMFcfa(c.pipe_ouvert_xof)} M FCFA`],
                ],
              },
            }))}
          />
          <Note style={{ marginTop: 14 }}>
            {eff.note} {fi.avertissement}
          </Note>
        </Tile>

        <Tile span={6} title="Limites assumées de ce classement" quiet>
          <Lst
            items={eff.limites.map((l, i) => ({
              title: `Limite ${i + 1}`,
              sub: l,
              tag: "à trancher",
              tagVariant: "n" as const,
            }))}
          />
          <Note style={{ marginTop: 14 }}>
            Transformation mesurée sur {eff.periodes_mesure.transformation}. CA signé mesuré sur{" "}
            {eff.periodes_mesure.ca_signe}.
          </Note>
        </Tile>

        {ref.doublons_orthographe.length > 0 || ref.porteurs_non_nominatifs.length > 0 ? (
          <Tile span={6} title="Référentiel à valider" kick={`${formatNumber(fi.nb_alias_non_confirmes)} alias`}>
            <Lst
              items={[
                ...ref.doublons_orthographe.map((d) => ({
                  title: d.display_name,
                  sub: `écrit de ${formatNumber(d.orthographes.length)} façons : ${d.orthographes.join(" / ")}`,
                  tag: "doublon fusionné",
                  tagVariant: "w" as const,
                  detail: {
                    kicker: "Référentiel · doublon d'orthographe",
                    title: d.display_name,
                    tag: "fusion proposée",
                    tagVariant: "w" as const,
                    body: [
                      `Ces ${formatNumber(d.orthographes.length)} écritures ont été rapprochées automatiquement : ${d.orthographes.join(" / ")}.`,
                      "Le rapprochement se fait sur la casse, les accents et les espaces uniquement — jamais sur une ressemblance phonétique, qui pourrait fusionner deux personnes différentes sans laisser de trace.",
                      "Ce rattachement est une PROPOSITION, non encore validée humainement.",
                    ],
                    kv: d.orthographes.map((o, i) => [`Écriture ${i + 1}`, o] as [string, string]),
                  },
                })),
                ...ref.porteurs_non_nominatifs.map((p) => ({
                  title: p.display_name,
                  sub: `${formatNumber(p.occurrences)} lignes · ${p.motif}`,
                  tag: p.nature === "technique" ? "compte technique" : "entité collective",
                  tagVariant: p.nature === "technique" ? ("r" as const) : ("n" as const),
                  detail: {
                    kicker: "Référentiel · porteur exclu du classement",
                    title: p.display_name,
                    tag: p.nature === "technique" ? "compte technique" : "entité collective",
                    tagVariant: p.nature === "technique" ? ("r" as const) : ("n" as const),
                    body: [
                      `Ce porteur apparaît sur ${formatNumber(p.occurrences)} lignes du miroir. Motif d'exclusion : ${p.motif}.`,
                      p.nature === "technique"
                        ? "Sa présence signale des affaires saisies sans commercial rattaché. Le volume est réel, l'attribution est à corriger dans l'ERP."
                        : "Le CA porté est réel mais n'est attribuable à aucune personne : il compte dans le total de l'équipe et jamais dans un classement individuel.",
                    ],
                    kv: [
                      ["Lignes portées", formatNumber(p.occurrences)],
                      ["Nature", p.nature],
                    ],
                  },
                })),
              ]}
            />
          </Tile>
        ) : null}

        <Tile
          span={12}
          title="Indice de prospection"
          kick={sourceKick(prosp.source, prosp.periode === "mois" ? "mensuel" : prosp.periode === "trimestre" ? "trimestriel" : "annuel")}
        >
          <HintLine>Cliquez une période pour l&apos;écart à l&apos;objectif</HintLine>
          <Bars
            rows={prosp.lignes.map((l) => ({
              name: l.libelle,
              sub: `objectif ${formatNumber(l.objectif_nb)} · ${formatNumber(l.nb_nouveaux_comptes)} nouveaux comptes · ${formatMFcfa(l.montant_genere_xof)} M FCFA générés`,
              value: formatNumber(l.nb_opportunites),
              pct: (l.nb_opportunites / maxProsp) * 100,
              variant: l.ecart_nb < 0 ? ("r" as const) : ("s" as const),
              detail: {
                kicker: "Période · prospection (gabarit)",
                title: l.libelle,
                tag: "donnée statique",
                tagVariant: "n" as const,
                body: [
                  `${formatNumber(l.nb_opportunites)} opportunités générées pour un objectif de ${formatNumber(l.objectif_nb)}, soit un écart de ${l.ecart_nb > 0 ? "+" : ""}${formatNumber(l.ecart_nb)}. Dont ${formatNumber(l.nb_nouveaux_comptes)} sur des comptes nouveaux, pour ${formatMFcfa(l.montant_genere_xof)} M FCFA.`,
                  prosp.raison,
                  "Ce qui EST mesurable aujourd'hui et remplace utilement cet écran : le nombre de comptes ayant passé leur première commande, visible dans l'onglet Comptes.",
                ],
                kv: [
                  ["Opportunités générées", formatNumber(l.nb_opportunites)],
                  ["Objectif", formatNumber(l.objectif_nb)],
                  ["Écart", formatNumber(l.ecart_nb)],
                  ["Nouveaux comptes", formatNumber(l.nb_nouveaux_comptes)],
                  ["Montant généré", `${formatMFcfa(l.montant_genere_xof)} M FCFA`],
                ],
              },
            }))}
          />
          <SourceNote source={prosp.source} raison={prosp.raison} avertissement={prosp.avertissement} />
          <Note style={{ marginTop: 14 }}>{prosp.note}</Note>
        </Tile>
      </Bento>
    </>
  );
}
