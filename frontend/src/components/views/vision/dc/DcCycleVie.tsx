import { getCycleVie } from "@/lib/api/commercial";
import { formatDate, formatFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, HintLine, Lst, StatTile, Tile } from "@/components/ui/bento";
import { Note } from "@/components/ui/primitives";
import { SourceNote, sourceKick } from "./source";

/** Onglet « Cycle de vie » — §2 du compte-rendu DC.
 *
 * « Cycle de vie de l'opportunité à tracer de bout en bout, pour les opportunités
 * à partir de 30 millions. »
 *
 * L'écran est organisé selon le DEGRÉ DE TRAÇABILITÉ réellement atteint, parce que
 * c'est l'information la plus utile ici — et la plus facile à travestir :
 *
 * 1. le STOCK au-dessus du seuil est entièrement mesuré (combien, quel montant,
 *    quelle étape, quel âge) ;
 * 2. la DURÉE création → clôture n'est mesurable que sur une fraction des affaires
 *    closes, et le chiffre est masqué quand la couverture est trop faible pour
 *    qu'il décrive autre chose qu'un échantillon ;
 * 3. la DURÉE PAR ÉTAPE n'est pas mesurable du tout : le miroir écrase l'étape
 *    précédente. Le gabarit est affiché comme tel, à côté de la profondeur réelle
 *    de l'historique en cours de constitution.
 *
 * Le nombre d'affaires au-dessus du seuil est lui-même une information à porter au
 * DC : le cadrage supposait « une vingtaine par an », le pipe en compte mille.
 */
export async function DcCycleVie() {
  const cycle = await getCycleVie(15);

  if (!cycle) {
    return (
      <Bento>
        <Tile span={12} title="Cycle de vie des affaires">
          <Note style={{ marginTop: 0 }}>Le pipeline n&apos;est pas accessible depuis ce profil.</Note>
        </Tile>
      </Bento>
    );
  }

  const { stock, duree_close: duree, historique_etapes: histo } = cycle;
  const maxEtape = Math.max(...cycle.par_etape.map((e) => e.montant_xof), 1);
  const maxGabarit = Math.max(...histo.durees_par_etape.map((e) => e.duree_mediane_jours), 1);

  return (
    <>
      <div className="kpi-row">
        <StatTile
          span={4}
          label={`Affaires ≥ ${formatFcfa(cycle.seuil_xof)} FCFA`}
          aide="Le nombre de grosses affaires actuellement en cours. Ce sont celles dont le cadrage demandait un suivi de bout en bout."
          value={formatNumber(stock.nb_ouvertes)}
          unit="ouvertes"
          reading={`${formatFcfa(stock.montant_ouvert_xof)} FCFA · ${formatPct(stock.part_pipe_ouvert_pct, 0)} % du pipe ouvert`}
          detail={{
            kicker: "Indicateur · périmètre tracé",
            title: `Affaires au-dessus du seuil de ${formatFcfa(cycle.seuil_xof)} FCFA`,
            tag: `${formatNumber(stock.nb_total)} au total`,
            tagVariant: "a",
            body: [
              `${formatNumber(stock.nb_ouvertes)} affaires ouvertes dépassent le seuil, pour ${formatFcfa(stock.montant_ouvert_xof)} FCFA — soit ${formatPct(stock.part_pipe_ouvert_pct, 0)} % du pipe ouvert en montant. Pondérées par la probabilité déclarée, elles ressortent à ${formatFcfa(stock.montant_ouvert_pondere_xof)} FCFA.`,
              `Le miroir en compte ${formatNumber(stock.nb_total)} au total, dont ${formatNumber(stock.nb_closes)} déjà closes.`,
              `Point à trancher : le cadrage supposait une vingtaine d'affaires par an au-dessus de ce seuil. Le pipe en porte ${formatNumber(stock.nb_ouvertes)} ouvertes à lui seul. Soit le seuil doit monter, soit le traçage « de bout en bout » ne peut pas être manuel.`,
            ],
            kv: [
              ["Ouvertes", formatNumber(stock.nb_ouvertes)],
              ["Montant ouvert", `${formatFcfa(stock.montant_ouvert_xof)} FCFA`],
              ["Montant pondéré", `${formatFcfa(stock.montant_ouvert_pondere_xof)} FCFA`],
              ["Closes", formatNumber(stock.nb_closes)],
              ["Seuil appliqué", `${formatFcfa(cycle.seuil_xof)} FCFA`],
            ],
          }}
        />
        {/* Les affaires enlisées sont ce sur quoi on agit ; le stock au-dessus du
            seuil et la durée de cycle donnent l'échelle et la norme. */}
        <StatTile
          span={4}
          rang="principal"
          label="Affaires enlisées"
          aide="Les grosses affaires qui n'ont pas bougé depuis trop longtemps. Ni gagnées, ni perdues, ni avancées : ce sont celles à débloquer ou à fermer."
          value={formatNumber(stock.nb_enlisees)}
          unit={`ouvertes depuis ${stock.seuil_enlisement_jours} jours+`}
          reading={
            stock.nb_ouvertes
              ? `${formatPct((100 * stock.nb_enlisees) / stock.nb_ouvertes, 0)} % des affaires suivies`
              : "aucune affaire suivie"
          }
          readingVariant={stock.nb_enlisees > 0 ? "neg" : undefined}
          detail={{
            kicker: "Indicateur · vélocité",
            title: "Affaires ouvertes depuis plus de deux trimestres",
            tag: `${stock.seuil_enlisement_jours} jours`,
            tagVariant: "r",
            body: [
              `${formatNumber(stock.nb_enlisees)} affaires au-dessus du seuil sont ouvertes depuis plus de ${stock.seuil_enlisement_jours} jours.`,
              "Deux trimestres, c'est le seuil retenu : une affaire qui traverse deux forecasts sans se conclure a cessé d'être une prévision.",
              "L'âge n'est calculé que sur les affaires dont la date de création est exploitable — celles portant une date d'import en masse ne sont jamais déclarées enlisées, faute de savoir depuis quand elles existent.",
            ],
            kv: [
              ["Enlisées", formatNumber(stock.nb_enlisees)],
              ["Seuil d'enlisement", `${stock.seuil_enlisement_jours} jours`],
              ["Affaires ouvertes suivies", formatNumber(stock.nb_ouvertes)],
            ],
          }}
        />
        <StatTile
          span={4}
          label="Durée de cycle mesurée"
          aide="Le temps qu'il faut en moyenne entre l'ouverture d'une affaire et sa conclusion. Calculé sur les affaires déjà terminées qui portent les dates nécessaires."
          value={duree.exploitable && duree.mediane_jours !== null ? formatNumber(duree.mediane_jours) : "—"}
          unit={duree.exploitable ? "jours (médiane)" : "non mesurable"}
          reading={`${formatNumber(duree.nb_mesurees)} affaires datées sur ${formatNumber(duree.nb_closes_total)} closes (${formatPct(duree.couverture_pct, 1)} %)`}
          readingVariant={duree.exploitable ? undefined : "wat"}
          detail={{
            kicker: "Indicateur · durée création → clôture",
            title: "Durée de cycle sur les affaires closes",
            tag: duree.exploitable ? "mesurée" : "couverture insuffisante",
            tagVariant: duree.exploitable ? "s" : "w",
            body: [
              `${formatNumber(duree.nb_mesurees)} affaires closes au-dessus du seuil portent à la fois une date de création exploitable et une date de clôture, sur ${formatNumber(duree.nb_closes_total)} — soit ${formatPct(duree.couverture_pct, 1)} %.`,
              duree.exploitable
                ? `La durée médiane s'établit à ${formatNumber(duree.mediane_jours ?? 0)} jours, la moyenne à ${formatNumber(duree.moyenne_jours ?? 0)} jours.`
                : duree.raison_non_exploitable,
              "Les dates de création correspondant aux imports en masse sont écartées du calcul : les retenir donnerait des affaires de quelques mois d'âge pour des dossiers ouverts depuis des années.",
            ],
            kv: [
              ["Affaires mesurées", formatNumber(duree.nb_mesurees)],
              ["Closes au-dessus du seuil", formatNumber(duree.nb_closes_total)],
              ["Couverture", `${formatPct(duree.couverture_pct, 1)} %`],
              ["Médiane", duree.mediane_jours !== null ? `${formatNumber(duree.mediane_jours)} jours` : "—"],
              ["Moyenne", duree.moyenne_jours !== null ? `${formatNumber(duree.moyenne_jours)} jours` : "—"],
            ],
          }}
        />
      </div>

      <Bento>
        <Tile
          span={7}
          title={`Où se tiennent les affaires ≥ ${formatFcfa(cycle.seuil_xof)}`}
          kick="mesuré · par étape"
          aide="À quel stade d'avancement se trouvent vos grosses affaires en cours. Une accumulation sur une même étape signale l'endroit où ça coince."
        >
          <HintLine>Cliquez une étape pour son poids</HintLine>
          <Bars
            rows={cycle.par_etape.slice(0, 8).map((e) => {
              const part = stock.montant_ouvert_xof ? (e.montant_xof / stock.montant_ouvert_xof) * 100 : 0;
              return {
                name: e.stage,
                sub: `${formatNumber(e.nb)} affaires · ${formatPct(part, 0)} % du montant suivi`,
                value: `${formatFcfa(e.montant_xof)}`,
                pct: (e.montant_xof / maxEtape) * 100,
                variant: part > 40 ? ("w" as const) : undefined,
                detail: {
                  kicker: "Étape · affaires au-dessus du seuil",
                  title: e.stage,
                  tag: `${formatPct(part, 0)} % du montant suivi`,
                  tagVariant: part > 40 ? ("w" as const) : ("a" as const),
                  body: [
                    `${formatNumber(e.nb)} affaires au-dessus du seuil sont à l'étape « ${e.stage} », pour ${formatFcfa(e.montant_xof)} FCFA.`,
                    part > 40
                      ? "Cette étape porte à elle seule plus de 40 % du montant suivi : un défaut de calibrage à cet endroit déplace tout le chiffre annoncé."
                      : "Le poids de cette étape reste réparti.",
                    "Cette photo dit où les affaires SONT, pas depuis combien de temps elles y sont : la durée passée à chaque étape n'est pas conservée par le miroir.",
                  ],
                  kv: [
                    ["Affaires", formatNumber(e.nb)],
                    ["Montant", `${formatFcfa(e.montant_xof)} FCFA`],
                    ["Part du montant suivi", `${formatPct(part, 0)} %`],
                  ],
                },
              };
            })}
          />
        </Tile>

        <Tile
          span={5}
          title="Affaires suivies, par montant"
          kick={`${formatNumber(cycle.affaires.length)} affichées`}
          aide="Le détail des grosses affaires une par une : montant, étape, et depuis combien de temps elles sont ouvertes."
        >
          <HintLine>Cliquez une affaire pour son âge et son état</HintLine>
          {/* Repli à 7 : la liste porte jusqu'à quinze affaires et occupait à elle
              seule plus d'un écran, reléguant les blocs suivants sous la ligne de
              flottaison. Les sept premières suffisent à la lecture courante (les
              plus gros montants), le reste est à un clic. */}
          <Lst
            replierApres={7}
            nom="affaires"
            items={cycle.affaires.map((a) => ({
              title: a.name,
              sub: [
                a.client,
                a.stage,
                a.age_jours !== null ? `ouverte depuis ${formatNumber(a.age_jours)} j` : "âge inconnu",
                a.echeance_depassee ? "échéance dépassée" : null,
              ]
                .filter(Boolean)
                .join(" · "),
              tag: a.enlisee ? "enlisée" : `${formatFcfa(a.montant_xof)}`,
              tagVariant: a.enlisee ? ("r" as const) : ("a" as const),
              detail: {
                kicker: "Affaire · cycle de vie",
                title: a.name,
                tag: a.enlisee ? "enlisée" : "en cours",
                tagVariant: a.enlisee ? ("r" as const) : ("a" as const),
                body: [
                  `${a.client} · ${a.stage} · ${formatFcfa(a.montant_xof)} FCFA à ${formatPct(a.probabilite_pct, 0)} % de probabilité déclarée, portée par ${a.commercial || "aucun commercial rattaché"}.`,
                  a.age_jours !== null
                    ? `Ouverte depuis ${formatNumber(a.age_jours)} jours (création le ${formatDate(a.creee_le)}).${a.enlisee ? ` Au-delà de ${stock.seuil_enlisement_jours} jours, l'affaire a traversé deux forecasts sans se conclure.` : ""}`
                    : "Sa date de création est une date d'import en masse : l'âge réel de cette affaire est inconnu, et elle n'est donc jamais déclarée enlisée.",
                  a.echeance_depassee
                    ? `Son échéance du ${formatDate(a.deadline)} est dépassée : le montant pèse encore dans le forecast tant qu'elle n'est pas requalifiée.`
                    : `Échéance prévue le ${formatDate(a.deadline)}.`,
                ],
                kv: [
                  ["Client", a.client],
                  ["Commercial", a.commercial || "non renseigné"],
                  ["Étape", a.stage],
                  ["Montant", `${formatFcfa(a.montant_xof)} FCFA`],
                  ["Probabilité déclarée", `${formatPct(a.probabilite_pct, 0)} %`],
                  ["Créée le", formatDate(a.creee_le)],
                  ["Âge", a.age_jours !== null ? `${formatNumber(a.age_jours)} jours` : "inconnu"],
                  ["Échéance", formatDate(a.deadline)],
                ],
              },
            }))}
          />
        </Tile>

        <Tile
          span={7}
          title="Durée par étape du cycle"
          kick={sourceKick(histo.source, "gabarit")}
          aide="Le temps passé à chaque étape. Ces durées ne sont pas mesurées : le système ne conserve pas l'étape précédente d'une affaire. C'est la forme que prendra l'indicateur, pas encore son contenu."
        >
          <HintLine>Cliquez une étape pour ce que le gabarit suppose</HintLine>
          <Bars
            rows={histo.durees_par_etape.map((e) => ({
              name: e.etape,
              sub: `${formatPct(e.part_abandon_pct, 0)} % d'abandon à cette étape`,
              value: `${formatNumber(e.duree_mediane_jours)} j`,
              pct: (e.duree_mediane_jours / maxGabarit) * 100,
              variant: undefined,
              detail: {
                kicker: "Étape · durée (gabarit)",
                title: e.etape,
                tag: "donnée statique",
                tagVariant: "n" as const,
                body: [
                  `Le gabarit pose une durée médiane de ${formatNumber(e.duree_mediane_jours)} jours à cette étape, avec ${formatPct(e.part_abandon_pct, 0)} % d'abandon.`,
                  "Ces valeurs ne sont PAS mesurées : le miroir écrase l'étape précédente à chaque mise à jour, on sait où en est une affaire mais pas par où elle est passée.",
                  histo.raison,
                ],
                kv: [
                  ["Durée médiane (gabarit)", `${formatNumber(e.duree_mediane_jours)} jours`],
                  ["Abandon (gabarit)", `${formatPct(e.part_abandon_pct, 0)} %`],
                ],
              },
            }))}
          />
          <SourceNote source={histo.source} raison={histo.raison} avertissement={histo.avertissement} />
        </Tile>

        <Tile
          span={5}
          title="Historique en cours de constitution"
          kick="mesuré"
          aide="Depuis quand le cockpit enregistre les changements d'étape. Plus cette profondeur augmente, plus les durées par étape deviendront réelles."
        >
          <Bars
            rows={[
              {
                name: "Instantanés du pipeline disponibles",
                sub:
                  histo.profondeur_reelle.premier && histo.profondeur_reelle.dernier
                    ? `du ${formatDate(histo.profondeur_reelle.premier)} au ${formatDate(histo.profondeur_reelle.dernier)}`
                    : "aucun instantané",
                value: formatNumber(histo.profondeur_reelle.nb_instantanes),
                pct: Math.min(100, (histo.profondeur_reelle.nb_instantanes / 30) * 100),
                variant: histo.profondeur_reelle.exploitable ? ("s" as const) : ("w" as const),
              },
              {
                name: "Profondeur de l'historique",
                sub: "un trimestre est le minimum pour mesurer une durée d'étape",
                value: `${formatNumber(histo.profondeur_reelle.profondeur_jours)} j`,
                pct: Math.min(100, (histo.profondeur_reelle.profondeur_jours / 90) * 100),
                variant: histo.profondeur_reelle.exploitable ? ("s" as const) : ("w" as const),
              },
              {
                name: "Affaires ayant changé d'étape",
                sub: `sur ${formatNumber(histo.mouvement_observe.nb_suivies)} suivies entre les deux instantanés extrêmes`,
                value: formatNumber(histo.mouvement_observe.nb_changements_etape),
                pct: histo.mouvement_observe.nb_suivies
                  ? Math.min(100, (histo.mouvement_observe.nb_changements_etape / histo.mouvement_observe.nb_suivies) * 100 * 20)
                  : 0,
                variant: histo.mouvement_observe.nb_changements_etape > 0 ? undefined : ("r" as const),
              },
            ]}
          />
          <Note style={{ marginTop: 14 }}>
            Le pipeline est photographié chaque nuit : l&apos;historique nécessaire au traçage de bout en
            bout se constitue donc à partir de maintenant, sans rattraper le passé. Sur la fenêtre
            disponible ({formatNumber(histo.profondeur_reelle.profondeur_jours)} jours),{" "}
            {formatNumber(histo.mouvement_observe.nb_changements_etape)} affaire(s) sur{" "}
            {formatNumber(histo.mouvement_observe.nb_suivies)} ont changé d&apos;étape et{" "}
            {formatNumber(histo.mouvement_observe.nb_changements_montant)} de montant.
            {histo.mouvement_observe.nb_changements_etape === 0 &&
              " Aucun mouvement observé : le problème n'est pas la mécanique de capture, c'est que le pipe du miroir ne bouge pas."}
          </Note>
        </Tile>

        {histo.mouvement_observe.changements_etape.length > 0 && (
          <Tile
            span={12}
            title="Mouvements d'étape observés"
            kick="mesuré · entre deux instantanés"
            aide="Les affaires qui ont changé d'étape depuis le dernier relevé : ce qui a avancé, ce qui a reculé."
          >
            <Lst
              items={histo.mouvement_observe.changements_etape.map((m) => ({
                title: m.name,
                sub: `${m.client} · ${m.etape_avant} → ${m.etape_apres} · ${m.commercial || "commercial non renseigné"}`,
                tag: `${formatFcfa(m.montant_xof)}`,
                tagVariant: "s" as const,
                detail: {
                  kicker: "Mouvement · changement d'étape",
                  title: m.name,
                  tag: "avancée constatée",
                  tagVariant: "s" as const,
                  body: [
                    `Cette affaire est passée de « ${m.etape_avant} » à « ${m.etape_apres} » entre le ${formatDate(histo.mouvement_observe.depuis)} et le ${formatDate(histo.mouvement_observe.jusqu_a)}.`,
                    "C'est le seul type de mouvement que les instantanés permettent aujourd'hui de constater. Accumulés, ils donneront la durée réelle passée à chaque étape.",
                  ],
                  kv: [
                    ["Client", m.client],
                    ["Étape avant", m.etape_avant],
                    ["Étape après", m.etape_apres],
                    ["Montant", `${formatFcfa(m.montant_xof)} FCFA`],
                    ["Commercial", m.commercial || "non renseigné"],
                  ],
                },
              }))}
            />
          </Tile>
        )}

      </Bento>
    </>
  );
}
