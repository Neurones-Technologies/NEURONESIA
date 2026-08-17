import { getQualitePipe } from "@/lib/api/commercial";
import { formatDate, formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, HintLine, Lst, StatTile, Tile } from "@/components/ui/bento";
import { Note } from "@/components/ui/primitives";
import { ScreenNotes } from "@/components/ui/screen-notes";

/** Onglet « À closer et à compléter » — §4 du compte-rendu DC.
 *
 * « Distinction entre les opportunités à closer (finalisation en cours) et les
 * opportunités à compléter (informations manquantes ou dossier incomplet). »
 *
 * Ni l'une ni l'autre n'existe dans Odoo : ce sont deux RÈGLES, affichées ici en
 * même temps que leurs résultats. Un indicateur dont la règle est cachée ne se
 * discute pas, il se subit — et le DC finit par ne plus l'ouvrir.
 *
 * L'écran en montre un TROISIÈME panier, qui n'était pas demandé mais que les
 * données imposent : les affaires à requalifier. Mesuré sur ce pipe, la quasi-
 * totalité des opportunités ouvertes portent une échéance dépassée. Les compter
 * comme « incomplètes » aurait produit un indicateur signalant 98 % du pipe, donc
 * aucune liste de travail. Compléter un dossier et reprendre une date qui n'a pas
 * été tenue sont deux gestes différents.
 */
export async function DcPipeQualite() {
  const qualite = await getQualitePipe(12);

  if (!qualite) {
    return (
      <Bento>
        <Tile span={12} title="À closer et à compléter">
          <Note style={{ marginTop: 0 }}>Le pipeline n&apos;est pas accessible depuis ce profil.</Note>
        </Tile>
      </Bento>
    );
  }

  const t = qualite.totaux;
  const maxDefaut = Math.max(...qualite.defauts.map((d) => d.nb_opportunites), 1);

  return (
    <>
      {/* Titre conservé : sur cet écran la note n'énonce pas des hypothèses de
          mesure mais la règle de tri des trois piles — c'est elle qui explique
          pourquoi une opportunité tombe dans « à closer » plutôt qu'ailleurs. */}
      {/* <ScreenNotes titre="Règle appliquée" notes={[qualite.note]} /> */}

      <div className="kpi-row">
        {/* « À closer » est la seule des trois piles qui porte une action datée :
            les deux autres sont de la mise en ordre du pipe. */}
        <StatTile
          span={4}
          rang="principal"
          label="À closer"
          aide="Les affaires proches de la signature, dont le dossier est complet. C'est là que l'effort commercial rapporte le plus vite."
          value={formatNumber(t.nb_a_closer)}
          unit="opportunités"
          reading={`${formatMFcfa(t.montant_a_closer_xof)} M FCFA en jeu${t.nb_prioritaires > 0 ? ` · ${formatNumber(t.nb_prioritaires)} avec dossier incomplet` : ""}`}
          readingVariant={t.nb_prioritaires > 0 ? "neg" : "pos"}
          detail={{
            kicker: "Indicateur · finalisation en cours",
            title: "Opportunités en phase de closing",
            tag: `${formatNumber(t.nb_a_closer)} affaires`,
            tagVariant: "a",
            body: [
              `${formatNumber(t.nb_a_closer)} opportunités sont en étape de finalisation ou à moins de ${qualite.regle.horizon_closer_jours} jours de leur échéance, pour ${formatMFcfa(t.montant_a_closer_xof)} M FCFA.`,
              `Les deux critères sont acceptés volontairement : sur ce pipe, l'étape est souvent moins à jour que la date. Étapes reconnues comme finales : ${qualite.regle.motifs_etape_closer.join(", ")}.`,
              t.nb_prioritaires > 0
                ? `${formatNumber(t.nb_prioritaires)} de ces affaires arrivent à la signature avec un dossier incomplet. C'est le cas le plus urgent de l'écran : le montant est acquis à court terme, l'information manque.`
                : "Aucune de ces affaires ne présente de défaut de dossier.",
            ],
            kv: [
              ["Opportunités à closer", formatNumber(t.nb_a_closer)],
              ["Montant en jeu", `${formatMFcfa(t.montant_a_closer_xof)} M FCFA`],
              ["Dont dossier incomplet", formatNumber(t.nb_prioritaires)],
              ["Horizon retenu", `${qualite.regle.horizon_closer_jours} jours`],
            ],
          }}
        />
        <StatTile
          span={4}
          label="À compléter"
          aide="Les affaires auxquelles il manque une information pour avancer : montant, échéance, interlocuteur. Le travail à faire est de saisie, pas de négociation."
          value={formatNumber(t.nb_a_completer)}
          unit="opportunités"
          reading={`${formatPct(t.part_a_completer_pct, 0)} % du pipe ouvert · ${formatMFcfa(t.montant_a_completer_xof)} M FCFA`}
          readingVariant="wat"
          detail={{
            kicker: "Indicateur · complétude du dossier",
            title: "Opportunités dont l'information manque",
            tag: `${formatPct(t.part_montant_a_completer_pct, 0)} % du montant ouvert`,
            tagVariant: "w",
            body: [
              `${formatNumber(t.nb_a_completer)} opportunités ouvertes sur ${formatNumber(t.nb_ouvertes)} présentent au moins un champ manquant parmi les quatre qui les rendent pilotables, pour ${formatMFcfa(t.montant_a_completer_xof)} M FCFA.`,
              "Aucune règle de complétude n'existe aujourd'hui dans l'équipe : celle appliquée ici est une proposition, et elle est affichée pour être discutée plutôt qu'imposée.",
              `${formatNumber(t.nb_sans_commercial)} opportunités n'ont aucun commercial rattaché. Ce défaut est compté à part : il se corrige dans le référentiel, pas dans le dossier.`,
            ],
            kv: [
              ["À compléter", formatNumber(t.nb_a_completer)],
              ["Part du pipe ouvert", `${formatPct(t.part_a_completer_pct, 0)} %`],
              ["Montant concerné", `${formatMFcfa(t.montant_a_completer_xof)} M FCFA`],
              ["Sans commercial", formatNumber(t.nb_sans_commercial)],
            ],
          }}
        />
        <StatTile
          span={4}
          label="À requalifier"
          aide="Les affaires dont la date de conclusion annoncée est passée sans rien. Tant qu'elles ne sont pas revues, elles gonflent la prévision sans raison."
          value={formatNumber(t.nb_a_requalifier)}
          unit="échéances dépassées"
          reading={`${formatPct(t.part_montant_a_requalifier_pct, 0)} % du montant ouvert encore compté dans le forecast`}
          readingVariant="neg"
          detail={{
            kicker: "Indicateur · fiabilité des dates",
            title: "Opportunités dont l'échéance est passée",
            tag: `${formatMFcfa(t.montant_a_requalifier_xof)} M FCFA`,
            tagVariant: "r",
            body: [
              `${formatNumber(t.nb_a_requalifier)} opportunités ouvertes portent une date de clôture déjà passée, pour ${formatMFcfa(t.montant_a_requalifier_xof)} M FCFA — soit ${formatPct(t.part_montant_a_requalifier_pct, 0)} % du montant ouvert.`,
              "Une date dépassée n'est pas une affaire perdue : c'est une affaire dont la date n'a pas été tenue à jour. Tant qu'elle n'est pas requalifiée, elle gonfle le forecast du trimestre en cours.",
              "Ce panier est séparé de la complétude à dessein : les fusionner produirait un indicateur qui signale la quasi-totalité du pipe, donc une liste de travail inutilisable.",
            ],
            kv: [
              ["À requalifier", formatNumber(t.nb_a_requalifier)],
              ["Montant concerné", `${formatMFcfa(t.montant_a_requalifier_xof)} M FCFA`],
              ["Part du montant ouvert", `${formatPct(t.part_montant_a_requalifier_pct, 0)} %`],
              ["Pipe ouvert total", `${formatMFcfa(t.montant_ouvert_xof)} M FCFA`],
            ],
          }}
        />
      </div>

      <Bento>
        <Tile
          span={7}
          title="Opportunités à closer"
          kick={`${formatNumber(qualite.a_closer.length)} affichées`}
          aide="La liste des affaires mûres pour être conclues, les plus grosses d'abord. C'est la file de travail de la semaine."
        >
          {qualite.a_closer.length > 0 ? (
            <>
              <HintLine>Cliquez une affaire pour son état de dossier</HintLine>
              <Lst
                items={qualite.a_closer.map((o) => ({
                  title: o.name,
                  sub: `${o.client} · ${o.stage} · ${o.commercial || "commercial non renseigné"} · ${o.motif_closer}`,
                  tag: o.prioritaire ? "dossier incomplet" : `${formatMFcfa(o.montant_xof)} M`,
                  tagVariant: o.prioritaire ? ("r" as const) : ("a" as const),
                  detail: {
                    kicker: `Opportunité · ${o.motif_closer}`,
                    title: o.name,
                    tag: o.prioritaire ? "à compléter avant signature" : "en finalisation",
                    tagVariant: o.prioritaire ? ("r" as const) : ("a" as const),
                    body: [
                      `${o.client} · ${o.stage} · ${formatMFcfa(o.montant_xof)} M FCFA à ${formatPct(o.probabilite_pct, 0)} % de probabilité déclarée. Échéance le ${formatDate(o.deadline)}${o.jours_avant_echeance !== null ? `, dans ${formatNumber(o.jours_avant_echeance)} jour(s)` : ""}.`,
                      o.prioritaire
                        ? `Le dossier arrive à la signature avec des informations manquantes : ${o.defauts_libelles.join(", ")}.`
                        : "Le dossier est complet au regard des quatre champs suivis.",
                      "Retenue ici parce que " +
                        (o.motif_closer === "étape de finalisation"
                          ? "son étape signale une finalisation en cours."
                          : `son échéance tombe dans les ${qualite.regle.horizon_closer_jours} prochains jours.`),
                    ],
                    kv: [
                      ["Client", o.client],
                      ["Commercial", o.commercial || "non renseigné"],
                      ["Étape", o.stage],
                      ["Montant", `${formatMFcfa(o.montant_xof)} M FCFA`],
                      ["Probabilité déclarée", `${formatPct(o.probabilite_pct, 0)} %`],
                      ["Échéance", formatDate(o.deadline)],
                      ["Défauts", o.defauts_libelles.join(", ") || "aucun"],
                    ],
                  },
                }))}
              />
            </>
          ) : (
            <Note style={{ marginTop: 0 }}>
              Aucune affaire ouverte n&apos;est en étape de finalisation ni à moins de{" "}
              {qualite.regle.horizon_closer_jours} jours d&apos;échéance.
            </Note>
          )}
        </Tile>

        <Tile
          span={5}
          title="Nature des informations manquantes"
          kick="sur le pipe ouvert"
          aide="Ce qui manque le plus souvent dans les dossiers. Si un même champ revient partout, c'est une habitude de saisie à corriger, pas un oubli isolé."
        >
          <HintLine>Cliquez un défaut pour son poids</HintLine>
          <Bars
            rows={qualite.defauts.map((d) => ({
              name: d.libelle,
              sub: `${formatPct(d.part_pct, 1)} % du pipe ouvert · poids ${d.poids}`,
              value: formatNumber(d.nb_opportunites),
              pct: (d.nb_opportunites / maxDefaut) * 100,
              variant: d.poids >= 3 ? ("r" as const) : d.poids === 2 ? ("w" as const) : undefined,
              detail: {
                kicker: "Défaut de complétude",
                title: d.libelle,
                tag: `${formatNumber(d.nb_opportunites)} opportunités`,
                tagVariant: d.poids >= 3 ? ("r" as const) : ("w" as const),
                body: [
                  `${formatNumber(d.nb_opportunites)} opportunités ouvertes présentent ce défaut, soit ${formatPct(d.part_pct, 1)} % du pipe ouvert.`,
                  `Son poids dans le classement de gravité est de ${d.poids} sur ${Math.max(...qualite.defauts.map((x) => x.poids))}. Les poids sont fixés par CONSÉQUENCE : ce qui fausse directement le chiffre annoncé compte plus que ce qui gêne une ventilation.`,
                ],
                kv: [
                  ["Opportunités", formatNumber(d.nb_opportunites)],
                  ["Part du pipe ouvert", `${formatPct(d.part_pct, 1)} %`],
                  ["Poids de gravité", String(d.poids)],
                ],
              },
            }))}
          />
        </Tile>

        <Tile
          span={7}
          title="Dossiers les plus incomplets"
          kick="par gravité puis montant"
          aide="Les affaires où il manque le plus d'informations, en commençant par les plus grosses. Compléter celles-là fiabilise la prévision plus que toutes les autres."
        >
          {qualite.a_completer.length > 0 ? (
            <Lst
              items={qualite.a_completer.map((o) => ({
                title: o.name,
                sub: `${o.client} · ${o.stage} · ${o.defauts_libelles.join(", ")}`,
                tag: `${formatMFcfa(o.montant_xof)} M`,
                tagVariant: o.gravite >= 5 ? ("r" as const) : ("w" as const),
                detail: {
                  kicker: "Opportunité · dossier incomplet",
                  title: o.name,
                  tag: `gravité ${o.gravite}`,
                  tagVariant: o.gravite >= 5 ? ("r" as const) : ("w" as const),
                  body: [
                    `${o.client} · ${o.stage} · ${formatMFcfa(o.montant_xof)} M FCFA. Informations manquantes : ${o.defauts_libelles.join(", ")}.`,
                    "La gravité additionne les poids des défauts constatés : elle sert à trier la liste de travail, pas à juger le commercial.",
                    o.commercial ? `Affaire portée par ${o.commercial}.` : "Aucun commercial n'est rattaché à cette affaire.",
                  ],
                  kv: [
                    ["Client", o.client],
                    ["Commercial", o.commercial || "non renseigné"],
                    ["Étape", o.stage],
                    ["Montant", `${formatMFcfa(o.montant_xof)} M FCFA`],
                    ["Échéance", formatDate(o.deadline)],
                    ["Défauts", o.defauts_libelles.join(", ")],
                    ["Gravité", String(o.gravite)],
                  ],
                },
              }))}
            />
          ) : (
            <Note style={{ marginTop: 0 }}>Aucun dossier ouvert ne présente d&apos;information manquante.</Note>
          )}
        </Tile>

        <Tile
          span={5}
          title="Plus gros montants à requalifier"
          kick="échéance dépassée"
          aide="Les affaires en retard qui pèsent le plus lourd. Reprendre leur date avec le client corrige immédiatement la prévision."
        >
          {qualite.a_requalifier.length > 0 ? (
            <Lst
              items={qualite.a_requalifier.map((o) => ({
                title: o.name,
                sub: `${o.client} · ${o.stage} · ${o.jours_de_retard !== null ? `${formatNumber(o.jours_de_retard)} jours de retard` : "échéance passée"}`,
                tag: `${formatMFcfa(o.montant_xof)} M`,
                tagVariant: "r" as const,
                detail: {
                  kicker: "Opportunité · échéance dépassée",
                  title: o.name,
                  tag: "à requalifier",
                  tagVariant: "r" as const,
                  body: [
                    `${o.client} · ${o.stage} · ${formatMFcfa(o.montant_xof)} M FCFA. Échéance du ${formatDate(o.deadline)}, dépassée de ${o.jours_de_retard !== null ? formatNumber(o.jours_de_retard) : "?"} jour(s).`,
                    "Ce montant continue de peser dans le forecast tant que la date n'est pas révisée ou l'affaire close. C'est la première cause d'un chiffre annoncé plus haut que la réalité.",
                  ],
                  kv: [
                    ["Client", o.client],
                    ["Commercial", o.commercial || "non renseigné"],
                    ["Étape", o.stage],
                    ["Montant", `${formatMFcfa(o.montant_xof)} M FCFA`],
                    ["Échéance", formatDate(o.deadline)],
                    ["Retard", o.jours_de_retard !== null ? `${formatNumber(o.jours_de_retard)} jours` : "—"],
                  ],
                },
              }))}
            />
          ) : (
            <Note style={{ marginTop: 0 }}>Aucune opportunité ouverte ne porte d&apos;échéance dépassée.</Note>
          )}
        </Tile>

      </Bento>
    </>
  );
}
