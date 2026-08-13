import { getComptesDc, getEquipeDc, Periode } from "@/lib/api/commercial";
import { formatDate, formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, HintLine, Lst, StatTile, Tile } from "@/components/ui/bento";
import { Note } from "@/components/ui/primitives";
import { PeriodeNav } from "./periode-nav";
import { SourceNote, sourceKick } from "./source";

/** « Indice de prospection » — chapitre 3 du compte-rendu DC.
 *
 * « Indice de prospection : nombre d'opportunités générées, décliné par mois, par
 * trimestre et par an » et « un focus particulier sur l'acquisition de nouveaux
 * comptes / nouveaux clients ».
 *
 * Deux moitiés de faisabilité opposée, présentées côte à côte pour que la
 * différence soit visible du premier coup d'œil :
 *
 * - L'INDICE DE PROSPECTION est un GABARIT. C'est une mesure de FLUX, et le miroir
 *   n'a pas de date de création exploitable : deux imports en masse concentrent
 *   6 475 créations sur deux journées. Aucune table de leads n'existe par ailleurs.
 * - L'ACQUISITION DE NOUVEAUX COMPTES est MESURÉE, et c'est la réponse utilisable
 *   dès aujourd'hui au « focus nouveaux clients » : la première commande signée
 *   d'un compte est une date fiable, elle.
 *
 * Servir la seconde sans la première serait ignorer la demande ; servir la première
 * sans la seconde laisserait le DC devant un écran entièrement fictif.
 */
export async function DcProspection({ periode, annee }: { periode: Periode; annee?: number }) {
  const [equipe, comptes] = await Promise.all([getEquipeDc(annee, periode), getComptesDc(10)]);

  if (!equipe) {
    return (
      <Bento>
        <Tile span={12} title="Indice de prospection">
          <Note style={{ marginTop: 0 }}>
            Le suivi de prospection n&apos;est pas accessible depuis ce profil.
          </Note>
        </Tile>
      </Bento>
    );
  }

  const prosp = equipe.prospection;
  const acquisition = comptes?.acquisition;
  const maxProsp = Math.max(...prosp.lignes.map((l) => l.nb_opportunites), 1);
  const maxAcq = Math.max(...(acquisition?.annees ?? []).map((a) => a.nb_comptes), 1);

  return (
    <>
      <PeriodeNav basePath="/dc/vision/prospection" periode={prosp.periode} annee={prosp.annee} />

      <div className="kpi-row">
        <StatTile
          span={4}
          label="Opportunités générées"
          value={formatNumber(prosp.totaux.nb_opportunites)}
          unit={`objectif ${formatNumber(prosp.objectif_annuel_nb)}`}
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
              ["Taux d'atteinte", `${formatPct(prosp.totaux.taux_atteinte_pct, 0)} %`],
              ["Montant généré (gabarit)", `${formatMFcfa(prosp.totaux.montant_genere_xof)} M FCFA`],
            ],
          }}
        />
        {acquisition ? (
          <StatTile
            span={4}
            label={`Nouveaux comptes ${acquisition.annee_courante.annee}`}
            value={formatNumber(acquisition.annee_courante.nb_comptes)}
            unit="premières commandes"
            reading={`${formatNumber(acquisition.annee_courante.nb_comptes_annee_precedente)} sur l'exercice précédent complet — mesuré`}
            detail={{
              kicker: "Indicateur · acquisition (mesuré)",
              title: "Comptes entrés en portefeuille cette année",
              tag: "mesuré",
              tagVariant: "s",
              body: [
                `${formatNumber(acquisition.annee_courante.nb_comptes)} comptes ont passé leur première commande en ${acquisition.annee_courante.annee}, pour ${formatMFcfa(acquisition.annee_courante.ca_xof)} M FCFA de CA cumulé depuis leur entrée.`,
                `L'exercice précédent en a compté ${formatNumber(acquisition.annee_courante.nb_comptes_annee_precedente)} sur douze mois complets : la comparaison n'est valable qu'à date équivalente.`,
                "C'est la seule mesure fiable du « focus nouveaux comptes » demandé : la date de première commande signée existe, contrairement aux dates de création d'opportunité.",
              ],
              kv: [
                ["Nouveaux comptes", formatNumber(acquisition.annee_courante.nb_comptes)],
                ["CA cumulé associé", `${formatMFcfa(acquisition.annee_courante.ca_xof)} M FCFA`],
                ["Exercice précédent", formatNumber(acquisition.annee_courante.nb_comptes_annee_precedente)],
              ],
            }}
          />
        ) : null}
        {acquisition ? (
          <StatTile
            span={4}
            label="Vivier de prospects"
            value={formatNumber(acquisition.vivier.nb_prospects)}
            unit="jamais commandé"
            reading={`${formatNumber(acquisition.vivier.nb_comptes_avec_commande)} comptes ont déjà commandé — mesuré`}
            detail={{
              kicker: "Indicateur · vivier (mesuré)",
              title: "Comptes du référentiel n'ayant jamais commandé",
              tag: "prospects",
              tagVariant: "n",
              body: [
                `${formatNumber(acquisition.vivier.nb_prospects)} comptes existent dans le référentiel clients sans avoir jamais passé de commande. Ce ne sont pas des clients perdus : ce sont des prospects.`,
                `${formatNumber(acquisition.vivier.nb_comptes_avec_commande)} comptes ont, eux, au moins une commande signée.`,
                "Ce vivier est le dénominateur naturel d'un indice de prospection réel, le jour où l'amont de l'opportunité sera remonté de l'ERP.",
              ],
              kv: [
                ["Prospects", formatNumber(acquisition.vivier.nb_prospects)],
                ["Comptes clients", formatNumber(acquisition.vivier.nb_comptes_avec_commande)],
              ],
            }}
          />
        ) : null}
      </div>

      <Bento>
        <Tile
          span={12}
          title="Indice de prospection"
          kick={sourceKick(
            prosp.source,
            prosp.periode === "mois" ? "mensuel" : prosp.periode === "trimestre" ? "trimestriel" : "annuel",
          )}
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
                  "Ce qui EST mesurable et le remplace utilement : le nombre de comptes ayant passé leur première commande, dans la tuile d'acquisition ci-dessous.",
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

        {acquisition && (
          <>
            <Tile span={7} title="Acquisition de nouveaux comptes par exercice" kick="mesuré · première commande signée">
              <HintLine>Cliquez un exercice pour ses comptes entrants</HintLine>
              <Bars
                rows={acquisition.annees
                  .slice()
                  .reverse()
                  .map((a) => ({
                    name: String(a.annee),
                    sub: `${formatMFcfa(a.ca_xof)} M FCFA de CA cumulé depuis leur entrée${a.annee === acquisition.annee_courante.annee ? " · exercice en cours" : ""}`,
                    value: formatNumber(a.nb_comptes),
                    pct: (a.nb_comptes / maxAcq) * 100,
                    variant: a.annee === acquisition.annee_courante.annee ? ("s" as const) : undefined,
                    detail: {
                      kicker: "Exercice · comptes entrants",
                      title: `${formatNumber(a.nb_comptes)} nouveaux comptes en ${a.annee}`,
                      tag: `${formatMFcfa(a.ca_xof)} M FCFA cumulés`,
                      tagVariant: "a" as const,
                      body: [
                        `${formatNumber(a.nb_comptes)} comptes ont passé leur première commande en ${a.annee}. Leur CA cumulé depuis l'entrée atteint ${formatMFcfa(a.ca_xof)} M FCFA — un montant qui court sur toutes les années suivantes, pas seulement sur ${a.annee}.`,
                        a.annee === acquisition.annee_courante.annee
                          ? "Exercice en cours : le compte n'est pas comparable à une année pleine."
                          : "Exercice complet.",
                      ],
                      kv: [
                        ["Nouveaux comptes", formatNumber(a.nb_comptes)],
                        ["CA cumulé", `${formatMFcfa(a.ca_xof)} M FCFA`],
                        ...a.comptes.slice(0, 6).map(
                          (c) =>
                            [c.compte, `${formatMFcfa(c.ca_total_xof)} M · ${formatNumber(c.nb_commandes)} cmd`] as [
                              string,
                              string,
                            ],
                        ),
                      ],
                    },
                  }))}
              />
              <Note style={{ marginTop: 14 }}>{acquisition.note}</Note>
            </Tile>

            <Tile
              span={5}
              title={`Comptes entrés en ${acquisition.annee_courante.annee}`}
              kick="mesuré · par CA depuis l'entrée"
            >
              {(acquisition.annees.find((a) => a.annee === acquisition.annee_courante.annee)?.comptes ?? []).length >
              0 ? (
                <Lst
                  items={(
                    acquisition.annees.find((a) => a.annee === acquisition.annee_courante.annee)?.comptes ?? []
                  ).map((c) => ({
                    title: c.compte,
                    sub: `première commande le ${formatDate(c.premiere_commande)} · ${formatNumber(c.nb_commandes)} commande(s)${c.commercial ? ` · ${c.commercial}` : ""}`,
                    tag: `${formatMFcfa(c.ca_total_xof)} M`,
                    tagVariant: "s" as const,
                    detail: {
                      kicker: "Nouveau compte",
                      title: c.compte,
                      tag: `${formatMFcfa(c.ca_total_xof)} M FCFA`,
                      tagVariant: "s" as const,
                      body: [
                        `Première commande signée le ${formatDate(c.premiere_commande)}. Depuis, ${formatNumber(c.nb_commandes)} commande(s) pour ${formatMFcfa(c.ca_total_xof)} M FCFA.`,
                        c.commercial
                          ? `Compte rattaché à ${c.commercial} sur sa dernière commande.`
                          : "Aucun commercial rattaché sur sa dernière commande.",
                      ],
                      kv: [
                        ["Première commande", formatDate(c.premiere_commande)],
                        ["CA depuis l'entrée", `${formatMFcfa(c.ca_total_xof)} M FCFA`],
                        ["Commandes", formatNumber(c.nb_commandes)],
                        ["Commercial", c.commercial || "non renseigné"],
                      ],
                    },
                  }))}
                />
              ) : (
                <Note style={{ marginTop: 0 }}>
                  Aucun compte n&apos;a passé de première commande sur l&apos;exercice en cours.
                </Note>
              )}
            </Tile>
          </>
        )}
      </Bento>
    </>
  );
}
