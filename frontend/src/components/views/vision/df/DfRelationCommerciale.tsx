import { getRelationCommerciale, MauvaisPayeur } from "@/lib/api/daf";
import { formatDate, formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, HintLine, StatTile, Tile } from "@/components/ui/bento";
import { Clickable } from "@/components/ui/detail";
import { Note, Tag } from "@/components/ui/primitives";
import { ChartNote, LineChart, StackedAreaChart } from "@/components/ui/chart";
import { RAMPE_AGE, SERIE_1 } from "@/components/ui/chart-palette";
import { Variant } from "@/lib/types";
import { SourceNote, sourceKick } from "../dc/source";
import { ExerciceNav } from "./exercice-nav";
import { ScreenNotes } from "@/components/ui/screen-notes";
import { ScreenLede } from "@/components/ui/screen-lede";

/** Tableau de bord n°2 du DAF — Relation commerciale.
 *
 * « Point sur les créances : DSO. Point sur les dettes : DPO. Suivi des mauvais
 * clients (retard de paiement). »
 *
 * L'écran est construit autour d'une asymétrie qu'il ne faut pas cacher : les
 * créances sont mesurées ligne à ligne, les dettes ne le sont pas du tout — aucune
 * facture fournisseur n'est synchronisée. Le DPO est donc affiché avec sa marque
 * de provenance et, à côté, ce qui est réellement mesurable (les achats engagés).
 *
 * Sur les créances, deux lectures du DSO sont servies séparément : le délai
 * constaté sur les factures réglées, et l'encours rapporté au chiffre d'affaires.
 * Elles diffèrent d'un facteur six sur ces données, et cet écart n'est pas une
 * anomalie de calcul — c'est la mesure du stock d'impayés anciens.
 */
const STATUT_TAG: Record<MauvaisPayeur["statut"], Variant> = {
  contentieux: "r",
  en_retard: "w",
  payeur_lent: "w",
  a_jour: "s",
};

const STATUT_LIBELLE: Record<MauvaisPayeur["statut"], string> = {
  contentieux: "contentieux",
  en_retard: "en retard",
  payeur_lent: "payeur lent",
  a_jour: "à jour",
};

export async function DfRelationCommerciale({ annee }: { annee?: number }) {
  const data = await getRelationCommerciale(annee);

  if (!data) {
    return (
      <Bento>
        <Tile span={12} title="Relation commerciale">
          <Note style={{ marginTop: 0 }}>
            Le suivi des créances et des dettes n&apos;est pas accessible depuis ce profil.
          </Note>
        </Tile>
      </Bento>
    );
  }

  const { dso, dpo, balance_agee: balance, mauvais_payeurs: payeurs, cycle_cash: cycle } = data;
  const { serie_encours: courbeEncours, serie_dso: courbeDso } = data;
  const evo = courbeEncours.evolution;
  const resumeDso = courbeDso.resume;
  const auDela = dso.delai_encaissement_moyen_jours !== null
    && dso.delai_encaissement_moyen_jours > dso.cible_dso_jours;
  const contentieux = balance.tranches.find((t) => t.code === "90_plus");

  return (
    <>
      <ExerciceNav basePath="/df/vision/relation-commerciale" annee={data.annee} annees={data.annees_disponibles} />

      <ScreenLede
        texte={
          `Les clients règlent en ${formatPct(dso.delai_encaissement_moyen_jours, 0)} jours en moyenne, ` +
          `pour une cible de ${formatNumber(dso.cible_dso_jours)} — ${auDela ? "au-delà" : "dans la cible"}. ` +
          `${formatNumber(payeurs.totaux.nb_clients_a_risque)} clients sur ${formatNumber(payeurs.totaux.nb_clients_factures)} concentrent le risque de recouvrement.`
        }
        signaux={[
          {
            label: `DSO ${formatPct(dso.delai_encaissement_moyen_jours, 0)} j vs cible ${formatNumber(dso.cible_dso_jours)} j`,
            alerte: auDela,
          },
          {
            label: `${formatPct(contentieux?.part_pct ?? null, 0)} % de l'encours au-delà de 90 j`,
            alerte: (contentieux?.part_pct ?? 0) > 50,
          },
          { label: `recouvrement ${formatPct(dso.taux_recouvrement_pct, 0)} %` },
          {
            label: dpo.source === "reel" ? `DPO ${formatPct(dpo.dpo_jours, 0)} j` : "DPO non mesurable",
            alerte: dpo.source !== "reel",
          },
        ]}
      />

      <ScreenNotes
        notes={[
          dso.note,
          dpo.note,
          // Même phrase que la note de pied précédente, composée en chaîne : le
          // panneau prend des textes, pas du JSX.
          `Couverture de la mesure : ${formatNumber(dso.couverture.nb_reglees_datees)} factures portent une date de règlement sur ${formatNumber(dso.couverture.nb_factures)} (${formatPct(dso.couverture.part_datee_pct, 1)} %).${
            balance.nb_sans_echeance > 0
              ? ` ${formatNumber(balance.nb_sans_echeance)} facture(s) ouverte(s) n'ont pas d'échéance exploitable (${formatMFcfa(balance.montant_sans_echeance_xof)} M FCFA) : elles sortent de la balance âgée.`
              : ""
          }`,
        ]}
      />

      <div className="kpi-row">
        <StatTile
          span={3}
          rang="principal"
          label="DSO constaté"
          value={formatPct(dso.delai_encaissement_moyen_jours, 0)}
          unit="jours"
          reading={`cible ${formatNumber(dso.cible_dso_jours)} j · médiane ${formatPct(dso.delai_encaissement_median_jours, 0)} j`}
          readingVariant={auDela ? "neg" : "pos"}
          detail={{
            kicker: "Indicateur · délai mesuré",
            title: "Délai d'encaissement constaté",
            tag: auDela ? "au-delà de la cible" : "dans la cible",
            tagVariant: auDela ? "r" : "s",
            body: [
              `Mesuré sur ${formatNumber(dso.couverture.nb_delais_mesures)} factures effectivement réglées : ${formatPct(dso.delai_encaissement_moyen_jours, 1)} jours en moyenne entre l'émission de la facture et son règlement, ${formatPct(dso.delai_encaissement_median_jours, 0)} jours en médiane.`,
              `Le retard par rapport à l'échéance, lui, ressort à ${formatPct(dso.retard_moyen_jours, 1)} jours : l'écart entre les deux est le délai contractuel accordé aux clients.`,
              dso.note,
            ],
            kv: [
              ["Délai moyen", `${formatPct(dso.delai_encaissement_moyen_jours, 1)} j`],
              ["Délai médian", `${formatPct(dso.delai_encaissement_median_jours, 0)} j`],
              ["Retard moyen après échéance", `${formatPct(dso.retard_moyen_jours, 1)} j`],
              ["Cible", `${formatNumber(dso.cible_dso_jours)} j`],
              ["Factures mesurées", formatNumber(dso.couverture.nb_delais_mesures)],
            ],
          }}
        />
        <StatTile
          span={3}
          label="DSO sur encours"
          value={formatNumber(dso.dso_encours_jours ?? 0)}
          unit="jours de CA"
          reading={
            dso.ecart_lectures_jours !== null
              ? `+${formatPct(dso.ecart_lectures_jours, 0)} j vs délai constaté`
              : "lecture bilancielle"
          }
          readingVariant="neg"
          detail={{
            kicker: "Indicateur · lecture bilancielle",
            title: "Encours rapporté au chiffre d'affaires",
            tag: "stock d'impayés",
            tagVariant: "r",
            body: [
              `${formatMFcfa(dso.encours_xof)} M FCFA d'encours client pour ${formatMFcfa(dso.ca_exercice_xof)} M FCFA de CA sur l'exercice, soit ${formatNumber(dso.dso_encours_jours ?? 0)} jours de chiffre d'affaires immobilisés.`,
              `Cette lecture est bien plus élevée que le délai constaté (${formatPct(dso.delai_encaissement_moyen_jours, 0)} j) parce qu'elle inclut les factures anciennes JAMAIS réglées, que le délai constaté ne peut pas voir : il ne se calcule que sur ce qui a été payé.`,
              "L'écart entre les deux lectures est donc la mesure du stock d'impayés, pas une incohérence de calcul.",
            ],
            kv: [
              ["Encours total", `${formatMFcfa(dso.encours_xof)} M FCFA`],
              ["Dont échu", `${formatMFcfa(dso.encours_echu_xof)} M FCFA`],
              ["CA de l'exercice", `${formatMFcfa(dso.ca_exercice_xof)} M FCFA`],
              ["Jours de CA immobilisés", formatNumber(dso.dso_encours_jours ?? 0)],
              ["Taux de recouvrement", `${formatPct(dso.taux_recouvrement_pct, 1)} %`],
            ],
          }}
        />
        {/* Le DPO recule d'un plan tant qu'aucune facture fournisseur n'est
            synchronisée : la valeur affichée est posée, pas mesurée. Le rang suit
            la source — le jour où les dettes arrivent, l'indicateur reprend sa
            place sans modification d'écran. */}
        <StatTile
          span={3}
          rang={dpo.source === "reel" ? "secondaire" : "contexte"}
          label="DPO"
          value={formatPct(dpo.dpo_jours, 0)}
          unit="jours"
          reading={dpo.source === "reel" ? "mesuré" : "gabarit · dettes non synchronisées"}
          readingVariant={dpo.source === "reel" ? undefined : "wat"}
          detail={{
            kicker: dpo.source === "reel" ? "Indicateur · délai mesuré" : "Gabarit · non mesurable",
            title: "Délai de paiement fournisseurs",
            tag: dpo.source === "reel" ? "mesuré" : "posé",
            tagVariant: dpo.source === "reel" ? "s" : "w",
            body: [
              dpo.source === "reel"
                ? `Délai moyen de ${formatPct(dpo.dpo_jours, 1)} jours entre la facture fournisseur et son règlement, sur ${formatNumber(dpo.nb_factures_fournisseurs)} factures.`
                : `Aucune facture fournisseur n'est synchronisée : le DPO affiché est posé. Ce qui est mesuré, ce sont ${formatMFcfa(dpo.base_mesuree.achats_engages_exercice_xof)} M FCFA d'achats ENGAGÉS sur ${formatNumber(dpo.base_mesuree.nb_commandes_exercice)} commandes auprès de ${formatNumber(dpo.base_mesuree.nb_fournisseurs_exercice)} fournisseurs.`,
              dpo.raison ?? dpo.note,
              dpo.source === "reel" ? dpo.note : "Une commande passée n'est pas une dette échue : entre les deux, il manque la facture, son échéance et son règlement.",
            ],
            kv: [
              ["DPO", `${formatPct(dpo.dpo_jours, 1)} j`],
              [
                "Délai négocié moyen",
                dpo.base_mesuree.delai_negocie_moyen_jours !== null
                  ? `${formatPct(dpo.base_mesuree.delai_negocie_moyen_jours, 0)} j`
                  : `non renseigné (${formatNumber(dpo.base_mesuree.nb_fiches_fournisseur)} fiches fournisseur)`,
              ],
              ["Achats engagés (mesuré)", `${formatMFcfa(dpo.base_mesuree.achats_engages_exercice_xof)} M FCFA`],
              ["Commandes d'achat", formatNumber(dpo.base_mesuree.nb_commandes_exercice)],
              ["Factures fournisseurs", formatNumber(dpo.nb_factures_fournisseurs)],
            ],
          }}
        />
        <StatTile
          span={3}
          label="Clients à risque"
          value={formatNumber(payeurs.totaux.nb_clients_a_risque)}
          unit={`sur ${formatNumber(payeurs.totaux.nb_clients_factures)}`}
          reading={`dont ${formatNumber(payeurs.totaux.nb_contentieux)} en contentieux`}
          readingVariant="neg"
          detail={{
            kicker: "Indicateur · suivi des mauvais payeurs",
            title: "Clients portant un signal de paiement",
            tag: `${formatNumber(payeurs.totaux.nb_contentieux)} contentieux`,
            tagVariant: "r",
            body: [
              `${formatNumber(payeurs.totaux.nb_clients_a_risque)} clients sur ${formatNumber(payeurs.totaux.nb_clients_factures)} portent un encours échu ou un comportement de paiement lent, pour ${formatMFcfa(payeurs.totaux.encours_echu_total_xof)} M FCFA d'encours échu au total.`,
              `${formatNumber(payeurs.totaux.nb_clients_arriere_ancien)} d'entre eux portent une créance de plus de deux ans (${formatMFcfa(payeurs.totaux.encours_arriere_ancien_xof)} M FCFA) : à cette ancienneté, la question n'est plus de relancer mais de provisionner.`,
              payeurs.note,
            ],
            kv: [
              ["Clients facturés", formatNumber(payeurs.totaux.nb_clients_factures)],
              ["Clients à risque", formatNumber(payeurs.totaux.nb_clients_a_risque)],
              ["En contentieux", formatNumber(payeurs.totaux.nb_contentieux)],
              ["Payeurs lents", formatNumber(payeurs.totaux.nb_payeurs_lents)],
              ["Arriéré de plus de 2 ans", `${formatMFcfa(payeurs.totaux.encours_arriere_ancien_xof)} M FCFA`],
              ["Concentration top 5", `${formatPct(payeurs.totaux.part_top5_encours_echu_pct, 1)} %`],
            ],
          }}
        />
      </div>

      <Bento>
        <Tile
          span={7}
          title="Où va l'encours client"
          kick={`${formatNumber(courbeEncours.profondeur_mois)} mois · par ancienneté`}
        >
          <StackedAreaChart
            abscisses={courbeEncours.points.map((p) => p.libelle)}
            series={courbeEncours.tranches.map((t, i) => ({
              cle: t.code,
              libelle: t.libelle,
              couleur: RAMPE_AGE[i] ?? RAMPE_AGE[RAMPE_AGE.length - 1],
              valeurs: courbeEncours.points.map(
                (p) => p.tranches.find((x) => x.code === t.code)?.montant_xof ?? 0,
              ),
            }))}
            formatY={(v) => `${formatMFcfa(v)} M`}
            infos={courbeEncours.points.map((p) => {
              const detail = p.tranches
                .filter((t) => t.montant_xof > 0)
                .map((t) => `${t.libelle} ${formatMFcfa(t.montant_xof)} M`)
                .join(" · ");
              return `${p.libelle} — encours ${formatMFcfa(p.total_xof)} M sur ${formatNumber(p.nb_factures)} factures. ${detail}`;
            })}
          />
          <ChartNote>
            {formatMFcfa(evo.encours_debut_xof)} M en {courbeEncours.points[0]?.libelle ?? evo.depuis} →{" "}
            {formatMFcfa(evo.encours_fin_xof)} M aujourd&apos;hui, soit{" "}
            {evo.variation_pct > 0 ? "+" : ""}
            {formatPct(evo.variation_pct, 0)} %. La part au-delà de 90 jours passe de{" "}
            {formatPct(evo.part_contentieux_debut_pct, 0)} % à {formatPct(evo.part_contentieux_fin_pct, 0)} %.
          </ChartNote>
          <Note accent style={{ marginTop: 12 }}>
            {courbeEncours.limite}
          </Note>
        </Tile>

        <Tile
          span={5}
          title="Délai d'encaissement dans le temps"
          kick={`moyenne glissante ${formatNumber(courbeDso.fenetre_mois)} mois`}
        >
          <LineChart
            series={[
              {
                cle: "dso",
                libelle: "Délai constaté",
                couleur: SERIE_1,
                aire: true,
                etiquetteFin:
                  resumeDso.delai_fin_jours !== null ? `${formatPct(resumeDso.delai_fin_jours, 0)} j` : undefined,
                points: courbeDso.points.map((p) => ({
                  x: p.libelle,
                  y: p.delai_moyen_jours,
                  fiable: !p.synchronisation_incomplete,
                  info: `${p.libelle} — ${
                    p.delai_moyen_jours !== null ? `${formatPct(p.delai_moyen_jours, 1)} jours` : "non publié"
                  }, sur ${formatNumber(p.nb_reglements_fenetre)} règlements de la fenêtre · ${formatMFcfa(p.montant_encaisse_mois_xof)} M encaissés ce mois${
                    p.synchronisation_incomplete ? " · synchronisation incomplète" : ""
                  }`,
                })),
              },
            ]}
            formatY={(v) => `${Math.round(v)} j`}
            reference={{ valeur: courbeDso.cible_jours, libelle: `cible ${courbeDso.cible_jours} j` }}
          />
          <ChartNote>
            Dernier mois fiable : {resumeDso.dernier_mois_fiable ?? "—"} à{" "}
            {formatPct(resumeDso.delai_fin_jours, 0)} j, soit{" "}
            {(resumeDso.ecart_cible_jours ?? 0) > 0 ? "+" : ""}
            {formatPct(resumeDso.ecart_cible_jours, 0)} j par rapport à la cible.{" "}
            {resumeDso.nb_mois_synchronisation_incomplete > 0
              ? `Les ${formatNumber(resumeDso.nb_mois_synchronisation_incomplete)} derniers mois sont en pointillé : trop peu de règlements y sont rapatriés pour que le délai s'y lise.`
              : ""}
          </ChartNote>
        </Tile>

        <Tile span={12} title="Suivi des mauvais payeurs" kick={`${formatNumber(payeurs.clients.length)} clients classés par risque`}>
          <HintLine>Cliquez un client pour son comportement de paiement et son exposition</HintLine>
          <div style={{ overflowX: "auto" }}>
            <table className="tb">
              <thead>
                <tr>
                  <th>Client</th>
                  <th className="r">Encours échu</th>
                  <th className="r">Retard courant</th>
                  <th className="r">Retard habituel</th>
                  <th className="r">Indice</th>
                  <th>Statut</th>
                </tr>
              </thead>
              <tbody>
                {payeurs.clients.map((c) => (
                  <Clickable
                    key={`${c.client_id ?? c.client}`}
                    as="tr"
                    detail={{
                      kicker: "Client · risque de paiement",
                      title: c.client,
                      tag: STATUT_LIBELLE[c.statut],
                      tagVariant: STATUT_TAG[c.statut],
                      body: [
                        `${formatMFcfa(c.encours_echu_xof)} M FCFA d'encours échu sur ${formatNumber(c.nb_factures_ouvertes)} facture(s) ouverte(s), avec un retard courant maximal de ${formatNumber(c.retard_courant_max_jours)} jours (échéance la plus ancienne : ${formatDate(c.echeance_la_plus_ancienne)}).`,
                        c.comportement_significatif
                          ? `Son comportement de paiement est mesuré sur ${formatNumber(c.nb_factures_reglees)} factures réglées : ${formatPct(c.retard_moyen_regle_jours, 1)} jours de retard en moyenne. C'est un payeur ${(c.retard_moyen_regle_jours ?? 0) > 30 ? "structurellement lent" : "globalement fiable"}.`
                          : `Il n'a réglé que ${formatNumber(c.nb_factures_reglees)} facture(s) : son retard moyen est affiché mais n'entre pas dans l'indice — sur si peu de factures, un retard est un incident, pas un comportement.`,
                        c.retard_courant_max_jours > 2 * 365
                          ? "Cette créance dépasse deux ans. À cette ancienneté, la relance n'est plus l'outil : la question est celle de la provision ou du passage en perte."
                          : c.retard_courant_max_jours > payeurs.regle.seuil_contentieux_jours
                            ? "Au-delà de 90 jours, la relance commerciale simple a généralement déjà échoué : l'escalade se décide (mise en demeure, blocage des livraisons, étalement négocié)."
                            : "Le retard reste dans une zone où une relance ferme suffit habituellement.",
                        c.client_connu ? "" : "Ce client n'existe pas dans le référentiel : la facture est rattachée à un tiers supprimé ou hors périmètre. À corriger dans l'ERP.",
                      ].filter(Boolean),
                      kv: [
                        ["Encours échu", `${formatMFcfa(c.encours_echu_xof)} M FCFA`],
                        ["Encours total", `${formatMFcfa(c.encours_xof)} M FCFA`],
                        ["Factures ouvertes", formatNumber(c.nb_factures_ouvertes)],
                        ["Retard courant max", `${formatNumber(c.retard_courant_max_jours)} j`],
                        [
                          "Retard habituel",
                          c.retard_moyen_regle_jours !== null
                            ? `${formatPct(c.retard_moyen_regle_jours, 1)} j sur ${formatNumber(c.nb_factures_reglees)} factures`
                            : "aucune facture réglée",
                        ],
                        ["Part de l'encours échu", `${formatPct(c.part_encours_echu_pct, 1)} %`],
                        ["Indice de risque", formatPct(c.indice_risque, 1)],
                        ["Total facturé", `${formatMFcfa(c.montant_facture_xof)} M FCFA`],
                      ],
                    }}
                  >
                    <td>{c.client}</td>
                    <td className="r mono">{formatMFcfa(c.encours_echu_xof)} M</td>
                    <td className="r mono">{formatNumber(c.retard_courant_max_jours)} j</td>
                    <td className="r mono">
                      {c.retard_moyen_regle_jours !== null
                        ? `${formatPct(c.retard_moyen_regle_jours, 0)} j${c.comportement_significatif ? "" : " *"}`
                        : "—"}
                    </td>
                    <td className="r mono">{formatPct(c.indice_risque, 0)}</td>
                    <td>
                      <Tag variant={STATUT_TAG[c.statut]}>{STATUT_LIBELLE[c.statut]}</Tag>
                    </td>
                  </Clickable>
                ))}
              </tbody>
            </table>
          </div>
          <Note style={{ marginTop: 14 }}>
            Indice de risque : {payeurs.regle.composantes}. Un retard habituel suivi d&apos;un
            astérisque est calculé sur moins de {formatNumber(payeurs.regle.min_factures_comportement)}{" "}
            factures réglées — affiché, mais non retenu dans l&apos;indice.
          </Note>
        </Tile>

        <Tile span={4} title="Balance âgée des créances" kick={`${formatMFcfa(balance.total_xof)} M FCFA d'encours`}>
          <Bars
            rows={balance.tranches.map((t) => ({
              name: t.libelle,
              sub: `${formatNumber(t.nb_factures ?? 0)} facture(s) · ${formatPct(t.part_pct, 1)} % de l'encours`,
              value: `${formatMFcfa(t.montant_xof)} M`,
              pct: t.part_pct,
              variant:
                t.code === "90_plus" ? ("r" as const) : t.code === "non_echu" ? ("s" as const) : ("w" as const),
              detail: {
                kicker: "Tranche d'ancienneté · mesurée",
                title: t.libelle,
                tag: `${formatPct(t.part_pct, 1)} % de l'encours`,
                tagVariant: t.code === "90_plus" ? "r" : t.code === "non_echu" ? "s" : "w",
                body: [
                  `${formatMFcfa(t.montant_xof)} M FCFA restant dus sur ${formatNumber(t.nb_factures ?? 0)} facture(s) dans cette tranche.`,
                  t.code === "90_plus"
                    ? "Au-delà de 90 jours, le recouvrement amiable a rarement encore prise. C'est la tranche qui détermine le besoin de provision."
                    : t.code === "non_echu"
                      ? "Cette part n'est pas en retard : elle ne doit pas être comptée comme un défaut de recouvrement."
                      : "Tranche encore récupérable par relance commerciale ferme.",
                  balance.note,
                ],
                kv: [
                  ["Montant restant dû", `${formatMFcfa(t.montant_xof)} M FCFA`],
                  ["Factures", formatNumber(t.nb_factures ?? 0)],
                  ["Part de l'encours", `${formatPct(t.part_pct, 1)} %`],
                ],
              },
            }))}
          />
          {contentieux && contentieux.part_pct > 50 && (
            <Note accent style={{ marginTop: 14 }}>
              {formatPct(contentieux.part_pct, 0)} % de l&apos;encours client dépasse 90 jours de retard, soit{" "}
              {formatMFcfa(contentieux.montant_xof)} M FCFA sur {formatNumber(contentieux.nb_factures ?? 0)}{" "}
              factures. À ce niveau, le sujet n&apos;est plus le délai de paiement mais l&apos;assainissement du
              poste client.
            </Note>
          )}
        </Tile>

        <Tile
          span={4}
          title="Dette fournisseurs par ancienneté"
          kick={sourceKick(dpo.source, `${formatMFcfa(dpo.dette_xof)} M FCFA`)}
        >
          <Bars
            rows={dpo.tranches.map((t) => ({
              name: t.libelle,
              sub:
                t.nb_factures !== null
                  ? `${formatNumber(t.nb_factures)} facture(s) · ${formatPct(t.part_pct, 1)} %`
                  : `${formatPct(t.part_pct, 1)} % de la dette posée`,
              value: `${formatMFcfa(t.montant_xof)} M`,
              pct: t.part_pct,
              variant: t.code === "90_plus" ? ("r" as const) : t.code === "non_echu" ? ("s" as const) : ("w" as const),
            }))}
          />
          <SourceNote source={dpo.source} raison={dpo.raison} avertissement={dpo.avertissement} />
        </Tile>

        <Tile span={4} title="Cycle de cash" kick={sourceKick(cycle.source, "DSO contre DPO")}>
          <Bars
            rows={[
              {
                name: "Délai d'encaissement client (DSO)",
                sub: "mesuré sur les factures réglées",
                value: `${formatPct(cycle.dso_jours, 0)} j`,
                pct: 100,
                variant: "r" as const,
              },
              {
                name: "Délai de paiement fournisseur (DPO)",
                sub: dpo.source === "reel" ? "mesuré" : "posé faute de factures fournisseurs",
                value: `${formatPct(cycle.dpo_jours, 0)} j`,
                pct:
                  cycle.dso_jours && cycle.dpo_jours
                    ? Math.min(100, (cycle.dpo_jours / cycle.dso_jours) * 100)
                    : 0,
                variant: dpo.source === "reel" ? ("s" as const) : ("w" as const),
              },
            ]}
          />
          <Note style={{ marginTop: 14 }}>
            {cycle.ecart_jours !== null
              ? `Écart de ${formatPct(cycle.ecart_jours, 0)} jours. ${cycle.lecture}`
              : cycle.lecture}
          </Note>
          <SourceNote
            source={cycle.source}
            raison={cycle.fiabilite}
            avertissement={dpo.source === "reel" ? null : dpo.avertissement}
          />
        </Tile>

      </Bento>
    </>
  );
}
