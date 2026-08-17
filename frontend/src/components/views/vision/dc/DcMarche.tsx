import { getBriefing } from "@/lib/api/briefing";
import { getMarcheDc } from "@/lib/api/commercial";
import { formatDate, formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, Brief, HintLine, Lst, StatTile, Tile } from "@/components/ui/bento";
import { Note } from "@/components/ui/primitives";

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
          aide="Le domaine sur lequel vous avez le plus d'affaires en cours, en montant. Il dit où votre activité se concentre aujourd'hui — pas où elle rapporte le plus."
          value={axes.dominante?.axe ?? "—"}
          unit={axes.dominante ? `${formatPct(axes.dominante.part_montant_pct, 0)} % du pipe qualifié` : ""}
          reading={`calculé sur ${formatPct(axes.coverage.couverture_montant_pct, 0)} % du pipe en montant`}
          readingVariant={couvertureFaible ? "wat" : undefined}
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
          aide="La place que vous occuperiez sur votre marché. Le chiffre est une illustration, pas une mesure : il faudrait connaître la taille réelle du marché, information dont le cockpit ne dispose pas."
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
          aide="Les actualités de marché collectées automatiquement qui sont réellement consultables. Une partie de la collecte est inutilisable, ce compteur ne retient que le reste."
          value={formatNumber(veille.qualite.nb_avec_url)}
          unit={`sur ${formatNumber(veille.qualite.nb_total)} collectés`}
          reading={
            veille.qualite.dernier_scan
              ? `dernière collecte le ${formatDate(veille.qualite.dernier_scan)}`
              : "aucune collecte"
          }
          readingVariant={veille.qualite.part_exploitable_pct < 60 ? "wat" : undefined}
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

      <Bento>
        <Tile
          span={12}
          title="Santé du marché orienté — axes du pipe ouvert"
          kick={`mesuré · calculé sur ${formatPct(axes.coverage.couverture_montant_pct, 0)} % du pipe`}
          aide="Vos affaires en cours réparties par domaine d'activité, de la plus grosse enveloppe à la plus petite. À lire en comparant deux choses : le poids d'un domaine et le taux de réussite qui l'accompagne."
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
          />
          <Note style={{ marginTop: 14 }}>{axes.note}</Note>
        </Tile>

        <Tile
          span={12}
          title="Part de marché : ce qui est calculable et ce qui ne l'est pas"
          aide="La différence entre deux chiffres qu'on confond souvent : votre place sur le marché (inconnue, faute de référence extérieure) et le poids d'un domaine chez vous (connu). Les traiter comme équivalents conduit à des décisions fausses."
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

        <Tile
          span={12}
          title="Signaux de marché détectés"
          kick={`mesuré · ${formatNumber(veille.signaux.length)} signaux exploitables`}
          aide="Les actualités repérées automatiquement qui peuvent justifier une prise de contact : appels d'offres, levées de fonds, nominations. Classées par urgence à les traiter."
        >
          {veille.signaux.length > 0 ? (
            <>
              <HintLine>Cliquez un signal pour sa lecture commerciale</HintLine>
              <Lst
                items={veille.signaux.map((s) => ({
                  title: s.titre,
                  sub: [s.source, s.pays, s.detecte_le ? `détecté le ${formatDate(s.detecte_le)}` : null]
                    .filter(Boolean)
                    .join(" · "),
                  tag: s.criticite >= 70 ? "à traiter" : s.criticite >= 40 ? "à qualifier" : "à surveiller",
                  tagVariant: s.criticite >= 70 ? ("r" as const) : s.criticite >= 40 ? ("w" as const) : ("n" as const),
                  detail: {
                    kicker: `Signal de marché · ${s.source}`,
                    title: s.titre,
                    tag: `criticité ${formatNumber(s.criticite)}`,
                    tagVariant: s.criticite >= 70 ? ("r" as const) : ("w" as const),
                    body: [
                      s.so_what || "Aucune lecture commerciale n'a encore été rédigée pour ce signal.",
                      s.action ? `Action suggérée : ${s.action}` : "",
                      s.risque ? `Risque identifié : ${s.risque}` : "",
                      s.publie_le
                        ? `Publié le ${formatDate(s.publie_le)}.`
                        : "La source ne remonte pas de date de publication : seule la date de détection est connue, l'ancienneté réelle du signal ne l'est pas.",
                    ].filter(Boolean),
                    kv: [
                      ["Source", s.source],
                      ["Pays", s.pays || "—"],
                      ["Criticité", formatNumber(s.criticite)],
                      ["Détecté le", formatDate(s.detecte_le)],
                      ["Offre associée", s.offre || "—"],
                      ["Lien", s.url || "—"],
                    ],
                  },
                }))}
              />
            </>
          ) : (
            <Note style={{ marginTop: 0 }}>
              Aucun signal exploitable dans la veille : {formatNumber(veille.qualite.nb_total)} entrées
              collectées, aucune ne portant de lien utilisable.
            </Note>
          )}
          <Note style={{ marginTop: 14 }}>{veille.note}</Note>
        </Tile>
      </Bento>
    </>
  );
}
