import { getBriefing } from "@/lib/api/briefing";
import { getMarcheDc, SecteurStatique } from "@/lib/api/commercial";
import { formatDate, formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, Brief, HintLine, Orbit, OrbitPart, StatTile, Tile } from "@/components/ui/bento";
import { RAMPE_PART } from "@/components/ui/chart-palette";
import { Note } from "@/components/ui/primitives";

/** Verdict de lecture d'un secteur — un secteur ne se pilote pas au seul poids.
 *
 * Les seuils sont posés ici et nulle part ailleurs. Ils portent une convention
 * de LECTURE (à partir de quand un secteur est un socle, à partir de quand sa
 * décroissance mérite d'être signalée), pas une donnée : les déplacer change ce
 * que l'écran dit, ce qui est normal et voulu.
 *
 * L'ordre des tests compte : une décroissance forte l'emporte sur le poids, un
 * gros secteur qui recule est précisément ce qu'il faut voir en premier. */
function lectureSecteur(s: SecteurStatique): { libelle: string; ton: "s" | "w" | "r" | "n" | "a" } {
  if (s.croissance_pct <= -10) return { libelle: "en recul", ton: "r" };
  if (s.part_ca_pct >= 20) return { libelle: "socle", ton: "s" };
  if (s.croissance_pct >= 10) return { libelle: "en progression", ton: "a" };
  if (s.part_ca_pct < 5) return { libelle: "dispersé", ton: "n" };
  return { libelle: "stable", ton: "n" };
}

/** « Tendances et marché » — chapitre 1 du compte-rendu DC, et ÉCRAN D'OUVERTURE
 * du cockpit commercial.
 *
 * « Axe prioritaire à développer : évaluer les tendances : part du marché et selon
 * aussi la santé du marché orienté (Ex : Intelligence Artificielle et
 * infrastructure…) »
 *
 * C'est le premier point du compte-rendu, donc le premier onglet du premier
 * chapitre, donc l'écran sur lequel le cockpit s'ouvre : il porte à ce titre le
 * briefing du jour, que le DC doit voir sans avoir à le chercher.
 *
 * Deux demandes distinctes cohabitent dans ce chapitre, et l'écran doit empêcher de
 * les confondre :
 *
 * - la SANTÉ DU MARCHÉ ORIENTÉ (IA, infrastructure) est mesurable — sur NOS
 *   affaires. Une grille de motifs appliquée aux libellés d'opportunité ventile le
 *   pipe par axe de marché. C'est notre positionnement, pas l'état du marché ;
 * - la PART DE MARCHÉ ne l'est pas, et pour une raison qui ne se corrigera pas par
 *   de la saisie : il manque un univers de référence externe. Elle est donc affichée
 *   à côté de la part de portefeuille, nommée différemment — les confondre
 *   conduirait à des décisions erronées.
 *
 * La veille externe, elle, est réelle mais jeune : son taux de déchet est servi avec
 * elle, sans quoi une collecte à moitié inexploitable se lirait comme un panorama.
 */
export async function DcMarche() {
  const [marche, briefing] = await Promise.all([getMarcheDc(12), getBriefing()]);

  if (!marche) {
    return (
      <Bento>
        <Tile span={12} title="Tendances et marché">
          <Note style={{ marginTop: 0 }}>
            L&apos;analyse de marché n&apos;est pas accessible depuis ce profil.
          </Note>
        </Tile>
      </Bento>
    );
  }

  const { axes, secteurs, veille } = marche;
  const maxAxe = Math.max(...axes.axes.map((a) => a.montant_ouvert_xof), 1);
  const couvertureFaible = axes.coverage.couverture_montant_pct < 70;

  const briefLines = briefing?.section?.resume?.length
    ? briefing.section.resume
    : (briefing?.section?.bullets ?? []).slice(0, 5);

  const totalOuvert = axes.axes.reduce((s, a) => s + a.montant_ouvert_xof, 0);

  // Secteurs classés du plus lourd au plus léger : l'anneau extérieur de
  // `Orbit` doit être la part dominante, et le tableau se lit dans le même
  // ordre que l'anneau.
  const secteursClasses = [...secteurs.secteurs].sort((a, b) => b.ca_xof - a.ca_xof);
  const orbitParts: OrbitPart[] = secteursClasses.map((s, i) => ({
    name: s.secteur,
    value: `${formatMFcfa(s.ca_xof)} M`,
    pct: s.part_ca_pct,
    // La rampe est plus courte que la liste quand le miroir porte beaucoup de
    // secteurs : la queue reprend alors sa dernière teinte, qui est le neutre
    // le plus pâle — exactement le rôle qu'on veut lui donner.
    couleur: RAMPE_PART[Math.min(i, RAMPE_PART.length - 1)],
    detail: {
      kicker: "Secteur · part de portefeuille",
      title: s.secteur,
      tag: `${formatPct(s.part_ca_pct, 0)} % du CA`,
      tagVariant: lectureSecteur(s).ton,
      body: [
        `${formatNumber(s.nb_clients)} clients de ce secteur portent ${formatMFcfa(s.ca_xof)} M FCFA de chiffre d'affaires, soit ${formatPct(s.part_ca_pct, 0)} % du portefeuille renseigné.`,
        `Sa croissance observée est de ${s.croissance_pct >= 0 ? "+" : ""}${formatPct(s.croissance_pct, 0)} %.`,
        "Cette part est une part de NOTRE portefeuille, pas une part de marché : elle ne dit rien de ce que pèsent nos concurrents sur le même secteur.",
      ],
      kv: [
        ["Chiffre d'affaires", `${formatMFcfa(s.ca_xof)} M FCFA`],
        ["Clients", formatNumber(s.nb_clients)],
        ["Part du portefeuille", `${formatPct(s.part_ca_pct, 0)} %`],
        ["Croissance", `${s.croissance_pct >= 0 ? "+" : ""}${formatPct(s.croissance_pct, 0)} %`],
      ],
    },
  }));
  const troisPremiers = secteursClasses.slice(0, 3);
  const partTroisPremiers = troisPremiers.reduce((s, x) => s + x.part_ca_pct, 0);
  const clientsTroisPremiers = troisPremiers.reduce((s, x) => s + x.nb_clients, 0);
  // Effectif du GABARIT sectoriel, à ne pas confondre avec
  // `secteurs.couverture_reelle.nb_avec_secteur`, qui compte les clients du
  // miroir RÉEL portant un secteur (1 sur 1 381 à ce jour). Les deux chiffres
  // ne parlent pas de la même population : afficher la couverture réelle en
  // tête d'un tableau statique laisserait croire que ce tableau est mesuré.
  const clientsSecteurs = secteursClasses.reduce((s, x) => s + x.nb_clients, 0);

  return (
    <>
      <Brief
        kicker="Cockpit commercial · briefing du jour"
        headline={
          axes.dominante
            ? `${axes.dominante.axe} porte ${formatPct(axes.dominante.part_montant_pct, 0)} % du pipe qualifié, sur ${formatNumber(axes.coverage.nb_axes)} axes de marché.`
            : "Aucun axe de marché n'est qualifiable sur le pipe ouvert."
        }
        lines={briefLines}
        paragraphs={
          briefLines.length
            ? undefined
            : [
                `Le pipe ouvert qualifié se répartit sur ${formatNumber(axes.coverage.nb_axes)} axes pour ${formatMFcfa(totalOuvert)} M FCFA. Le briefing du jour n'est pas encore généré pour ce profil.`,
              ]
        }
        pills={[
          { label: `${formatNumber(axes.coverage.nb_axes)} axes de marché` },
          {
            label: `Pipe qualifié à ${formatPct(axes.coverage.couverture_montant_pct, 0)} %`,
            hot: couvertureFaible,
          },
          {
            label: `Secteur renseigné : ${formatNumber(secteurs.couverture_reelle.nb_avec_secteur)} client sur ${formatNumber(secteurs.couverture_reelle.nb_clients)}`,
            hot: true,
          },
          { label: `${formatNumber(veille.qualite.nb_avec_url)} signaux de veille exploitables` },
        ]}
      />

      <div className="kpi-row">
        {/* L'axe dominant est le seul des trois indicateurs mesuré sur le pipe
            réel ; la part de marché est supposée et les signaux de veille ne sont
            pas encore collectés — les deux reculent d'un plan sans disparaître. */}
        <StatTile
          span={4}
          rang="principal"
          label="Axe dominant du pipe"
          value={axes.dominante?.axe ?? "—"}
          unit={axes.dominante ? `${formatPct(axes.dominante.part_montant_pct, 0)} % du pipe qualifié` : ""}
          reading={`calculé sur ${formatPct(axes.coverage.couverture_montant_pct, 0)} % du pipe en montant`}
          readingVariant={couvertureFaible ? "wat" : undefined}
          // L'arc porte la PART DE L'AXE dominant, pas la couverture : c'est la
          // grandeur que le chiffre annonce. La couverture reste en ligne de
          // lecture, où elle nuance la mesure sans la concurrencer.
          cadran={
            axes.dominante ? { pct: axes.dominante.part_montant_pct ?? 0 } : undefined
          }
          detail={{
            kicker: "Indicateur · positionnement de marché",
            title: `${axes.dominante?.axe ?? "—"}, axe dominant`,
            tag: "mesuré",
            tagVariant: "s",
            body: [
              `Le pipe ouvert qualifié se répartit sur ${formatNumber(axes.coverage.nb_axes)} axes de marché, dominé par ${axes.dominante?.axe ?? "—"} à ${formatPct(axes.dominante?.part_montant_pct ?? null, 0)} % du montant.`,
              `L'axe est déduit du LIBELLÉ de l'opportunité au moyen d'une grille de ${formatNumber(axes.coverage.nb_motifs)} motifs éditables : le CRM ne porte aucune notion d'axe. ${formatNumber(axes.coverage.nb_non_classe)} opportunités (${formatMFcfa(axes.coverage.montant_non_classe_xof)} M FCFA) portent un libellé trop générique pour être qualifiées — les parts ci-dessus portent donc sur ${formatPct(axes.coverage.couverture_montant_pct, 0)} % du pipe.`,
              "Cette grille est une convention de lecture, pas une donnée extraite : la corriger fait bouger les chiffres, ce qui est normal et voulu.",
            ],
            kv: [
              ["Axe dominant", axes.dominante?.axe ?? "—"],
              ["Part du pipe qualifié", `${formatPct(axes.dominante?.part_montant_pct ?? null, 0)} %`],
              ["Axes distincts", formatNumber(axes.coverage.nb_axes)],
              ["Motifs de la grille", formatNumber(axes.coverage.nb_motifs)],
              ["Couverture en montant", `${formatPct(axes.coverage.couverture_montant_pct, 0)} %`],
              ["Opportunités non qualifiées", formatNumber(axes.coverage.nb_non_classe)],
            ],
          }}
        />
        <StatTile
          span={4}
          label="Part de marché"
          value={
            secteurs.totaux.part_marche_globale_pct !== null
              ? formatPct(secteurs.totaux.part_marche_globale_pct, 2)
              : "—"
          }
          unit="% — supposé, non mesuré"
          reading="aucune source externe de taille de marché"
          readingVariant="neg"
          detail={{
            kicker: "Indicateur · part de marché",
            title: "Ce qui est calculable et ce qui ne l'est pas",
            tag: "donnée statique",
            tagVariant: "n",
            body: [
              secteurs.part_marche.distinction,
              secteurs.part_marche.raison,
              `La valeur affichée rapporte un CA de gabarit à une taille de marché supposée de ${formatMFcfa(secteurs.totaux.taille_marche_xof)} M FCFA. Elle montre la forme de l'indicateur ; elle ne mesure rien.`,
            ],
            kv: [
              [
                "Part de marché supposée",
                secteurs.totaux.part_marche_globale_pct !== null
                  ? `${formatPct(secteurs.totaux.part_marche_globale_pct, 2)} %`
                  : "—",
              ],
              ["Taille de marché supposée", `${formatMFcfa(secteurs.totaux.taille_marche_xof)} M FCFA`],
              ["Source externe raccordée", "aucune"],
            ],
          }}
        />
        <StatTile
          span={4}
          rang="contexte"
          label="Signaux de veille exploitables"
          value={formatNumber(veille.qualite.nb_avec_url)}
          unit={`sur ${formatNumber(veille.qualite.nb_total)} collectés`}
          reading={
            veille.qualite.dernier_scan
              ? `dernière collecte le ${formatDate(veille.qualite.dernier_scan)}`
              : "aucune collecte"
          }
          readingVariant={veille.qualite.part_exploitable_pct < 60 ? "wat" : undefined}
          // Part de la collecte réellement exploitable : une proportion, donc un
          // arc. Le ton suit le même seuil que la ligne de lecture — les deux
          // marques disent la même chose, l'une en couleur, l'autre en mots.
          cadran={{
            pct: veille.qualite.part_exploitable_pct,
            ton: veille.qualite.part_exploitable_pct < 60 ? "w" : undefined,
          }}
          detail={{
            kicker: "Indicateur · veille externe",
            title: "Signaux de marché réellement exploitables",
            tag: `${formatPct(veille.qualite.part_exploitable_pct, 0)} %`,
            tagVariant: "w",
            body: [
              `${formatNumber(veille.qualite.nb_avec_url)} des ${formatNumber(veille.qualite.nb_total)} entrées collectées portent un lien exploitable. Les autres sont du bruit de collecte — libellés de menu capturés comme titres — et ne sont pas servies comme signaux.`,
              `Aucune des entrées ne porte de date de publication : l'ancienneté d'un signal n'est pas connue, seule sa date de détection l'est. Collecte du ${formatDate(veille.qualite.premier_scan)} au ${formatDate(veille.qualite.dernier_scan)}.`,
              veille.note,
            ],
            kv: [
              ["Entrées collectées", formatNumber(veille.qualite.nb_total)],
              ["Avec lien", formatNumber(veille.qualite.nb_avec_url)],
              ["Avec date de publication", formatNumber(veille.qualite.nb_avec_date_publication)],
              ["Part exploitable", `${formatPct(veille.qualite.part_exploitable_pct, 0)} %`],
              ...veille.sources.map((s) => [s.nom, s.active ? "active" : "inactive"] as [string, string]),
            ],
          }}
        />
      </div>

      {/* SECTION « POSITIONNEMENT » — les axes et les signaux se lisent ensemble :
          ce que nos affaires ouvertes disent du marché d'un côté, ce que la veille
          en dit de l'autre. Les deux tuiles étaient empilées sur toute la largeur,
          ce qui obligeait à faire défiler pour passer de l'une à l'autre alors
          qu'elles répondent à la même question. */}
      <div className="sec-h">
        <b>Positionnement</b>
        <span>ce que nos affaires ouvertes disent de notre marché</span>
      </div>

      <Bento>
        <Tile
          span={7}
          title="Santé du marché orienté — axes du pipe ouvert"
          kick={`mesuré · calculé sur ${formatPct(axes.coverage.couverture_montant_pct, 0)} % du pipe`}
        >
          <HintLine>Cliquez un axe pour son poids et son taux de réussite</HintLine>
          <Bars
            rows={axes.axes.map((a) => ({
              name: a.axe,
              sub: [
                `${formatNumber(a.nb_ouvertes)} opportunités ouvertes`,
                `${formatPct(a.part_montant_pct, 0)} % du pipe qualifié`,
                a.win_rate_pct !== null
                  ? `réussite ${formatPct(a.win_rate_pct, 0)} % sur ${formatNumber(a.nb_closes)} closes`
                  : "aucune affaire close",
              ].join(" · "),
              value: `${formatMFcfa(a.montant_ouvert_xof)} M`,
              pct: (a.montant_ouvert_xof / maxAxe) * 100,
              variant: a.part_montant_pct > 30 ? ("w" as const) : undefined,
              detail: {
                kicker: "Axe de marché · pipe ouvert",
                title: a.axe,
                tag: `${formatPct(a.part_montant_pct, 0)} % du pipe qualifié`,
                tagVariant: a.part_montant_pct > 30 ? ("w" as const) : ("a" as const),
                body: [
                  `${formatNumber(a.nb_ouvertes)} opportunités ouvertes sur cet axe pour ${formatMFcfa(a.montant_ouvert_xof)} M FCFA, soit ${formatMFcfa(a.montant_pondere_xof)} M FCFA pondérés par la probabilité déclarée.`,
                  a.win_rate_pct !== null
                    ? `Sur les ${formatNumber(a.nb_closes)} affaires déjà closes de cet axe, ${formatPct(a.win_rate_pct, 0)} % de la valeur engagée a été gagnée (${formatMFcfa(a.montant_gagne_xof)} M gagnés contre ${formatMFcfa(a.montant_perdu_xof)} M perdus). L'écart entre le poids dans le pipe et le taux de réussite est le signal à lire : se positionner massivement là où l'on gagne peu déplace le résultat.`
                    : "Aucune affaire close sur cet axe : son taux de réussite n'est pas encore calculable.",
                  "L'axe est déduit du libellé de l'opportunité par une grille de motifs, non lu dans un champ du CRM : un libellé plus explicite améliore directement la lecture.",
                ],
                kv: [
                  ["Pipe ouvert", `${formatMFcfa(a.montant_ouvert_xof)} M FCFA`],
                  ["Pipe pondéré", `${formatMFcfa(a.montant_pondere_xof)} M FCFA`],
                  ["Opportunités ouvertes", formatNumber(a.nb_ouvertes)],
                  ["Part du pipe qualifié", `${formatPct(a.part_montant_pct, 0)} %`],
                  ["Taux de réussite", a.win_rate_pct !== null ? `${formatPct(a.win_rate_pct, 0)} %` : "—"],
                  ["Affaires closes", formatNumber(a.nb_closes)],
                  ["Valeur gagnée", `${formatMFcfa(a.montant_gagne_xof)} M FCFA`],
                  ["Valeur perdue", `${formatMFcfa(a.montant_perdu_xof)} M FCFA`],
                ],
              },
            }))}
            // Le miroir porte dix axes ; les six premiers couvrent l'essentiel
            // du pipe et tiennent en face de l'anneau de concentration. Le repli
            // ne retire rien — la queue reste dépliable, et les parts affichées
            // portent toujours sur le pipe entier.
            replierApres={6}
            nom="axes"
          />
          <Note style={{ marginTop: 14 }}>{axes.note}</Note>
        </Tile>

        {/* CONCENTRATION DU PORTEFEUILLE — en vis-à-vis des axes, et non sous
            eux : les deux tuiles répondent à la même question (où pèse notre
            activité), l'une par le pipe ouvert, l'autre par le CA constaté.
            Elle occupe aussi la colonne de droite, que la veille — souvent
            vide — laissait en blanc sur toute la hauteur des axes. */}
        {secteursClasses.length > 0 && (
          <Tile
            span={5}
            title="Concentration du portefeuille"
            kick={`gabarit · ${formatNumber(clientsSecteurs)} clients`}
          >
            <Orbit parts={orbitParts} />
            <Note style={{ marginTop: 14 }}>
              Les trois anneaux portent les trois premiers secteurs : ensemble,{" "}
              {formatPct(partTroisPremiers, 0)} % du CA sur{" "}
              {formatNumber(clientsTroisPremiers)} clients.
            </Note>
          </Tile>
        )}

        {/* PART DE MARCHÉ — sous la concentration du portefeuille, dans la même
            colonne : les deux tuiles parlent de la même grandeur (ce que pèse
            notre CA), l'une répartie par secteur, l'autre rapportée au marché.
            Les lire l'une sous l'autre est ce qui empêche de confondre part de
            PORTEFEUILLE et part de MARCHÉ, distinction que la tuile elle-même
            passe deux notes à établir.

            « Signaux de marché détectés » a été retiré : la collecte de veille
            ne remonte aucune entrée exploitable (0 sur 0), et la tuile ne
            servait qu'à afficher deux notes expliquant cette absence. Le fait
            est déjà porté par l'indicateur « Signaux de veille exploitables »
            du bandeau, qui l'affiche chiffré. `marche.veille` reste servi par
            l'API et alimente cet indicateur — seule la LISTE des signaux n'est
            plus rendue. */}
        <Tile
          span={5}
          col={8}
          title="Part de marché : ce qui est calculable et ce qui ne l'est pas"
          quiet
        >
          <Bars
            rows={[
              {
                name: "Part de marché globale supposée",
                sub: `notre CA rapporté à une taille de marché de ${formatMFcfa(secteurs.totaux.taille_marche_xof)} M FCFA — aucune source externe raccordée`,
                value:
                  secteurs.totaux.part_marche_globale_pct !== null
                    ? `${formatPct(secteurs.totaux.part_marche_globale_pct, 2)} %`
                    : "—",
                pct: Math.min(100, (secteurs.totaux.part_marche_globale_pct ?? 0) * 10),
                variant: "w" as const,
              },
              {
                name: "Part de portefeuille de l'axe dominant",
                sub: "notre CA rapporté à notre propre total — calculable dès aujourd'hui",
                value: `${formatPct(axes.dominante?.part_montant_pct ?? null, 0)} %`,
                pct: axes.dominante?.part_montant_pct ?? 0,
                variant: "s" as const,
              },
            ]}
          />
          <Note accent style={{ marginTop: 14 }}>
            {secteurs.part_marche.distinction}
          </Note>
          <Note style={{ marginTop: 12 }}>{secteurs.part_marche.raison}</Note>
        </Tile>

        {/* PART DE PORTEFEUILLE PAR SECTEUR — le détail chiffré de l'anneau
            ci-dessus. Un tableau et non des barres : cinq grandeurs par ligne
            (clients, CA, part, pipe, lecture) ne tiennent pas sur une piste, et
            c'est leur mise en regard qui fait la lecture — un secteur qui pèse
            10 % du CA avec un pipe ouvert important ne se pilote pas comme un
            secteur qui pèse autant sans rien devant lui. */}
        {secteursClasses.length > 0 && (
          <Tile
            span={12}
            title="Part de portefeuille par secteur"
            kick={`gabarit · ${formatNumber(clientsSecteurs)} clients`}
          >
            <table className="tb">
              <thead>
                <tr>
                  <th>Secteur</th>
                  <th className="r">Clients</th>
                  <th className="r">CA 12 mois</th>
                  <th className="r">Part portefeuille</th>
                  <th className="r">Croissance</th>
                  <th>Lecture</th>
                </tr>
              </thead>
              <tbody>
                {secteursClasses.map((s) => {
                  const l = lectureSecteur(s);
                  return (
                    <tr key={s.secteur}>
                      <td>{s.secteur}</td>
                      <td className="r mono">{formatNumber(s.nb_clients)}</td>
                      <td className="r mono">{formatMFcfa(s.ca_xof)} M</td>
                      <td className="r mono">{formatPct(s.part_ca_pct, 0)} %</td>
                      <td className="r mono">
                        {s.croissance_pct >= 0 ? "+" : ""}
                        {formatPct(s.croissance_pct, 0)} %
                      </td>
                      <td>
                        <span className={`tag tag--${l.ton}`}>{l.libelle}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <Note style={{ marginTop: 14 }}>{secteurs.avertissement}</Note>
          </Tile>
        )}
      </Bento>
    </>
  );
}
