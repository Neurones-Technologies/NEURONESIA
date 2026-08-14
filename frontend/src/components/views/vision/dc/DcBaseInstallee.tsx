import { getCrossSellAnalysis, getCrossSellSignals } from "@/lib/api/crosssell";
import { getAccountActivity } from "@/lib/api/dashboard";
import { formatDate, formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, HintLine, Lst, Reste, Tile } from "@/components/ui/bento";
import { AnalysisSlot } from "@/components/ui/analysis-slot";
import { Note } from "@/components/ui/primitives";
import { DORMANCE_TAG, DORMANCE_VARIANT } from "./shared";

/** Onglet « Base installée » : l'état du portefeuille par ancienneté de commande,
 * les comptes qui viennent de décrocher, et le ciblage cross-sell. */
export async function DcBaseInstallee() {
  const [dormance, crosssell] = await Promise.all([getAccountActivity(), getCrossSellSignals()]);

  // L'ordre des segments vient du backend (Actif → Prospect) et ne doit PAS être
  // retrié : c'est une progression d'ancienneté, pas un classement par volume.
  const dormanceSegments = dormance.segments.filter((s) => s.nb_comptes > 0);
  const topSegmentNb = Math.max(...dormanceSegments.map((s) => s.nb_comptes), 1);

  if (dormanceSegments.length === 0) {
    return (
      <Bento>
        <Tile span={12} title="État du portefeuille par ancienneté de commande">
          <Note style={{ marginTop: 0 }}>
            Aucun compte exploitable dans le miroir pour segmenter le portefeuille par ancienneté de
            commande.
          </Note>
        </Tile>
      </Bento>
    );
  }

  return (
    <Bento>
      <Tile
        span={7}
        title="État du portefeuille par ancienneté de commande"
        kick={`au ${formatDate(dormance.as_of)} · seuil dormant ${dormance.seuils_mois.ralentit} mois`}
      >
        <HintLine>Cliquez un segment pour ses comptes</HintLine>
        <Bars
          rows={dormanceSegments.map((s) => {
            const marqueurs = [
              s.nb_avec_impaye > 0 ? `${formatNumber(s.nb_avec_impaye)} avec impayé` : null,
              s.nb_avec_opp_ouverte > 0 ? `${formatNumber(s.nb_avec_opp_ouverte)} avec pipe ouvert` : null,
            ].filter(Boolean);
            return {
              name: s.label,
              sub: [
                s.borne,
                s.ca_historique_xof > 0 ? `${formatMFcfa(s.ca_historique_xof)} M historiques` : null,
                ...marqueurs,
              ]
                .filter(Boolean)
                .join(" · "),
              value: formatNumber(s.nb_comptes),
              pct: topSegmentNb ? (s.nb_comptes / topSegmentNb) * 100 : 0,
              variant: DORMANCE_VARIANT[s.segment],
              detail: {
                kicker: `Segment · ${s.borne}`,
                title: `${s.label} — ${formatNumber(s.nb_comptes)} comptes`,
                tag: `${formatPct(s.part_nb_pct, 0)} % du portefeuille`,
                tagVariant: DORMANCE_TAG[s.segment],
                body: [
                  s.segment === "prospect"
                    ? `${formatNumber(s.nb_comptes)} comptes du référentiel n'ont jamais passé de commande. Ce ne sont pas des clients perdus mais des prospects : ${formatNumber(s.nb_avec_opp_ouverte)} d'entre eux portent déjà des opportunités ouvertes pour ${formatMFcfa(s.pipe_ouvert_xof)} M FCFA.`
                    : `${formatNumber(s.nb_comptes)} comptes n'ont pas commandé depuis ${s.borne}, pour ${formatMFcfa(s.ca_historique_xof)} M FCFA de chiffre d'affaires historique cumulé (${formatPct(s.part_ca_pct, 0)} % du total). Silence médian du segment : ${s.silence_median_mois ?? "—"} mois.`,
                  s.nb_avec_opp_ouverte > 0 && s.segment !== "prospect"
                    ? `${formatNumber(s.nb_avec_opp_ouverte)} de ces comptes portent des opportunités ouvertes pour ${formatMFcfa(s.pipe_ouvert_xof)} M FCFA. Le silence se mesurant sur les commandes signées, un compte peut apparaître ici tout en faisant l'objet d'un travail commercial en cours.`
                    : null,
                  s.nb_avec_impaye > 0
                    ? `${formatNumber(s.nb_avec_impaye)} comptes de ce segment portent un impayé échu, pour ${formatMFcfa(s.impaye_xof)} M FCFA. À traiter avec la Direction Financière avant toute relance.`
                    : null,
                ].filter((l): l is string => Boolean(l)),
                kv: [
                  ["Comptes", formatNumber(s.nb_comptes)],
                  ["Part du portefeuille", `${formatPct(s.part_nb_pct, 0)} %`],
                  ["CA historique", `${formatMFcfa(s.ca_historique_xof)} M FCFA`],
                  ["Silence médian", s.silence_median_mois !== null ? `${s.silence_median_mois} mois` : "—"],
                  ["Avec impayé échu", formatNumber(s.nb_avec_impaye)],
                  ["Avec pipe ouvert", formatNumber(s.nb_avec_opp_ouverte)],
                  ...s.comptes
                    .slice(0, 6)
                    .map(
                      (c) =>
                        [
                          c.compte,
                          `${formatMFcfa(c.ca_total_xof)} M${c.mois_silence !== null ? ` · ${c.mois_silence} mois` : ""}${c.alerte_impaye ? " · impayé" : ""}`,
                        ] as [string, string],
                    ),
                ],
                // note: "Segmentation absolue sur l'ancienneté de commande, distincte de la « rupture de rythme » du briefing DG qui compare chaque compte à son propre intervalle médian.",
              },
            };
          })}
        />
        <Note style={{ marginTop: 14 }}>
          Le silence se mesure sur les commandes signées, pas sur les opportunités : un compte peut
          apparaître dormant tout en faisant l&apos;objet d&apos;un travail commercial en cours. Les{" "}
          {formatNumber(dormance.totaux.nb_prospects)}{" "}
          prospects n&apos;ont jamais commandé — ce ne sont pas des clients perdus.
          {dormance.qualite_donnees.nb_hors_referentiel > 0 &&
            ` ${formatNumber(dormance.qualite_donnees.nb_hors_referentiel)} comptes ont commandé (${formatMFcfa(dormance.qualite_donnees.ca_hors_referentiel_xof)} M FCFA) sans exister dans le référentiel clients d'Odoo.`}
        </Note>
      </Tile>

      {dormance.decrochages.length > 0 && (
        <Tile span={5} title="Comptes qui viennent de décrocher" kick="par CA historique">
          <HintLine>Cliquez un compte pour son historique</HintLine>
          <Lst
            items={dormance.decrochages.slice(0, 6).map((c) => ({
              title: c.compte,
              sub: `${c.mois_silence} mois sans commande · ${formatMFcfa(c.ca_total_xof)} M historiques${c.nb_opp_ouvertes > 0 ? ` · ${formatNumber(c.nb_opp_ouvertes)} opportunités ouvertes` : ""}`,
              tag: c.alerte_impaye ? `${formatMFcfa(c.impaye_xof)} M impayés` : c.label,
              tagVariant: c.alerte_impaye ? ("r" as const) : ("w" as const),
              detail: {
                kicker: `Compte · ${c.label.toLowerCase()}`,
                title: c.compte,
                tag: `${c.mois_silence} mois de silence`,
                tagVariant: c.alerte_impaye ? ("r" as const) : ("w" as const),
                body: [
                  `Dernière commande le ${formatDate(c.derniere_commande)}, soit ${c.mois_silence} mois. Ce compte a généré ${formatMFcfa(c.ca_total_xof)} M FCFA sur ${formatNumber(c.nb_commandes)} commandes depuis le début de la relation.`,
                  c.nb_opp_ouvertes > 0
                    ? `Il porte ${formatNumber(c.nb_opp_ouvertes)} opportunités ouvertes pour ${formatMFcfa(c.opp_ouvertes_xof)} M FCFA : il y a du travail commercial en cours, mais aucune commande signée depuis ${c.mois_silence} mois.`
                    : "Aucune opportunité ouverte sur ce compte : le silence est total, côté commande comme côté pipeline.",
                  c.alerte_impaye
                    ? `Ce compte porte ${formatMFcfa(c.impaye_xof)} M FCFA d'impayé échu, avec un retard maximum de ${formatNumber(c.retard_max_jours)} jours. Une relance commerciale se coordonne avec la Direction Financière — le détail des factures relève de son périmètre.`
                    : "Aucun impayé échu sur ce compte.",
                  c.hors_referentiel
                    ? "Ce compte n'existe pas dans le référentiel clients d'Odoo alors qu'il a passé des commandes : anomalie de synchronisation à faire corriger."
                    : null,
                ].filter((l): l is string => Boolean(l)),
                kv: [
                  ["Segment", c.label],
                  ["Dernière commande", formatDate(c.derniere_commande)],
                  ["Silence", `${c.mois_silence} mois`],
                  ["CA historique", `${formatMFcfa(c.ca_total_xof)} M FCFA`],
                  ["Commandes", formatNumber(c.nb_commandes)],
                  ["Commercial rattaché", c.commercial || "non renseigné"],
                  ["Pipe ouvert", c.nb_opp_ouvertes > 0 ? `${formatMFcfa(c.opp_ouvertes_xof)} M FCFA` : "—"],
                  ["Impayé échu", c.alerte_impaye ? `${formatMFcfa(c.impaye_xof)} M FCFA` : "—"],
                ],
                // note: "Commercial repris de la dernière commande du compte. Le référentiel commercial d'Odoo est en texte libre, sans notion d'équipe.",
              },
            }))}
          />
          <Reste
            affiches={Math.min(6, dormance.decrochages.length)}
            total={dormance.decrochages.length}
            nom="comptes décrochés"
          />
        </Tile>
      )}

      <Tile span={12} title="Ciblage cross-sell et renouvellement" kick="M1 · narration">
        <AnalysisSlot load={getCrossSellAnalysis} pliable titrePli="Lire l'analyse du ciblage" />
        {crosssell && (
          <div style={{ marginTop: 18 }}>
            <HintLine>Cliquez un compte pour le signal détaillé</HintLine>
            <Lst
              items={[
                ...crosssell.renouvellement.slice(0, 3).map((it) => ({
                  title: it.client,
                  sub: it.detail,
                  tag: it.titre,
                  tagVariant: "w" as const,
                  detail: {
                    kicker: "Signal · renouvellement probable",
                    title: it.client,
                    tag: it.titre,
                    tagVariant: "w" as const,
                    body: [it.detail, `Montant historique associé : ${formatMFcfa(it.montant_xof)} M FCFA.`],
                    kv: [
                      ["Montant", `${formatMFcfa(it.montant_xof)} M FCFA`],
                      ["Type de signal", it.titre],
                    ],
                    // note: "Signal calculé sur les lignes de commande réelles (catégories déjà achetées et ancienneté).",
                  },
                })),
                ...[...crosssell.cross_sell, ...crosssell.up_sell]
                  .sort((a, b) => b.montant_xof - a.montant_xof)
                  .slice(0, 3)
                  .map((it) => ({
                    title: it.client,
                    sub: it.detail,
                    tag: it.titre,
                    tagVariant: "a" as const,
                    detail: {
                      kicker: "Signal · vente additionnelle",
                      title: it.client,
                      tag: it.titre,
                      tagVariant: "a" as const,
                      body: [it.detail, `Montant historique associé : ${formatMFcfa(it.montant_xof)} M FCFA.`],
                      kv: [
                        ["Montant", `${formatMFcfa(it.montant_xof)} M FCFA`],
                        ["Type de signal", it.titre],
                      ],
                      // note: "Comparaison de catégories achetées entre comptes de profil voisin, sur les commandes réelles.",
                    },
                  })),
              ]}
            />
          </div>
        )}
      </Tile>
    </Bento>
  );
}
