import { getBriefing } from "@/lib/api/briefing";
import { getClientPortfolio } from "@/lib/api/clients";
import { getKpis, getMargins, getMarginsAnalysis } from "@/lib/api/dashboard";
import { getPartnersAnalysis, getSupplierIntelligence } from "@/lib/api/partners";
import { formatFcfa, formatNumber, formatPct, signedFcfa } from "@/lib/format";
import { Bars, Bento, Brief, /* FootNote, */ HintLine, Lst, Reste, StatTile, Tile } from "@/components/ui/bento";
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
  const [margins, kpis, suppliers, portfolio, briefing] = await Promise.all([
    getMargins(undefined, 30),
    getKpis(),
    getSupplierIntelligence(15),
    getClientPortfolio(50),
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

  // Taux de matérialisation du BACKLOG, donc calculé sur la même population que
  // lui : tous exercices. Le rapporter au seul CA de l'exercice mélangerait un
  // stock cumulé à un flux de quelques mois — en janvier, le taux exploserait
  // sans que rien n'ait bougé dans la livraison.
  const tauxMaterialisation = margins.stats.ca_provisoire_tous_exercices
    ? (margins.stats.ca_definitif_tous_exercices / margins.stats.ca_provisoire_tous_exercices) * 100
    : 0;

  const topSupplierAmount = suppliers?.[0]?.montant_total_xof ?? 0;
  const monoSource = (suppliers ?? []).filter((s) => s.dossiers_a_risque_fournisseur_unique > 0);

  // La charge de livraison vue PAR CLIENT, et non par dossier : le reste de
  // l'écran raisonne en dossiers, mais un retard se négocie avec un client, pas
  // avec une référence. Les comptes portant plusieurs chantiers ouverts ne sont
  // visibles nulle part ailleurs.
  const avecBacklog = (portfolio ?? []).filter((c) => c.backlog_xof > 0);
  const parBacklog = avecBacklog
    .slice()
    .sort((a, b) => b.backlog_xof - a.backlog_xof)
    .slice(0, 5);
  const maxBacklogClient = parBacklog[0]?.backlog_xof ?? 0;
  const backlogTotalClients = avecBacklog.reduce((s, c) => s + c.backlog_xof, 0);

  return (
    <>
      <Brief
        kicker="Livraison · backlog et fournisseurs"
        headline={`${formatFcfa(margins.stats.backlog_total)} FCFA de backlog à consommer sur ${formatNumber(margins.stats.nb_dossiers_tous_exercices)} dossiers.`}
        lines={briefLines}
        paragraphs={
          briefLines.length
            ? undefined
            : [
                `Le backlog représente ${formatFcfa(margins.stats.backlog_total)} FCFA, pour un taux de matérialisation du CA de ${formatPct(tauxMaterialisation, 0)} %. Le briefing du jour n'est pas encore généré pour ce profil.`,
              ]
        }
        pills={[
          // Le backlog porte sur tous les exercices : le nombre de dossiers qui
          // l'accompagne doit compter la même population, pas celle de l'année.
          { label: `${formatNumber(margins.stats.nb_dossiers_tous_exercices)} dossiers actifs` },
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
          aide="Le travail déjà vendu qui reste à réaliser. C'est votre carnet de commandes : de l'activité assurée, pas encore exécutée."
          value={formatFcfa(margins.stats.backlog_total)}
          unit="FCFA"
          reading={`${formatNumber(margins.stats.nb_dossiers_tous_exercices)} dossiers actifs`}
          detail={{
            kicker: "Indicateur · backlog",
            title: "Backlog restant à consommer (tous exercices)",
            tag: `${formatNumber(margins.stats.nb_dossiers_tous_exercices)} dossiers`,
            tagVariant: "a",
            body: [
              // Toute cette tuile parle du STOCK : les trois montants et le
              // compteur viennent de la même population, tous exercices. Les
              // mélanger avec le CA de l'exercice ferait un écart qui ne tombe
              // pas sur le backlog affiché juste au-dessus.
              `Le backlog correspond à l'écart entre le CA provisoire des dossiers (${formatFcfa(margins.stats.ca_provisoire_tous_exercices)} FCFA) et ce qui a déjà été facturé (${formatFcfa(margins.stats.ca_definitif_tous_exercices)} FCFA).`,
              `Sur cette base, ${formatPct(tauxMaterialisation, 0)} % de la valeur engagée s'est matérialisée en facturation. Le reste est du travail vendu qui n'a pas encore produit de facture.`,
              `Le carnet ne se borne pas à l'exercice : un dossier ouvert avant ${margins.stats.annee} et encore en cours de livraison reste du travail à réaliser aujourd'hui.`,
            ],
            kv: [
              ["CA provisoire (tous exercices)", `${formatFcfa(margins.stats.ca_provisoire_tous_exercices)} FCFA`],
              ["CA définitif (tous exercices)", `${formatFcfa(margins.stats.ca_definitif_tous_exercices)} FCFA`],
              ["Backlog", `${formatFcfa(margins.stats.backlog_total)} FCFA`],
              ["Taux de matérialisation", `${formatPct(tauxMaterialisation, 0)} %`],
              ["Dossiers", formatNumber(margins.stats.nb_dossiers_tous_exercices)],
              [`Dont ouverts en ${margins.stats.annee}`, formatNumber(margins.stats.nb_dossiers)],
            ],
            // note: "Le CA provisoire est la valorisation initiale du dossier commercial, le définitif la valeur réellement facturée à date.",
          }}
        />
        <StatTile
          span={4}
          label="Mois de visibilité"
          aide="Combien de mois d'activité votre carnet de commandes couvre, au rythme actuel. En dessous de quelques mois, il faut vendre pour ne pas avoir d'équipes sans travail."
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
                ? `Le backlog de ${formatFcfa(margins.stats.backlog_total)} FCFA rapporté au rythme de facturation mensuel moyen (${formatFcfa(avgMonthlyRevenue)} FCFA) donne ${formatPct(moisVisibilite, 1)} mois de visibilité.`
                : "Le rythme de facturation mensuel moyen n'est pas calculable sur la période disponible.",
              "Proxy assumé : sans feuilles de temps dans le miroir, la charge réelle des équipes n'est pas mesurable. Ce chiffre mesure la couverture du carnet, pas l'occupation des consultants.",
            ],
            kv: [
              ["Backlog", `${formatFcfa(margins.stats.backlog_total)} FCFA`],
              ["CA mensuel moyen", `${formatFcfa(avgMonthlyRevenue)} FCFA`],
              ["Visibilité", moisVisibilite !== null ? `${formatPct(moisVisibilite, 1)} mois` : "—"],
              ["Seuil interne", "3,0 mois"],
            ],
            // note: "Calcul global, toutes practices confondues : le détail par practice exigerait un référentiel produit normalisé, absent du miroir.",
          }}
        />
        <StatTile
          span={4}
          label="Reste fournisseurs à payer"
          aide="Ce que vous devez encore régler à vos sous-traitants et fournisseurs sur les chantiers en cours."
          value={formatFcfa(margins.stats.fournisseurs_restant)}
          unit="FCFA"
          reading={`${formatNumber(suppliers?.length ?? 0)} fournisseurs suivis`}
          readingVariant="wat"
          detail={{
            kicker: "Indicateur · engagement fournisseur",
            title: "Reste à payer aux fournisseurs",
            tag: `${formatFcfa(margins.stats.fournisseurs_restant)} FCFA`,
            tagVariant: "w",
            body: [
              `Les commandes d'achat engagées laissent ${formatFcfa(margins.stats.fournisseurs_restant)} FCFA à régler.`,
              `À mettre en regard du reste à encaisser client (${formatFcfa(margins.stats.reste_a_encaisser)} FCFA) : c'est l'écart entre les deux qui détermine si la livraison se finance elle-même.`,
            ],
            kv: [
              ["Reste fournisseurs", `${formatFcfa(margins.stats.fournisseurs_restant)} FCFA`],
              ["Reste à encaisser client", `${formatFcfa(margins.stats.reste_a_encaisser)} FCFA`],
              ["Déjà encaissé", `${formatFcfa(margins.stats.total_encaisse)} FCFA`],
            ],
            // note: "Montants issus des commandes d'achat et factures du miroir Odoo.",
          }}
        />

        <Tile
          span={12}
          title="Consommation du backlog vs plan"
          kick="narration"
          aide="Si vous réalisez le travail vendu au rythme prévu, ou si du retard s'accumule."
        >
          <AnalysisSlot load={getMarginsAnalysis} />
          {/* <FootNote>
            Proxy assumé · l&apos;écart entre CA provisoire et définitif signale un décalage réel mais n&apos;en donne
            pas la cause (staffing, périmètre, fournisseur).
          </FootNote> */}
        </Tile>

        <Tile
          span={5}
          title="Cycle de la valeur"
          kick="du devis à l'encaissement"
          aide="Le parcours d'une affaire, du devis jusqu'à l'encaissement, avec ce qui se perd à chaque étape. Montre où la valeur s'évapore."
        >
          {/* Entonnoir CUMULÉ, comme le disent les libellés : les quatre barres
              se lisent en part du CA provisoire de la même population. Deux
              d'entre elles (encaissé, reste à encaisser) sont des stocks tous
              exercices ; les rapporter au CA du seul exercice donnerait des
              parts au-delà de 100 % sans que rien ne soit anormal. */}
          <Bars
            rows={[
              {
                name: "CA provisoire cumulé",
                sub: "valorisation initiale des dossiers",
                value: `${formatFcfa(margins.stats.ca_provisoire_tous_exercices)}`,
                pct: 100,
              },
              {
                name: "CA définitif cumulé",
                sub: `${formatPct(tauxMaterialisation, 0)} % matérialisé`,
                value: `${formatFcfa(margins.stats.ca_definitif_tous_exercices)}`,
                pct: tauxMaterialisation,
                variant: tauxMaterialisation < 60 ? ("w" as const) : ("s" as const),
              },
              {
                name: "Déjà encaissé",
                sub: "règlements reçus",
                value: `${formatFcfa(margins.stats.total_encaisse)}`,
                pct: margins.stats.ca_provisoire_tous_exercices
                  ? (margins.stats.total_encaisse / margins.stats.ca_provisoire_tous_exercices) * 100
                  : 0,
                variant: "s" as const,
              },
              {
                name: "Reste à encaisser",
                sub: "facturé non réglé",
                value: `${formatFcfa(margins.stats.reste_a_encaisser)}`,
                pct: margins.stats.ca_provisoire_tous_exercices
                  ? (margins.stats.reste_a_encaisser / margins.stats.ca_provisoire_tous_exercices) * 100
                  : 0,
                variant: "r" as const,
              },
            ]}
          />
          {/* <FootNote>Toutes les barres sont exprimées en part du CA provisoire cumulé.</FootNote> */}
        </Tile>

        <Tile
          span={7}
          title="Dossiers en dérive"
          kick="CA définitif < 50 % du provisoire"
          aide="Les chantiers qui rapportent beaucoup moins que ce qui était prévu au départ. À examiner un par un : l'écart vient soit du chiffrage, soit de l'exécution."
        >
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
                        `Le dossier « ${d.projet} » a été valorisé à ${formatFcfa(d.ca_provisoire)} FCFA mais seuls ${formatFcfa(d.ca_definitif)} FCFA ont été facturés, soit ${formatPct(avancement, 0)} % de la valeur engagée.`,
                        `La marge passe de ${formatPct(d.perc_marge_prov, 1)} % prévue à ${formatPct(d.perc_marge_def, 1)} % constatée. Un écart de cette ampleur relève soit d'un retard de facturation, soit d'une réduction de périmètre non répercutée au contrat.`,
                      ],
                      kv: [
                        ["CA provisoire", `${formatFcfa(d.ca_provisoire)} FCFA`],
                        ["CA définitif", `${formatFcfa(d.ca_definitif)} FCFA`],
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

        {parBacklog.length > 0 && (
          <Tile
            span={12}
            title="Clients qui portent le plus de backlog"
            kick={`${formatFcfa(backlogTotalClients)} à livrer · ${formatNumber(avecBacklog.length)} comptes concernés`}
            aide="Le travail déjà vendu qui reste à livrer, regroupé par client. Le reste de l'écran raisonne par dossier ; ici on voit à qui l'on doit le plus, ce qui est l'interlocuteur réel quand un délai glisse."
          >
            <HintLine>Cliquez un compte pour sa charge de livraison</HintLine>
            <Bars
              rows={parBacklog.map((c) => {
                const part = backlogTotalClients ? (c.backlog_xof / backlogTotalClients) * 100 : 0;
                return {
                  name: c.client,
                  sub: [
                    `${formatNumber(c.nb_dossiers)} dossier(s)`,
                    `${formatPct(part, 0)} % du backlog`,
                    c.secteur ?? "secteur non renseigné",
                  ].join(" · "),
                  value: `${formatFcfa(c.backlog_xof)}`,
                  pct: maxBacklogClient ? (c.backlog_xof / maxBacklogClient) * 100 : 0,
                  variant: part > 20 ? ("r" as const) : part > 10 ? ("w" as const) : undefined,
                  detail: {
                    kicker: "Compte · charge de livraison",
                    title: c.client,
                    tag:
                      part > 20 ? "concentration forte" : part > 10 ? "à surveiller" : "charge répartie",
                    tagVariant: part > 20 ? ("r" as const) : part > 10 ? ("w" as const) : ("n" as const),
                    body: [
                      `${c.client} porte ${formatFcfa(c.backlog_xof)} FCFA de travail vendu non encore livré, réparti sur ${formatNumber(c.nb_dossiers)} dossier(s), soit ${formatPct(part, 0)} % du backlog total.`,
                      part > 20
                        ? "Un cinquième du carnet dépend de ce seul compte : un décalage de planning chez lui déplace directement la charge de l'ensemble des équipes."
                        : "La charge de ce compte reste absorbable au regard du carnet global.",
                      c.reste_a_encaisser_xof > 0
                        ? `Ce compte laisse par ailleurs ${formatFcfa(c.reste_a_encaisser_xof)} FCFA facturés non réglés — livrer davantage augmente l'exposition tant que ce reste n'est pas encaissé.`
                        : "Ce compte n'a aucun reste à encaisser : livrer ne crée pas d'exposition financière supplémentaire.",
                    ],
                    kv: [
                      ["Backlog à livrer", `${formatFcfa(c.backlog_xof)} FCFA`],
                      ["Part du backlog", `${formatPct(part, 0)} %`],
                      ["Dossiers", formatNumber(c.nb_dossiers)],
                      ["CA total", `${formatFcfa(c.ca_total_xof)} FCFA`],
                      ["Reste à encaisser", `${formatFcfa(c.reste_a_encaisser_xof)} FCFA`],
                      ["Secteur", c.secteur ?? "non renseigné"],
                    ],
                  },
                };
              })}
            />
            <Reste
              affiches={parBacklog.length}
              total={avecBacklog.length}
              nom="comptes avec backlog"
              ou={`${formatFcfa(backlogTotalClients)} FCFA au total`}
            />
            <Note style={{ marginTop: 14 }}>
              Backlog issu des dossiers (CA provisoire moins ce qui est déjà facturé), agrégé par client sur
              les 50 comptes les plus importants du portefeuille.
            </Note>
          </Tile>
        )}

        <Tile
          span={12}
          title="Fiabilité fournisseurs"
          kick="narration"
          aide="Sur qui vous pouvez compter parmi vos sous-traitants, et qui pose des difficultés récurrentes."
        >
          <AnalysisSlot load={getPartnersAnalysis} />
        </Tile>

        {suppliers && suppliers.length > 0 && (
          <Tile
            span={7}
            title="Poids des fournisseurs"
            kick="part des achats"
            aide="La part de vos achats confiée à chaque fournisseur. Un fournisseur trop dominant devient un point de fragilité."
          >
            <HintLine>Cliquez un fournisseur pour son exposition</HintLine>
            <Bars
              rows={suppliers.slice(0, 6).map((s) => ({
                name: s.name,
                sub: `${formatPct(s.taux_dependance_pct, 1)} % des achats · retard moyen ${s.retard_moyen_jours !== null ? `${formatNumber(s.retard_moyen_jours)} j` : "non mesuré"}`,
                value: `${formatFcfa(s.montant_total_xof)}`,
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
                    `${s.name} représente ${formatFcfa(s.montant_total_xof)} FCFA d'achats, soit ${formatPct(s.taux_dependance_pct, 1)} % du total, sur ${formatNumber(s.nb_dossiers_lies)} dossier(s) lié(s).`,
                    s.dossiers_a_risque_fournisseur_unique > 0
                      ? `${formatNumber(s.dossiers_a_risque_fournisseur_unique)} dossier(s) dépendent de ce seul fournisseur : une rupture de sa part bloque directement la livraison client, sans solution de repli identifiée dans le miroir.`
                      : "Aucun dossier ne dépend exclusivement de ce fournisseur, ce qui limite le risque de rupture.",
                  ],
                  kv: [
                    ["Montant acheté", `${formatFcfa(s.montant_total_xof)} FCFA`],
                    ["Dépendance", `${formatPct(s.taux_dependance_pct, 1)} %`],
                    ["Dossiers liés", formatNumber(s.nb_dossiers_lies)],
                    ["Dossiers mono-source", formatNumber(s.dossiers_a_risque_fournisseur_unique)],
                    [
                      "Retard moyen",
                      s.retard_moyen_jours !== null ? `${formatNumber(s.retard_moyen_jours)} jours` : "non mesuré",
                    ],
                    ["Marge de sous-traitance", `${signedFcfa(s.marge_sous_traitance_xof)} FCFA`],
                  ],
                  // note: "Calculé sur les commandes d'achat réelles. Le retard n'est mesurable que si la date de réception est renseignée.",
                },
              }))}
            />
          </Tile>
        )}

        <Tile
          span={5}
          title="Tension sur la sous-traitance"
          kick="M4"
          aide="Les endroits où la sous-traitance risque de manquer ou de coûter plus cher que prévu."
        >
          {risquesSousTraitance.length > 0 ? (
            <Lst
              items={risquesSousTraitance.map((s) => ({
                title: s.name,
                sub: `${formatNumber(s.nb_dossiers_lies)} dossier(s) · marge ${signedFcfa(s.marge_sous_traitance_xof)}`,
                tag: s.dossiers_a_risque_fournisseur_unique > 0 ? "mono-source" : "à surveiller",
                tagVariant: s.dossiers_a_risque_fournisseur_unique > 0 ? ("r" as const) : ("n" as const),
                detail: {
                  kicker: "Risque de sous-traitance",
                  title: s.name,
                  tag: s.dossiers_a_risque_fournisseur_unique > 0 ? "mono-source" : "dépendance élevée",
                  tagVariant: s.dossiers_a_risque_fournisseur_unique > 0 ? ("r" as const) : ("w" as const),
                  body: [
                    `Ce fournisseur porte ${formatPct(s.taux_dependance_pct, 1)} % des achats sur ${formatNumber(s.nb_dossiers_lies)} dossier(s), pour une marge de sous-traitance de ${signedFcfa(s.marge_sous_traitance_xof)} FCFA.`,
                    s.dossiers_a_risque_fournisseur_unique > 0
                      ? "Sans second fournisseur référencé sur ces dossiers, la continuité de livraison repose sur lui seul. Une clause de continuité ou un fournisseur alternatif est la parade habituelle."
                      : "La dépendance dépasse le seuil de 10 % des achats sans être mono-source : le risque est financier plus que technique.",
                  ],
                  kv: [
                    ["Dépendance", `${formatPct(s.taux_dependance_pct, 1)} %`],
                    ["Dossiers liés", formatNumber(s.nb_dossiers_lies)],
                    ["Dossiers mono-source", formatNumber(s.dossiers_a_risque_fournisseur_unique)],
                    ["Marge de sous-traitance", `${signedFcfa(s.marge_sous_traitance_xof)} FCFA`],
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
