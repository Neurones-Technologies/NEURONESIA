import { getBriefing } from "@/lib/api/briefing";
import { getDso, getMargins, getMarginsAnalysis, getUnpaid, getUnpaidAnalysis } from "@/lib/api/dashboard";
import { formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, Brief, FootNote, HintLine, StatTile, Tile } from "@/components/ui/bento";
import { Clickable } from "@/components/ui/detail";
import { AnalysisNarr, Note, Tag } from "@/components/ui/primitives";

export async function DfVision() {
  const [dso, unpaid, margins, unpaidAnalysis, marginsAnalysis, briefing] = await Promise.all([
    getDso(),
    getUnpaid(15),
    getMargins(),
    getUnpaidAnalysis(),
    getMarginsAnalysis(),
    getBriefing(),
  ]);

  const briefLines = briefing?.section?.resume?.length
    ? briefing.section.resume
    : (briefing?.section?.bullets ?? []).slice(0, 5);

  const topDebtors = (unpaid?.exposure.top_10_debiteurs ?? [])
    .slice()
    .sort((a, b) => b.retard_max_jours - a.retard_max_jours);
  const topInvoices = (unpaid?.top_invoices ?? []) as Array<Record<string, unknown>>;
  const totalTopInvoices = topInvoices.reduce((s, inv) => s + Number(inv.montant_xof ?? 0), 0);

  const exposition = unpaid?.exposure.exposition_totale_xof ?? 0;
  const retard90 = unpaid?.exposure.retard_90j_montant_xof ?? 0;
  const part90 = exposition ? (retard90 / exposition) * 100 : 0;
  const topDebtorAmount = topDebtors[0]?.montant_total_xof ?? 0;

  const ecartDelai =
    dso?.delai_moyen_recouvrement_reel_jours != null && dso?.delai_moyen_accorde_jours != null
      ? dso.delai_moyen_recouvrement_reel_jours - dso.delai_moyen_accorde_jours
      : null;

  const margeEcart = margins.stats.perc_marge_definitive_moyen - margins.stats.perc_marge_provisoire_moyen;

  return (
    <>
      <Brief
        kicker="Cash · encaissement et marge"
        headline={`${formatMFcfa(exposition)} M FCFA d'encours client, dont ${formatMFcfa(retard90)} M échus depuis plus de 90 jours.`}
        lines={briefLines}
        paragraphs={
          briefLines.length
            ? undefined
            : [
                `L'encours client atteint ${formatMFcfa(exposition)} M FCFA sur ${formatNumber(unpaid?.exposure.nb_factures_impayees ?? 0)} factures impayées. Le briefing du jour n'est pas encore généré pour ce profil.`,
              ]
        }
        pills={[
          { label: `${formatNumber(unpaid?.exposure.nb_factures_impayees ?? 0)} factures impayées` },
          { label: `${formatPct(part90, 0)} % de l'encours au-delà de 90 j`, hot: part90 > 30 },
          {
            label:
              dso?.delai_moyen_recouvrement_reel_jours != null
                ? `DSO réel ${formatNumber(dso.delai_moyen_recouvrement_reel_jours)} j`
                : `DSO approché ${formatNumber(dso?.dso_approx_jours ?? 0)} j`,
            hot: ecartDelai !== null && ecartDelai > 0,
          },
          { label: `Marge définitive ${formatPct(margins.stats.perc_marge_definitive_moyen)} %`, hot: margeEcart < 0 },
        ]}
      />

      <Bento>
        <StatTile
          span={4}
          label="Encours client"
          value={formatMFcfa(exposition)}
          unit="M FCFA"
          reading={`${formatNumber(unpaid?.exposure.nb_factures_impayees ?? 0)} factures impayées`}
          readingVariant="neg"
          detail={{
            kicker: "Indicateur · exposition",
            title: "Encours client impayé",
            tag: `${formatNumber(unpaid?.exposure.nb_factures_impayees ?? 0)} factures`,
            tagVariant: "r",
            body: [
              `L'encours total impayé s'élève à ${formatMFcfa(exposition)} M FCFA, réparti sur ${formatNumber(unpaid?.exposure.nb_factures_impayees ?? 0)} factures.`,
              `${formatMFcfa(retard90)} M FCFA, soit ${formatPct(part90, 0)} % de cet encours, sont échus depuis plus de 90 jours. Au-delà de ce seuil, le recouvrement amiable devient rarement suffisant.`,
            ],
            kv: [
              ["Encours total", `${formatMFcfa(exposition)} M FCFA`],
              ["Factures impayées", formatNumber(unpaid?.exposure.nb_factures_impayees ?? 0)],
              ["Échu > 90 jours", `${formatMFcfa(retard90)} M FCFA`],
              ["Part > 90 jours", `${formatPct(part90, 0)} %`],
            ],
            note: "Factures non réglées du miroir Odoo, hors litiges déclarés.",
          }}
        />
        <StatTile
          span={4}
          label={dso?.delai_moyen_recouvrement_reel_jours != null ? "DSO réel" : "DSO approché"}
          value={
            dso?.delai_moyen_recouvrement_reel_jours != null
              ? formatNumber(dso.delai_moyen_recouvrement_reel_jours)
              : formatNumber(dso?.dso_approx_jours ?? 0)
          }
          unit="jours"
          reading={
            ecartDelai !== null
              ? `${ecartDelai > 0 ? "+" : ""}${formatNumber(ecartDelai)} j vs délai accordé`
              : "approximation balance sheet"
          }
          readingVariant={ecartDelai !== null && ecartDelai > 0 ? "neg" : "wat"}
          detail={{
            kicker: "Indicateur · délai de règlement",
            title: "Délai moyen de recouvrement",
            tag: ecartDelai !== null && ecartDelai > 0 ? "au-delà du contractuel" : "à fiabiliser",
            tagVariant: ecartDelai !== null && ecartDelai > 0 ? "r" : "w",
            body: [
              dso?.delai_moyen_recouvrement_reel_jours != null
                ? `Le délai réel constaté est de ${formatNumber(dso.delai_moyen_recouvrement_reel_jours)} jours, contre ${dso.delai_moyen_accorde_jours != null ? `${formatNumber(dso.delai_moyen_accorde_jours)} jours` : "un délai non renseigné"} accordé contractuellement.`
                : `Les dates de paiement réelles ne sont pas encore synchronisées : le chiffre affiché (${formatNumber(dso?.dso_approx_jours ?? 0)} j) est une approximation calculée sur l'encours rapporté au CA.`,
              ecartDelai !== null && ecartDelai > 0
                ? `L'écart de ${formatNumber(ecartDelai)} jours est systémique, pas le fait de quelques comptes isolés : il porte sur l'ensemble des factures suivies et pèse directement sur le besoin en trésorerie.`
                : "Ce chiffre reste à fiabiliser dès que la synchronisation des règlements sera complète.",
            ],
            kv: [
              [
                "Délai accordé",
                dso?.delai_moyen_accorde_jours != null ? `${formatNumber(dso.delai_moyen_accorde_jours)} j` : "—",
              ],
              [
                "Délai réel",
                dso?.delai_moyen_recouvrement_reel_jours != null
                  ? `${formatNumber(dso.delai_moyen_recouvrement_reel_jours)} j`
                  : "non calculable",
              ],
              ["Taux de recouvrement", `${formatPct(dso?.taux_recouvrement_pct ?? null, 1)} %`],
              ["Montant en attente", `${formatMFcfa(dso?.montant_en_attente_xof)} M FCFA`],
              ["Factures suivies", formatNumber(dso?.total_factures ?? 0)],
            ],
            note: dso?.note ?? "Calculé sur les factures et règlements du miroir Odoo.",
          }}
        />
        <StatTile
          span={4}
          label="Marge définitive moyenne"
          value={`${formatPct(margins.stats.perc_marge_definitive_moyen)}`}
          unit="%"
          reading={`${margeEcart >= 0 ? "+" : ""}${formatPct(margeEcart, 1)} pts vs provisoire`}
          readingVariant={margeEcart < 0 ? "neg" : "pos"}
          detail={{
            kicker: "Indicateur · marge",
            title: "Marge définitive contre marge prévue",
            tag: margeEcart < 0 ? "érosion constatée" : "marge tenue",
            tagVariant: margeEcart < 0 ? "r" : "s",
            body: [
              `La marge prévue à la valorisation initiale des dossiers était de ${formatPct(margins.stats.perc_marge_provisoire_moyen)} %. La marge constatée sur ce qui a été réellement facturé ressort à ${formatPct(margins.stats.perc_marge_definitive_moyen)} %, sur ${formatNumber(margins.stats.nb_dossiers)} dossiers.`,
              margeEcart < 0
                ? `L'écart de ${formatPct(Math.abs(margeEcart), 1)} points se lit comme une érosion : ce qui a été vendu rapporte moins que prévu au devis. Le détail des lignes d'achat, qui permettrait d'isoler l'effet ciseau, n'est pas accessible depuis ce profil.`
                : "La marge réalisée tient la prévision du devis, ce qui indique un chiffrage initial fiable.",
            ],
            kv: [
              ["Marge provisoire", `${formatPct(margins.stats.perc_marge_provisoire_moyen)} %`],
              ["Marge définitive", `${formatPct(margins.stats.perc_marge_definitive_moyen)} %`],
              ["Écart", `${margeEcart >= 0 ? "+" : ""}${formatPct(margeEcart, 1)} pts`],
              ["Dossiers", formatNumber(margins.stats.nb_dossiers)],
              ["Reste fournisseurs à payer", `${formatMFcfa(margins.stats.fournisseurs_restant)} M FCFA`],
            ],
            note: "Proxy assumé : comparaison provisoire/définitif, faute d'accès au détail des lignes de commandes fournisseurs depuis ce profil.",
          }}
        />

        <Tile span={12} title="Dérive du délai de paiement" kick="narration">
          {unpaidAnalysis ? (
            <AnalysisNarr text={unpaidAnalysis.analysis} />
          ) : (
            <Note style={{ marginTop: 0 }}>Analyse non disponible pour ce profil.</Note>
          )}
        </Tile>

        <Tile span={7} title="Où se loge le retard" kick="par débiteur">
          {topDebtors.length > 0 ? (
            <>
              <HintLine>Cliquez un compte pour son exposition détaillée</HintLine>
              <Bars
                rows={topDebtors.slice(0, 6).map((d) => {
                  const part = exposition ? (d.montant_total_xof / exposition) * 100 : 0;
                  return {
                    name: d.client,
                    sub: `${formatNumber(d.nb_factures)} facture(s) · retard max ${formatNumber(d.retard_max_jours)} j · ${formatPct(part, 0)} % de l'encours`,
                    value: `${formatMFcfa(d.montant_total_xof)} M`,
                    pct: topDebtorAmount ? (d.montant_total_xof / topDebtorAmount) * 100 : 0,
                    variant: d.retard_max_jours > 90 ? ("r" as const) : ("w" as const),
                    detail: {
                      kicker: "Débiteur",
                      title: d.client,
                      tag: d.retard_max_jours > 90 ? "au-delà de 90 jours" : "retard modéré",
                      tagVariant: d.retard_max_jours > 90 ? ("r" as const) : ("w" as const),
                      body: [
                        `${d.client} porte ${formatMFcfa(d.montant_total_xof)} M FCFA d'impayés sur ${formatNumber(d.nb_factures)} facture(s), avec un retard maximal de ${formatNumber(d.retard_max_jours)} jours.`,
                        d.retard_max_jours > 90
                          ? "Au-delà de 90 jours, la relance commerciale simple a généralement déjà échoué. La question devient celle de l'escalade : mise en demeure, blocage des livraisons, ou étalement négocié si le compte reste stratégique."
                          : "Le retard reste dans une zone où une relance commerciale ferme suffit habituellement à débloquer le règlement.",
                      ],
                      kv: [
                        ["Montant impayé", `${formatMFcfa(d.montant_total_xof)} M FCFA`],
                        ["Factures concernées", formatNumber(d.nb_factures)],
                        ["Retard maximal", `${formatNumber(d.retard_max_jours)} jours`],
                        ["Part de l'encours", `${formatPct(part, 0)} %`],
                      ],
                      note: "Retard calculé entre la date d'échéance de la facture et la date du jour, miroir Odoo.",
                    },
                  };
                })}
              />
            </>
          ) : (
            <Note style={{ marginTop: 0 }}>Aucun impayé enregistré actuellement.</Note>
          )}
        </Tile>

        {unpaid && (
          <Tile span={5} title="Structure de l'exposition" kick="par statut de facture">
            <Bars
              rows={Object.entries(unpaid.exposure.par_statut).map(([statut, v]) => ({
                name: statut,
                sub: `${formatNumber(v.nb)} facture(s)`,
                value: `${formatMFcfa(v.montant)} M`,
                pct: exposition ? (v.montant / exposition) * 100 : 0,
                variant: "w" as const,
              }))}
            />
            <FootNote>
              {formatMFcfa(retard90)} M FCFA sur {formatNumber(unpaid.exposure.retard_90j_nb_factures)} facture(s) sont
              échus depuis plus de 90 jours, soit {formatPct(part90, 0)} % de l&apos;exposition totale.
            </FootNote>
          </Tile>
        )}

        <Tile span={12} title="Érosion de marge" kick="narration · proxy">
          {marginsAnalysis ? (
            <AnalysisNarr text={marginsAnalysis.analysis} />
          ) : (
            <Note style={{ marginTop: 0 }}>Analyse non disponible pour ce profil.</Note>
          )}
          <FootNote>
            Proxy assumé · le détail des lignes de commandes fournisseurs par référence n&apos;est pas accessible depuis
            ce profil. La comparaison marge provisoire / définitive est le signal d&apos;érosion le plus proche
            disponible ici.
          </FootNote>
        </Tile>

        <Tile span={12} title="Factures à investiguer" kick={`${formatNumber(topInvoices.length)} plus gros encours`}>
          {topInvoices.length > 0 ? (
            <>
              <HintLine>Cliquez une facture pour son contexte</HintLine>
              <div style={{ overflowX: "auto" }}>
                <table className="tb">
                  <thead>
                    <tr>
                      <th>Client</th>
                      <th className="r">Montant</th>
                      <th>Échéance</th>
                      <th>Statut</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topInvoices.slice(0, 8).map((inv, i) => (
                      <Clickable
                        key={i}
                        as="tr"
                        detail={{
                          kicker: "Facture impayée",
                          title: String(inv.client),
                          tag: `${formatMFcfa(Number(inv.montant_xof))} M FCFA`,
                          tagVariant: "w",
                          body: [
                            `Facture de ${formatMFcfa(Number(inv.montant_xof))} M FCFA au nom de ${String(inv.client)}, d'échéance ${String(inv["échéance"] ?? "non renseignée")} et de statut « ${String(inv.statut)} ».`,
                            `Elle fait partie des plus gros encours ouverts, qui totalisent ${formatMFcfa(totalTopInvoices)} M FCFA. À vérifier avant la prochaine clôture, en particulier si l'échéance est déjà dépassée.`,
                          ],
                          kv: [
                            ["Client", String(inv.client)],
                            ["Montant", `${formatMFcfa(Number(inv.montant_xof))} M FCFA`],
                            ["Échéance", String(inv["échéance"] ?? "—")],
                            ["Statut", String(inv.statut)],
                          ],
                          note: "Détection par montant, sans modèle statistique : chaque ligne est vérifiable directement dans Odoo.",
                        }}
                      >
                        <td>{String(inv.client)}</td>
                        <td className="r mono">{formatMFcfa(Number(inv.montant_xof))} M</td>
                        <td className="mono">{String(inv["échéance"] ?? "—")}</td>
                        <td>
                          <Tag variant="w">{String(inv.statut)}</Tag>
                        </td>
                      </Clickable>
                    ))}
                  </tbody>
                </table>
              </div>
              <FootNote>
                Ces {formatNumber(topInvoices.length)} factures représentent {formatMFcfa(totalTopInvoices)} M FCFA
                d&apos;encours. La détection d&apos;anomalies fines (doublons, écarts commande/facture) reste à
                construire côté backend.
              </FootNote>
            </>
          ) : (
            <Note style={{ marginTop: 0 }}>Aucune facture impayée à afficher.</Note>
          )}
        </Tile>
      </Bento>
    </>
  );
}
