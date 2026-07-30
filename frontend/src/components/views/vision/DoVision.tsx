import { getBriefing } from "@/lib/api/briefing";
import { getKpis, getMargins, getMarginsAnalysis } from "@/lib/api/dashboard";
import { getPartnersAnalysis, getSupplierIntelligence } from "@/lib/api/partners";
import { formatMFcfa, formatNumber, formatPct, mFcfa, signed } from "@/lib/format";
import { Bars, Bento, Brief, /* FootNote, */ HintLine, Lst, StatTile, Tile } from "@/components/ui/bento";
import { AnalysisSlot } from "@/components/ui/analysis-slot";
import { Note } from "@/components/ui/primitives";

interface TopDossier {
  ref: string;
  client: string;
  projet: string;
  ca_provisoire: number;
  ca_definitif: number;
  perc_marge_prov: number;
  perc_marge_def: number;
}

export async function DoVision() {
  // Narrations LLM exclues du Promise.all — voir components/ui/analysis-slot.tsx :
  // figées à la journée, mais 10-20 s si le calcul de secours se déclenche.
  const [margins, kpis, suppliers, briefing] = await Promise.all([
    getMargins(undefined, 30),
    getKpis(),
    getSupplierIntelligence(15),
    getBriefing(),
  ]);

  const briefLines = briefing?.section?.resume?.length
    ? briefing.section.resume
    : (briefing?.section?.bullets ?? []).slice(0, 5);

  const avgMonthlyRevenue = kpis.monthly.length
    ? kpis.monthly.reduce((s, m) => s + m.ca_xof, 0) / kpis.monthly.length
    : 0;
  const moisVisibilite = avgMonthlyRevenue ? margins.stats.backlog_total / avgMonthlyRevenue : null;

  const dossiers = margins.top_dossiers as unknown as TopDossier[];
  const enDerive = dossiers
    .filter((d) => d.ca_provisoire > 0 && d.ca_definitif < d.ca_provisoire * 0.5)
    .slice(0, 5);

  const risquesSousTraitance = (suppliers ?? [])
    .filter((s) => s.taux_dependance_pct >= 10 || s.dossiers_a_risque_fournisseur_unique > 0)
    .sort((a, b) => b.taux_dependance_pct - a.taux_dependance_pct)
    .slice(0, 5);

  const tauxMaterialisation = margins.stats.ca_provisoire_total
    ? (margins.stats.ca_definitif_total / margins.stats.ca_provisoire_total) * 100
    : 0;

  const topSupplierAmount = suppliers?.[0]?.montant_total_xof ?? 0;
  const monoSource = (suppliers ?? []).filter((s) => s.dossiers_a_risque_fournisseur_unique > 0);

  return (
    <>
      <Brief
        kicker="Livraison · backlog et fournisseurs"
        headline={`${formatMFcfa(margins.stats.backlog_total)} M FCFA de backlog à consommer sur ${formatNumber(margins.stats.nb_dossiers)} dossiers.`}
        lines={briefLines}
        paragraphs={
          briefLines.length
            ? undefined
            : [
                `Le backlog représente ${formatMFcfa(margins.stats.backlog_total)} M FCFA, pour un taux de matérialisation du CA de ${formatPct(tauxMaterialisation, 0)} %. Le briefing du jour n'est pas encore généré pour ce profil.`,
              ]
        }
        pills={[
          { label: `${formatNumber(margins.stats.nb_dossiers)} dossiers actifs` },
          { label: `Matérialisation ${formatPct(tauxMaterialisation, 0)} %`, hot: tauxMaterialisation < 60 },
          {
            label:
              moisVisibilite !== null ? `Visibilité ${formatPct(moisVisibilite, 1)} mois` : "Visibilité non calculable",
            hot: moisVisibilite !== null && moisVisibilite < 3,
          },
          { label: `${formatNumber(monoSource.length)} fournisseur(s) mono-source`, hot: monoSource.length > 0 },
        ]}
      />

      <Bento>
        <StatTile
          span={4}
          label="Backlog à consommer"
          value={formatMFcfa(margins.stats.backlog_total)}
          unit="M FCFA"
          reading={`${formatNumber(margins.stats.nb_dossiers)} dossiers actifs`}
          detail={{
            kicker: "Indicateur · backlog",
            title: "Backlog restant à consommer",
            tag: `${formatNumber(margins.stats.nb_dossiers)} dossiers`,
            tagVariant: "a",
            body: [
              `Le backlog correspond à l'écart entre le CA provisoire des dossiers (${formatMFcfa(margins.stats.ca_provisoire_total)} M FCFA) et ce qui a déjà été facturé (${formatMFcfa(margins.stats.ca_definitif_total)} M FCFA).`,
              `Sur cette base, ${formatPct(tauxMaterialisation, 0)} % de la valeur engagée s'est matérialisée en facturation. Le reste est du travail vendu qui n'a pas encore produit de facture.`,
            ],
            kv: [
              ["CA provisoire", `${formatMFcfa(margins.stats.ca_provisoire_total)} M FCFA`],
              ["CA définitif", `${formatMFcfa(margins.stats.ca_definitif_total)} M FCFA`],
              ["Backlog", `${formatMFcfa(margins.stats.backlog_total)} M FCFA`],
              ["Taux de matérialisation", `${formatPct(tauxMaterialisation, 0)} %`],
              ["Dossiers", formatNumber(margins.stats.nb_dossiers)],
            ],
            // note: "Le CA provisoire est la valorisation initiale du dossier commercial, le définitif la valeur réellement facturée à date.",
          }}
        />
        <StatTile
          span={4}
          label="Mois de visibilité"
          value={moisVisibilite !== null ? formatPct(moisVisibilite, 1) : "—"}
          unit={moisVisibilite !== null ? "mois" : undefined}
          reading={
            moisVisibilite === null
              ? "non calculable"
              : moisVisibilite < 3
                ? "sous le seuil de 3 mois"
                : "au-dessus du seuil de 3 mois"
          }
          readingVariant={moisVisibilite !== null && moisVisibilite < 3 ? "neg" : "pos"}
          detail={{
            kicker: "Indicateur · proxy de charge",
            title: "Mois de visibilité (proxy)",
            tag: moisVisibilite !== null && moisVisibilite < 3 ? "sous le seuil" : "acceptable",
            tagVariant: moisVisibilite !== null && moisVisibilite < 3 ? "r" : "s",
            body: [
              moisVisibilite !== null
                ? `Le backlog de ${formatMFcfa(margins.stats.backlog_total)} M FCFA rapporté au rythme de facturation mensuel moyen (${formatMFcfa(avgMonthlyRevenue)} M FCFA) donne ${formatPct(moisVisibilite, 1)} mois de visibilité.`
                : "Le rythme de facturation mensuel moyen n'est pas calculable sur la période disponible.",
              "Proxy assumé : sans feuilles de temps dans le miroir, la charge réelle des équipes n'est pas mesurable. Ce chiffre mesure la couverture du carnet, pas l'occupation des consultants.",
            ],
            kv: [
              ["Backlog", `${formatMFcfa(margins.stats.backlog_total)} M FCFA`],
              ["CA mensuel moyen", `${formatMFcfa(avgMonthlyRevenue)} M FCFA`],
              ["Visibilité", moisVisibilite !== null ? `${formatPct(moisVisibilite, 1)} mois` : "—"],
              ["Seuil interne", "3,0 mois"],
            ],
            // note: "Calcul global, toutes practices confondues : le détail par practice exigerait un référentiel produit normalisé, absent du miroir.",
          }}
        />
        <StatTile
          span={4}
          label="Reste fournisseurs à payer"
          value={formatMFcfa(margins.stats.fournisseurs_restant)}
          unit="M FCFA"
          reading={`${formatNumber(suppliers?.length ?? 0)} fournisseurs suivis`}
          readingVariant="wat"
          detail={{
            kicker: "Indicateur · engagement fournisseur",
            title: "Reste à payer aux fournisseurs",
            tag: `${formatMFcfa(margins.stats.fournisseurs_restant)} M FCFA`,
            tagVariant: "w",
            body: [
              `Les commandes d'achat engagées laissent ${formatMFcfa(margins.stats.fournisseurs_restant)} M FCFA à régler.`,
              `À mettre en regard du reste à encaisser client (${formatMFcfa(margins.stats.reste_a_encaisser)} M FCFA) : c'est l'écart entre les deux qui détermine si la livraison se finance elle-même.`,
            ],
            kv: [
              ["Reste fournisseurs", `${formatMFcfa(margins.stats.fournisseurs_restant)} M FCFA`],
              ["Reste à encaisser client", `${formatMFcfa(margins.stats.reste_a_encaisser)} M FCFA`],
              ["Déjà encaissé", `${formatMFcfa(margins.stats.total_encaisse)} M FCFA`],
            ],
            // note: "Montants issus des commandes d'achat et factures du miroir Odoo.",
          }}
        />

        <Tile span={12} title="Consommation du backlog vs plan" kick="narration">
          <AnalysisSlot load={getMarginsAnalysis} />
          {/* <FootNote>
            Proxy assumé · l&apos;écart entre CA provisoire et définitif signale un décalage réel mais n&apos;en donne
            pas la cause (staffing, périmètre, fournisseur).
          </FootNote> */}
        </Tile>

        <Tile span={5} title="Cycle de la valeur" kick="du devis à l'encaissement">
          <Bars
            rows={[
              {
                name: "CA provisoire cumulé",
                sub: "valorisation initiale des dossiers",
                value: `${formatMFcfa(margins.stats.ca_provisoire_total)} M`,
                pct: 100,
              },
              {
                name: "CA définitif cumulé",
                sub: `${formatPct(tauxMaterialisation, 0)} % matérialisé`,
                value: `${formatMFcfa(margins.stats.ca_definitif_total)} M`,
                pct: tauxMaterialisation,
                variant: tauxMaterialisation < 60 ? ("w" as const) : ("s" as const),
              },
              {
                name: "Déjà encaissé",
                sub: "règlements reçus",
                value: `${formatMFcfa(margins.stats.total_encaisse)} M`,
                pct: margins.stats.ca_provisoire_total
                  ? (margins.stats.total_encaisse / margins.stats.ca_provisoire_total) * 100
                  : 0,
                variant: "s" as const,
              },
              {
                name: "Reste à encaisser",
                sub: "facturé non réglé",
                value: `${formatMFcfa(margins.stats.reste_a_encaisser)} M`,
                pct: margins.stats.ca_provisoire_total
                  ? (margins.stats.reste_a_encaisser / margins.stats.ca_provisoire_total) * 100
                  : 0,
                variant: "r" as const,
              },
            ]}
          />
          {/* <FootNote>Toutes les barres sont exprimées en part du CA provisoire cumulé.</FootNote> */}
        </Tile>

        <Tile span={7} title="Dossiers en dérive" kick="CA définitif < 50 % du provisoire">
          {enDerive.length > 0 ? (
            <>
              <HintLine>Cliquez un dossier pour son écart détaillé</HintLine>
              <Lst
                items={enDerive.map((d) => {
                  const avancement = d.ca_provisoire ? (d.ca_definitif / d.ca_provisoire) * 100 : 0;
                  return {
                    title: `${d.ref} · ${d.client}`,
                    sub: d.projet,
                    tag: `${formatPct(avancement, 0)} % facturé`,
                    tagVariant: "r" as const,
                    detail: {
                      kicker: "Dossier en dérive",
                      title: `${d.ref} · ${d.client}`,
                      tag: "dérive de facturation",
                      tagVariant: "r" as const,
                      body: [
                        `Le dossier « ${d.projet} » a été valorisé à ${formatMFcfa(d.ca_provisoire)} M FCFA mais seuls ${formatMFcfa(d.ca_definitif)} M FCFA ont été facturés, soit ${formatPct(avancement, 0)} % de la valeur engagée.`,
                        `La marge passe de ${formatPct(d.perc_marge_prov, 1)} % prévue à ${formatPct(d.perc_marge_def, 1)} % constatée. Un écart de cette ampleur relève soit d'un retard de facturation, soit d'une réduction de périmètre non répercutée au contrat.`,
                      ],
                      kv: [
                        ["CA provisoire", `${formatMFcfa(d.ca_provisoire)} M FCFA`],
                        ["CA définitif", `${formatMFcfa(d.ca_definitif)} M FCFA`],
                        ["Avancement facturé", `${formatPct(avancement, 0)} %`],
                        ["Marge prévue", `${formatPct(d.perc_marge_prov, 1)} %`],
                        ["Marge constatée", `${formatPct(d.perc_marge_def, 1)} %`],
                      ],
                      // note: "Proxy assumé : le cockpit ne distingue pas un retard de facturation d'une baisse de périmètre.",
                    },
                  };
                })}
              />
            </>
          ) : (
            <Note style={{ marginTop: 0 }}>Aucun dossier ne présente une dérive marquée sur cet échantillon.</Note>
          )}
        </Tile>

        <Tile span={12} title="Fiabilité fournisseurs" kick="narration">
          <AnalysisSlot load={getPartnersAnalysis} />
        </Tile>

        {suppliers && suppliers.length > 0 && (
          <Tile span={7} title="Poids des fournisseurs" kick="part des achats">
            <HintLine>Cliquez un fournisseur pour son exposition</HintLine>
            <Bars
              rows={suppliers.slice(0, 6).map((s) => ({
                name: s.name,
                sub: `${formatPct(s.taux_dependance_pct, 1)} % des achats · retard moyen ${s.retard_moyen_jours !== null ? `${formatNumber(s.retard_moyen_jours)} j` : "non mesuré"}`,
                value: `${formatMFcfa(s.montant_total_xof)} M`,
                pct: topSupplierAmount ? (s.montant_total_xof / topSupplierAmount) * 100 : 0,
                variant:
                  s.taux_dependance_pct > 20
                    ? ("r" as const)
                    : s.taux_dependance_pct > 10
                      ? ("w" as const)
                      : undefined,
                detail: {
                  kicker: "Fournisseur",
                  title: s.name,
                  tag:
                    s.dossiers_a_risque_fournisseur_unique > 0
                      ? "mono-source"
                      : s.taux_dependance_pct > 20
                        ? "dépendance forte"
                        : "exposition mesurée",
                  tagVariant:
                    s.dossiers_a_risque_fournisseur_unique > 0
                      ? ("r" as const)
                      : s.taux_dependance_pct > 20
                        ? ("r" as const)
                        : ("n" as const),
                  body: [
                    `${s.name} représente ${formatMFcfa(s.montant_total_xof)} M FCFA d'achats, soit ${formatPct(s.taux_dependance_pct, 1)} % du total, sur ${formatNumber(s.nb_dossiers_lies)} dossier(s) lié(s).`,
                    s.dossiers_a_risque_fournisseur_unique > 0
                      ? `${formatNumber(s.dossiers_a_risque_fournisseur_unique)} dossier(s) dépendent de ce seul fournisseur : une rupture de sa part bloque directement la livraison client, sans solution de repli identifiée dans le miroir.`
                      : "Aucun dossier ne dépend exclusivement de ce fournisseur, ce qui limite le risque de rupture.",
                  ],
                  kv: [
                    ["Montant acheté", `${formatMFcfa(s.montant_total_xof)} M FCFA`],
                    ["Dépendance", `${formatPct(s.taux_dependance_pct, 1)} %`],
                    ["Dossiers liés", formatNumber(s.nb_dossiers_lies)],
                    ["Dossiers mono-source", formatNumber(s.dossiers_a_risque_fournisseur_unique)],
                    [
                      "Retard moyen",
                      s.retard_moyen_jours !== null ? `${formatNumber(s.retard_moyen_jours)} jours` : "non mesuré",
                    ],
                    ["Marge de sous-traitance", `${signed(mFcfa(s.marge_sous_traitance_xof))} M FCFA`],
                  ],
                  // note: "Calculé sur les commandes d'achat réelles. Le retard n'est mesurable que si la date de réception est renseignée.",
                },
              }))}
            />
          </Tile>
        )}

        <Tile span={5} title="Tension sur la sous-traitance" kick="M4">
          {risquesSousTraitance.length > 0 ? (
            <Lst
              items={risquesSousTraitance.map((s) => ({
                title: s.name,
                sub: `${formatNumber(s.nb_dossiers_lies)} dossier(s) · marge ${signed(mFcfa(s.marge_sous_traitance_xof))} M`,
                tag: s.dossiers_a_risque_fournisseur_unique > 0 ? "mono-source" : "à surveiller",
                tagVariant: s.dossiers_a_risque_fournisseur_unique > 0 ? ("r" as const) : ("n" as const),
                detail: {
                  kicker: "Risque de sous-traitance",
                  title: s.name,
                  tag: s.dossiers_a_risque_fournisseur_unique > 0 ? "mono-source" : "dépendance élevée",
                  tagVariant: s.dossiers_a_risque_fournisseur_unique > 0 ? ("r" as const) : ("w" as const),
                  body: [
                    `Ce fournisseur porte ${formatPct(s.taux_dependance_pct, 1)} % des achats sur ${formatNumber(s.nb_dossiers_lies)} dossier(s), pour une marge de sous-traitance de ${signed(mFcfa(s.marge_sous_traitance_xof))} M FCFA.`,
                    s.dossiers_a_risque_fournisseur_unique > 0
                      ? "Sans second fournisseur référencé sur ces dossiers, la continuité de livraison repose sur lui seul. Une clause de continuité ou un fournisseur alternatif est la parade habituelle."
                      : "La dépendance dépasse le seuil de 10 % des achats sans être mono-source : le risque est financier plus que technique.",
                  ],
                  kv: [
                    ["Dépendance", `${formatPct(s.taux_dependance_pct, 1)} %`],
                    ["Dossiers liés", formatNumber(s.nb_dossiers_lies)],
                    ["Dossiers mono-source", formatNumber(s.dossiers_a_risque_fournisseur_unique)],
                    ["Marge de sous-traitance", `${signed(mFcfa(s.marge_sous_traitance_xof))} M FCFA`],
                  ],
                  // note: "Seuil de dépendance retenu : 10 % des achats, ou présence d'au moins un dossier mono-source.",
                },
              }))}
            />
          ) : (
            <Note style={{ marginTop: 0 }}>
              Aucun fournisseur ne dépasse le seuil de dépendance sur cet échantillon.
            </Note>
          )}
        </Tile>
      </Bento>
    </>
  );
}
