import { getBriefing } from "@/lib/api/briefing";
import { getDso, getMargins, getMarginsAnalysis, getUnpaid, getUnpaidAnalysis } from "@/lib/api/dashboard";
import { formatFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, Brief, /* FootNote, */ HintLine, StatTile, Tile } from "@/components/ui/bento";
import { Clickable } from "@/components/ui/detail";
import { AnalysisSlot } from "@/components/ui/analysis-slot";
import { Note, Tag } from "@/components/ui/primitives";

export async function DfVision() {
  // Narrations LLM exclues du Promise.all — voir components/ui/analysis-slot.tsx :
  // figées à la journée, mais 10-20 s si le calcul de secours se déclenche.
  const [dso, unpaid, margins, briefing] = await Promise.all([
    getDso(),
    getUnpaid(15),
    getMargins(),
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

  // Taux AGRÉGÉS (`taux_marge_*`, ratio des totaux) et non `perc_marge_*_moyen`,
  // qui sont des moyennes non pondérées de pourcentages par dossier : sur ce
  // miroir la provisoire y vaut -745 %, un chiffre que l'écran affichait tel quel.
  const tauxProv = margins.stats.taux_marge_provisoire_pct;
  const tauxDef = margins.stats.taux_marge_definitive_pct;
  // Un dossier sans dépense imputée affiche 100 % de marge par construction. Le
  // taux définitif n'est donc publiable que si l'imputation couvre une part
  // suffisante du CA de l'exercice ; en dessous du seuil, la tuile annonce la
  // couverture À LA PLACE du chiffre plutôt qu'un « 99,99 % » flatteur et faux.
  const margeExploitable = margins.stats.marge_definitive_exploitable;
  const couvertureMarge = margins.stats.couverture_marge_definitive_pct;
  const margeEcart =
    margeExploitable && tauxDef !== null && tauxProv !== null ? tauxDef - tauxProv : null;
  const margeErodee = margeEcart !== null && margeEcart < 0;

  return (
    <>
      <Brief
        kicker="Cash · encaissement et marge"
        headline={`${formatFcfa(exposition)} FCFA d'encours client, dont ${formatFcfa(retard90)} échus depuis plus de 90 jours.`}
        lines={briefLines}
        paragraphs={
          briefLines.length
            ? undefined
            : [
                `L'encours client atteint ${formatFcfa(exposition)} FCFA sur ${formatNumber(unpaid?.exposure.nb_factures_impayees ?? 0)} factures impayées. Le briefing du jour n'est pas encore généré pour ce profil.`,
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
          {
            label: margeExploitable
              ? `Marge définitive ${formatPct(tauxDef, 1)} %`
              : `Marge définitive non exploitable (couverture ${formatPct(couvertureMarge, 1)} %)`,
            hot: margeErodee,
          },
        ]}
      />

      <Bento>
        {/* Ces trois tuiles vivent dans le Bento (chiffre à pleine taille) et non
            dans une `.kpi-row` : le rang n'y change que le fond et le filet.
            L'encours est l'exposition, c'est-à-dire l'objet de l'écran. */}
        <StatTile
          span={4}
          rang="principal"
          label="Encours client"
          aide="Le total de ce que vos clients vous doivent à ce jour, factures émises et non encore réglées."
          value={formatFcfa(exposition)}
          unit="FCFA"
          reading={`${formatNumber(unpaid?.exposure.nb_factures_impayees ?? 0)} factures impayées`}
          readingVariant="neg"
          detail={{
            kicker: "Indicateur · exposition",
            title: "Encours client impayé",
            tag: `${formatNumber(unpaid?.exposure.nb_factures_impayees ?? 0)} factures`,
            tagVariant: "r",
            body: [
              `L'encours total impayé s'élève à ${formatFcfa(exposition)} FCFA, réparti sur ${formatNumber(unpaid?.exposure.nb_factures_impayees ?? 0)} factures.`,
              `${formatFcfa(retard90)} FCFA, soit ${formatPct(part90, 0)} % de cet encours, sont échus depuis plus de 90 jours. Au-delà de ce seuil, le recouvrement amiable devient rarement suffisant.`,
            ],
            kv: [
              ["Encours total", `${formatFcfa(exposition)} FCFA`],
              ["Factures impayées", formatNumber(unpaid?.exposure.nb_factures_impayees ?? 0)],
              ["Échu > 90 jours", `${formatFcfa(retard90)} FCFA`],
              ["Part > 90 jours", `${formatPct(part90, 0)} %`],
            ],
            // note: "Factures non réglées du miroir Odoo, hors litiges déclarés.",
          }}
        />
        <StatTile
          span={4}
          label={dso?.delai_moyen_recouvrement_reel_jours != null ? "DSO réel" : "DSO approché"}
          aide="Le nombre de jours que mettent vos clients à vous payer, en moyenne. « Approché » signale un calcul de substitution, faute des dates de règlement exactes."
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
            title: dso?.exercice_delais
              ? `Délai moyen de recouvrement — règlements ${dso.exercice_delais}`
              : "Délai moyen de recouvrement",
            tag: ecartDelai !== null && ecartDelai > 0 ? "au-delà du contractuel" : "à fiabiliser",
            tagVariant: ecartDelai !== null && ecartDelai > 0 ? "r" : "w",
            body: [
              dso?.delai_moyen_recouvrement_reel_jours != null
                ? `Le délai réel constaté est de ${formatNumber(dso.delai_moyen_recouvrement_reel_jours)} jours, contre ${dso.delai_moyen_accorde_jours != null ? `${formatNumber(dso.delai_moyen_accorde_jours)} jours` : "un délai non renseigné"} accordé contractuellement.`
                : `Les dates de paiement réelles ne sont pas encore synchronisées : le chiffre affiché (${formatNumber(dso?.dso_approx_jours ?? 0)} j) est une approximation calculée sur l'encours rapporté au CA.`,
              // Sur quoi la moyenne est mesurée : le nombre de règlements est ce
              // qui dit si elle est solide. Un exercice à peine entamé en porte
              // peu, et le lecteur doit le voir plutôt que de le supposer.
              dso?.nb_factures_avec_date_paiement
                ? `Mesuré sur ${formatNumber(dso.nb_factures_avec_date_paiement)} facture(s) encaissée(s)${dso.exercice_delais ? ` en ${dso.exercice_delais}` : ""}, quelle que soit leur année d'émission — borner sur l'émission ne retiendrait que les factures déjà réglées la même année, donc les payeurs les plus rapides.`
                : "Aucun règlement daté sur l'exercice : le chiffre affiché retombe sur l'approximation bilancielle.",
              ecartDelai !== null && ecartDelai > 0
                ? `L'écart de ${formatNumber(ecartDelai)} jours est systémique, pas le fait de quelques comptes isolés : il porte sur l'ensemble des factures encaissées sur la période et pèse directement sur le besoin en trésorerie.`
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
              // Les deux délais ci-dessus portent sur les règlements de
              // l'exercice ; ces trois lignes sont des cumuls sur tout le
              // miroir. Deux portées dans un même tableau doivent être écrites,
              // sinon la colonne se lit comme un seul exercice.
              ["Taux de recouvrement (cumul)", `${formatPct(dso?.taux_recouvrement_pct ?? null, 1)} %`],
              ["Montant en attente (tous exercices)", `${formatFcfa(dso?.montant_en_attente_xof)} FCFA`],
              ["Factures suivies (tous exercices)", formatNumber(dso?.total_factures ?? 0)],
            ],
            // note: dso?.note ?? "Calculé sur les factures et règlements du miroir Odoo.",
          }}
        />
        <StatTile
          span={4}
          label="Marge définitive moyenne"
          aide="Ce que vous gardez en moyenne sur un dossier une fois tout facturé et payé. C'est la marge réellement constatée, pas celle espérée au devis."
          value={margeExploitable ? `${formatPct(tauxDef, 1)}` : "—"}
          unit={margeExploitable ? "%" : ""}
          reading={
            margeExploitable
              ? `${margeEcart !== null && margeEcart >= 0 ? "+" : ""}${formatPct(margeEcart, 1)} pts vs provisoire`
              : `dépense imputée sur ${formatPct(couvertureMarge, 1)} % du CA — non exploitable`
          }
          readingVariant={margeErodee ? "neg" : margeExploitable ? "pos" : "wat"}
          detail={{
            kicker: "Indicateur · marge",
            title: `Marge définitive contre marge prévue — exercice ${margins.stats.annee}`,
            tag: margeExploitable ? (margeErodee ? "érosion constatée" : "marge tenue") : "non exploitable",
            tagVariant: margeExploitable ? (margeErodee ? "r" : "s") : "w",
            body: [
              margeExploitable
                ? `La marge prévue à la valorisation initiale des dossiers était de ${formatPct(tauxProv, 1)} %. La marge constatée sur ce qui a été réellement facturé ressort à ${formatPct(tauxDef, 1)} %, mesurée sur les ${formatNumber(margins.stats.nb_dossiers_marge_imputee)} dossiers dont la dépense est imputée.`
                : `La marge définitive n'est pas mesurable sur l'exercice ${margins.stats.annee} : la dépense n'est imputée que sur ${formatNumber(margins.stats.nb_dossiers_marge_imputee)} dossier(s), soit ${formatPct(couvertureMarge, 1)} % du CA facturé, très en dessous du seuil de ${formatPct(margins.stats.seuil_couverture_marge_pct, 0)} % retenu.`,
              margeExploitable
                ? (margeErodee
                    ? `L'écart de ${formatPct(Math.abs(margeEcart ?? 0), 1)} points se lit comme une érosion : ce qui a été vendu rapporte moins que prévu au devis. Le détail des lignes d'achat, qui permettrait d'isoler l'effet ciseau, n'est pas accessible depuis ce profil.`
                    : "La marge réalisée tient la prévision du devis, ce qui indique un chiffrage initial fiable.")
                : "Un dossier sans dépense imputée affiche 100 % de marge par construction : publier la moyenne donnerait un taux flatteur et faux. La marge provisoire ci-dessous, elle, reste mesurée sur l'ensemble de l'exercice.",
              // Le taux provisoire n'a pas la même condition de validité : il
              // repose sur la valorisation du devis, renseignée dès l'ouverture.
              `Marge provisoire de l'exercice : ${formatPct(tauxProv, 1)} % sur ${formatNumber(margins.stats.nb_dossiers)} dossiers.`,
            ],
            kv: [
              ["Marge provisoire", `${formatPct(tauxProv, 1)} %`],
              [
                "Marge définitive",
                margeExploitable ? `${formatPct(tauxDef, 1)} %` : "non exploitable",
              ],
              ["Écart", margeEcart !== null ? `${margeEcart >= 0 ? "+" : ""}${formatPct(margeEcart, 1)} pts` : "—"],
              [
                "Couverture de la dépense imputée",
                `${formatPct(couvertureMarge, 1)} % du CA (seuil ${formatPct(margins.stats.seuil_couverture_marge_pct, 0)} %)`,
              ],
              [`Dossiers ouverts en ${margins.stats.annee}`, formatNumber(margins.stats.nb_dossiers)],
              // Stock : dette fournisseur à ce jour, tous exercices confondus —
              // la borner à l'exercice en ferait disparaître l'essentiel.
              ["Reste fournisseurs à payer (tous exercices)", `${formatFcfa(margins.stats.fournisseurs_restant)} FCFA`],
            ],
            // note: "Proxy assumé : comparaison provisoire/définitif, faute d'accès au détail des lignes de commandes fournisseurs depuis ce profil.",
          }}
        />

        {/* Appariées sur une ligne : les deux faces d'un même encours — par
            débiteur à gauche, par facture à droite. Le tableau de droite garde son
            `overflowX` et scrolle dans sa tuile plutôt que d'élargir la ligne. */}
        <Tile
          span={6}
          title="Où se loge le retard"
          kick="par débiteur"
          aide="Quels clients concentrent les impayés. Souvent quelques-uns portent l'essentiel du retard : ce sont eux qu'il faut traiter en premier."
        >
          {topDebtors.length > 0 ? (
            <>
              <HintLine>Cliquez un compte pour son exposition détaillée</HintLine>
              <Bars
                rows={topDebtors.slice(0, 6).map((d) => {
                  const part = exposition ? (d.montant_total_xof / exposition) * 100 : 0;
                  return {
                    name: d.client,
                    sub: `${formatNumber(d.nb_factures)} facture(s) · retard max ${formatNumber(d.retard_max_jours)} j · ${formatPct(part, 0)} % de l'encours`,
                    value: `${formatFcfa(d.montant_total_xof)}`,
                    pct: topDebtorAmount ? (d.montant_total_xof / topDebtorAmount) * 100 : 0,
                    variant: d.retard_max_jours > 90 ? ("r" as const) : ("w" as const),
                    detail: {
                      kicker: "Débiteur",
                      title: d.client,
                      tag: d.retard_max_jours > 90 ? "au-delà de 90 jours" : "retard modéré",
                      tagVariant: d.retard_max_jours > 90 ? ("r" as const) : ("w" as const),
                      body: [
                        `${d.client} porte ${formatFcfa(d.montant_total_xof)} FCFA d'impayés sur ${formatNumber(d.nb_factures)} facture(s), avec un retard maximal de ${formatNumber(d.retard_max_jours)} jours.`,
                        d.retard_max_jours > 90
                          ? "Au-delà de 90 jours, la relance commerciale simple a généralement déjà échoué. La question devient celle de l'escalade : mise en demeure, blocage des livraisons, ou étalement négocié si le compte reste stratégique."
                          : "Le retard reste dans une zone où une relance commerciale ferme suffit habituellement à débloquer le règlement.",
                      ],
                      kv: [
                        ["Montant impayé", `${formatFcfa(d.montant_total_xof)} FCFA`],
                        ["Factures concernées", formatNumber(d.nb_factures)],
                        ["Retard maximal", `${formatNumber(d.retard_max_jours)} jours`],
                        ["Part de l'encours", `${formatPct(part, 0)} %`],
                      ],
                      // note: "Retard calculé entre la date d'échéance de la facture et la date du jour, miroir Odoo.",
                    },
                  };
                })}
              />
            </>
          ) : (
            <Note style={{ marginTop: 0 }}>Aucun impayé enregistré actuellement.</Note>
          )}
        </Tile>

        <Tile
          span={6}
          title="Factures à investiguer"
          kick={`${formatNumber(topInvoices.length)} plus gros encours`}
          aide="Les factures impayées les plus lourdes, à examiner une par une. Un blocage administratif ou un litige se cache souvent derrière un gros montant qui traîne."
        >
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
                          tag: `${formatFcfa(Number(inv.montant_xof))} FCFA`,
                          tagVariant: "w",
                          body: [
                            `Facture de ${formatFcfa(Number(inv.montant_xof))} FCFA au nom de ${String(inv.client)}, d'échéance ${String(inv["échéance"] ?? "non renseignée")} et de statut « ${String(inv.statut)} ».`,
                            `Elle fait partie des plus gros encours ouverts, qui totalisent ${formatFcfa(totalTopInvoices)} FCFA. À vérifier avant la prochaine clôture, en particulier si l'échéance est déjà dépassée.`,
                          ],
                          kv: [
                            ["Client", String(inv.client)],
                            ["Montant", `${formatFcfa(Number(inv.montant_xof))} FCFA`],
                            ["Échéance", String(inv["échéance"] ?? "—")],
                            ["Statut", String(inv.statut)],
                          ],
                          // note: "Détection par montant, sans modèle statistique : chaque ligne est vérifiable directement dans Odoo.",
                        }}
                      >
                        <td>{String(inv.client)}</td>
                        <td className="r mono">{formatFcfa(Number(inv.montant_xof))} M</td>
                        <td className="mono">{String(inv["échéance"] ?? "—")}</td>
                        <td>
                          <Tag variant="w">{String(inv.statut)}</Tag>
                        </td>
                      </Clickable>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* <FootNote>
                Ces {formatNumber(topInvoices.length)} factures représentent {formatFcfa(totalTopInvoices)} FCFA
                d&apos;encours. La détection d&apos;anomalies fines (doublons, écarts commande/facture) reste à
                construire côté backend.
              </FootNote> */}
            </>
          ) : (
            <Note style={{ marginTop: 0 }}>Aucune facture impayée à afficher.</Note>
          )}
        </Tile>

        {/* Les deux narrations de l'écran, appariées sur une seule ligne et
            placées en clôture.
            Elles répondent à la même question sous deux angles (ce qui n'est pas
            encaissé, ce qui n'est pas gagné) et se lisent l'une contre l'autre —
            d'où la ligne partagée plutôt que deux pleines largeurs éloignées.
            En fin d'écran parce qu'elles commentent les chiffres qui précèdent :
            le DAF lit d'abord ses indicateurs, ses débiteurs et ses factures,
            puis l'analyse qui les relie. Pliées, elles annoncent leur sujet sans
            imposer leurs trois paragraphes : le lecteur ouvre celle qui le
            concerne. */}
        <Tile
          span={6}
          title="Dérive du délai de paiement"
          kick="narration"
          aide="Si vos clients mettent de plus en plus de temps à payer, et ce que cela coûte en trésorerie."
        >
          <AnalysisSlot load={getUnpaidAnalysis} pliable titrePli="Lire l'analyse du délai de paiement" />
        </Tile>

        <Tile
          span={6}
          title="Érosion de marge"
          kick="narration · proxy"
          aide="Ce qui grignote votre marge au fil des dossiers. « Proxy » signale une mesure indirecte, faute d'un rattachement complet des dépenses."
        >
          <AnalysisSlot load={getMarginsAnalysis} pliable titrePli="Lire l'analyse de la marge" />
        </Tile>
      </Bento>
    </>
  );
}
