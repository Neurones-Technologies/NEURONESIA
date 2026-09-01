import { getComptesDc } from "@/lib/api/commercial";
import { getSupplierIntelligence } from "@/lib/api/partners";
import { formatDate, formatFcfa, formatNumber, formatPct, signedFcfa } from "@/lib/format";
import { Bars, Bento, HintLine, Lst, Reste, StatTile, Tile } from "@/components/ui/bento";
import { Note } from "@/components/ui/primitives";

/** « Comptes par ventes » — chapitre 2 du compte-rendu DC.
 *
 * « Identifier les comptes générant le plus de ventes […]. Ces indicateurs doivent
 * être restitués en quantité et en montant simultanément — l'un des deux seuls ne
 * suffit pas à qualifier un compte. »
 *
 * L'écran prend cette exigence au mot : les quatre mesures brutes sont affichées
 * (CA réalisé, nombre de commandes, pipe à venir, nombre d'opportunités), et
 * l'indice qui les combine le fait par RANG et jamais par somme — additionner des
 * francs et des unités ne veut rien dire.
 *
 * Les comptes dont les deux lectures divergent sont signalés : ce sont exactement
 * ceux qu'un classement à une seule dimension aurait mal jugés, donc ceux qui
 * justifient la demande du DC.
 */
export async function DcComptes() {
  const [comptes, fournisseurs] = await Promise.all([getComptesDc(20), getSupplierIntelligence(30)]);

  if (!comptes) {
    return (
      <Bento>
        <Tile span={12} title="Comptes par ventes">
          <Note style={{ marginTop: 0 }}>
            Le classement des comptes n&apos;est pas accessible depuis ce profil.
          </Note>
        </Tile>
      </Bento>
    );
  }

  const { top_comptes: top } = comptes;
  const maxCa = Math.max(...top.comptes.map((c) => c.ca_realise_xof), 1);
  const divergents = top.comptes.filter((c) => c.lecture_divergente);

  // Partenaires qui font gagner le plus de marge de revente. Le DC ne pilote pas
  // les achats — il regarde ces lignes pour savoir avec QUI la revente est
  // rentable, l'exécution restant l'affaire des opérations.
  //
  // Les partenaires sans marge mesurable sont écartés plutôt que classés à zéro :
  // une marge nulle ne distingue pas « revente à prix coûtant » de « aucun dossier
  // rapproché », et mélanger les deux ferait remonter du vide dans un classement.
  const marges = (fournisseurs ?? []).filter((f) => f.marge_sous_traitance_xof !== 0);
  const topMarges = marges
    .slice()
    .sort((a, b) => b.marge_sous_traitance_xof - a.marge_sous_traitance_xof)
    .slice(0, 5);
  // L'échelle des barres est prise sur la plus forte marge EN VALEUR ABSOLUE :
  // une marge négative doit tracer une barre comparable à une positive de même
  // ampleur, sinon la perte se lit comme un détail.
  const maxMarge = Math.max(...topMarges.map((f) => Math.abs(f.marge_sous_traitance_xof)), 1);

  return (
    <>
      <div className="kpi-row">
        {/* Le CA cumulé du portefeuille est l'assiette de l'écran : c'est lui
            qu'on vient situer, le pipe et les divergences le qualifient. */}
        <StatTile
          span={4}
          rang="principal"
          label={`CA réalisé du portefeuille — ${top.annee}`}
          aide={`Ce que vos clients vous ont acheté depuis le 1er janvier ${top.annee}. C'est de l'argent commandé et signé, pas des affaires en cours.`}
          value={formatFcfa(top.totaux.ca_realise_xof)}
          unit={`FCFA sur l'exercice ${top.annee}`}
          reading={`${formatNumber(top.totaux.nb_comptes_classes)} comptes classés · top affiché = ${formatPct(top.totaux.part_ca_top_pct, 0)} % du CA`}
          detail={{
            kicker: `Indicateur · poids du réalisé · exercice ${top.annee}`,
            title: `Chiffre d'affaires ${top.annee} des comptes classés`,
            tag: "mesuré",
            tagVariant: "s",
            body: [
              `${formatNumber(top.totaux.nb_comptes_classes)} comptes portent une commande signée en ${top.annee} ou des opportunités à venir, pour ${formatFcfa(top.totaux.ca_realise_xof)} FCFA commandés sur l'exercice.`,
              // Le cumul depuis 2019 reste affiché, mais comme CONTEXTE et
              // nommé comme tel : c'est le rapport entre les deux qui se lit
              // (quelle part de la relation client s'est jouée cette année),
              // pas le gros chiffre pris pour celui de l'exercice.
              `Ces mêmes comptes ont commandé ${formatFcfa(top.totaux.ca_historique_xof)} FCFA depuis l'origine du miroir : l'exercice en cours en représente ${formatPct(top.totaux.ca_historique_xof ? (top.totaux.ca_realise_xof / top.totaux.ca_historique_xof) * 100 : null, 0)} %.`,
              `Le top affiché concentre ${formatPct(top.totaux.part_ca_top_pct, 0)} % du CA de l'exercice : c'est la mesure de concentration du portefeuille, à lire avec le nombre de comptes qu'elle représente.`,
              // Un compte sans commande cette année n'est pas perdu : il sort de
              // ce classement et relève de la dormance, qui le lit sur son
              // silence. Le dire ici évite de croire à une disparition.
              `Les comptes sans commande en ${top.annee} et sans pipe ne sont pas classés ici : ils relèvent de l'onglet « Base installée », qui les suit sur leur durée de silence.`,
            ],
            kv: [
              ["Comptes classés", formatNumber(top.totaux.nb_comptes_classes)],
              [`CA commandé ${top.annee}`, `${formatFcfa(top.totaux.ca_realise_xof)} FCFA`],
              ["CA cumulé depuis l'origine", `${formatFcfa(top.totaux.ca_historique_xof)} FCFA`],
              ["Part du top affiché", `${formatPct(top.totaux.part_ca_top_pct, 0)} %`],
            ],
          }}
        />
        <StatTile
          span={4}
          label="Pipe à venir"
          aide="Les affaires encore en discussion chez ces clients. Rien n'est signé : c'est ce qui pourrait rentrer, pas ce qui est acquis."
          value={formatFcfa(top.totaux.pipe_a_venir_xof)}
          unit="FCFA d'opportunités ouvertes"
          reading={`top affiché = ${formatPct(top.totaux.part_pipe_top_pct, 0)} % du pipe à venir`}
          detail={{
            kicker: "Indicateur · poids du futur",
            title: "Opportunités ouvertes dont l'échéance n'est pas passée",
            tag: "mesuré",
            tagVariant: "s",
            body: [
              `${formatFcfa(top.totaux.pipe_a_venir_xof)} FCFA d'opportunités ouvertes portent une échéance encore devant elles.`,
              "Les opportunités à échéance DÉPASSÉE sont comptées séparément et jamais dans ce total : les mêmes affaires servaient déjà de prévision à un trimestre révolu, et les compter comme du futur gonflerait le classement des comptes les moins bien tenus.",
            ],
            kv: [
              ["Pipe à venir", `${formatFcfa(top.totaux.pipe_a_venir_xof)} FCFA`],
              ["Part du top affiché", `${formatPct(top.totaux.part_pipe_top_pct, 0)} %`],
            ],
          }}
        />
        <StatTile
          span={4}
          rang="contexte"
          label="Comptes à lecture divergente"
          aide="Les clients qui changent de rang selon qu'on les classe au nombre de commandes ou au montant. Beaucoup de petites commandes ou une grosse : ce ne sont pas les mêmes clients, ni la même façon de les suivre."
          value={formatNumber(top.totaux.nb_lectures_divergentes)}
          unit="jugés différemment selon l'axe"
          reading="quantité et montant ne disent pas la même chose"
          readingVariant={top.totaux.nb_lectures_divergentes > 0 ? "wat" : undefined}
          detail={{
            kicker: "Indicateur · pourquoi les deux axes",
            title: "Comptes qui changent de rang selon la dimension",
            tag: `${formatNumber(top.totaux.nb_lectures_divergentes)} comptes`,
            tagVariant: "w",
            body: [
              `${formatNumber(top.totaux.nb_lectures_divergentes)} comptes présentent plus de 25 points d'écart entre leur rang en montant et leur rang en quantité.`,
              "C'est la démonstration chiffrée de la demande du compte-rendu : sur ces comptes, un classement à une seule dimension se tromperait. Beaucoup de petites commandes ne pèsent pas comme deux grosses, et l'inverse est vrai en charge de travail.",
              "L'indice combiné est calculé sur les RANGS des quatre mesures, jamais sur une somme : additionner des francs et des unités n'aurait pas de sens.",
            ],
            kv: [
              ["Lectures divergentes", formatNumber(top.totaux.nb_lectures_divergentes)],
              ["Comptes classés", formatNumber(top.totaux.nb_comptes_classes)],
              ["Seuil d'écart", "25 points de rang"],
            ],
          }}
        />
      </div>

      <Bento>
        <Tile
          span={12}
          title="Comptes générant le plus de ventes — en quantité et en montant"
          kick={`${formatNumber(top.totaux.nb_comptes_classes)} comptes classés`}
          aide="Vos meilleurs clients, classés deux fois : par nombre de commandes et par montant. Les deux listes ne se recouvrent pas, et c'est justement ce qu'il faut regarder."
        >
          <HintLine>Cliquez un compte pour ses quatre mesures</HintLine>
          <Bars
            rows={top.comptes.map((c) => ({
              name: c.compte,
              sub: [
                `${formatNumber(c.nb_commandes)} commandes en ${top.annee}`,
                `${formatNumber(c.nb_opp_a_venir)} opportunités à venir (${formatFcfa(c.pipe_a_venir_xof)})`,
                c.lecture_divergente ? "lecture divergente" : null,
                c.alerte_impaye ? "impayé échu" : null,
              ]
                .filter(Boolean)
                .join(" · "),
              value: `${formatFcfa(c.ca_realise_xof)}`,
              pct: (c.ca_realise_xof / maxCa) * 100,
              variant: c.alerte_impaye ? ("r" as const) : c.lecture_divergente ? ("w" as const) : undefined,
              detail: {
                kicker: "Compte · classement combiné",
                title: c.compte,
                tag: `indice ${formatPct(c.indice_combine, 0)}`,
                tagVariant: c.lecture_divergente ? ("w" as const) : ("a" as const),
                body: [
                  `Réalisé ${top.annee} : ${formatFcfa(c.ca_realise_xof)} FCFA sur ${formatNumber(c.nb_commandes)} commandes, panier moyen ${formatFcfa(c.panier_moyen_xof)} FCFA. À venir : ${formatNumber(c.nb_opp_a_venir)} opportunités ouvertes pour ${formatFcfa(c.pipe_a_venir_xof)} FCFA.`,
                  // Le cumul situe la relation : 111 M cette année sur un compte
                  // qui en a fait 1 912 depuis 2019 n'est pas le même signal que
                  // le même montant chez un compte ouvert cette année.
                  `Depuis l'origine du miroir, ce compte a commandé ${formatFcfa(c.ca_historique_xof)} FCFA sur ${formatNumber(c.nb_commandes_historique)} commandes.`,
                  c.lecture_divergente
                    ? `Ce compte se juge différemment selon la dimension : ${formatPct(c.indice_montant, 0)} en montant contre ${formatPct(c.indice_quantite, 0)} en quantité. ${c.indice_montant > c.indice_quantite ? "Peu d'affaires, mais grosses — sa perte se voit immédiatement dans le chiffre." : "Beaucoup d'affaires, mais petites — sa perte se voit dans la charge, pas tout de suite dans le chiffre."}`
                    : `Les deux lectures concordent (${formatPct(c.indice_montant, 0)} en montant, ${formatPct(c.indice_quantite, 0)} en quantité) : le rang de ce compte ne dépend pas de la dimension regardée.`,
                  c.nb_opp_echues > 0
                    ? `${formatNumber(c.nb_opp_echues)} opportunité(s) de ce compte portent une échéance déjà dépassée pour ${formatFcfa(c.pipe_echu_xof)} FCFA : elles ne sont PAS comptées dans le pipe à venir ci-dessus, mais elles pèsent encore dans le forecast.`
                    : "Aucune opportunité de ce compte ne porte d'échéance dépassée.",
                  c.alerte_impaye
                    ? "Ce compte porte un impayé échu : toute relance commerciale se coordonne avec la Direction Financière."
                    : "",
                ].filter(Boolean),
                kv: [
                  [`CA réalisé ${top.annee}`, `${formatFcfa(c.ca_realise_xof)} FCFA`],
                  [`Commandes ${top.annee}`, formatNumber(c.nb_commandes)],
                  ["CA cumulé depuis l'origine", `${formatFcfa(c.ca_historique_xof)} FCFA`],
                  ["Panier moyen", `${formatFcfa(c.panier_moyen_xof)} FCFA`],
                  ["Opportunités à venir", formatNumber(c.nb_opp_a_venir)],
                  ["Pipe à venir", `${formatFcfa(c.pipe_a_venir_xof)} FCFA`],
                  ["Opportunités échues", formatNumber(c.nb_opp_echues)],
                  ["Indice montant", formatPct(c.indice_montant, 0)],
                  ["Indice quantité", formatPct(c.indice_quantite, 0)],
                  ["Dernière commande", formatDate(c.derniere_commande)],
                  ["Commercial rattaché", c.commercial || "non renseigné"],
                ],
              },
            }))}
          />
          {/* Le `kick` annonce 650 comptes classés, la liste en montre 20 : sans
              cette ligne, l'écart ne se lit nulle part. */}
          <Reste
            affiches={top.comptes.length}
            total={top.totaux.nb_comptes_classes}
            nom="comptes"
            ou={`top affiché = ${formatPct(top.totaux.part_ca_top_pct, 0)} % du CA`}
          />
          <Note style={{ marginTop: 14 }}>{top.note}</Note>
        </Tile>

        {divergents.length > 0 && (
          <Tile
            span={12}
            title="Comptes à lire sur les deux axes"
            kick={`${formatNumber(divergents.length)} affichés`}
            aide="Le détail des clients qui montent d'un côté et descendent de l'autre. Un client très présent mais peu rentable, ou l'inverse : chacun appelle une conduite différente."
          >
            <HintLine>Cliquez un compte pour voir l&apos;écart entre ses deux lectures</HintLine>
            <Lst
              items={divergents.map((c) => ({
                title: c.compte,
                sub: `${formatPct(c.indice_montant, 0)} en montant contre ${formatPct(c.indice_quantite, 0)} en quantité · ${formatNumber(c.nb_commandes)} commandes pour ${formatFcfa(c.ca_realise_xof)}`,
                tag: c.indice_montant > c.indice_quantite ? "gros tickets" : "volume",
                tagVariant: "w" as const,
                detail: {
                  kicker: "Compte · lecture divergente",
                  title: c.compte,
                  tag: `${formatPct(Math.abs(c.ecart_lecture), 0)} points d'écart`,
                  tagVariant: "w" as const,
                  body: [
                    c.indice_montant > c.indice_quantite
                      ? `Ce compte pèse lourd en montant (${formatPct(c.indice_montant, 0)}) et peu en quantité (${formatPct(c.indice_quantite, 0)}) : ${formatFcfa(c.ca_realise_xof)} FCFA sur seulement ${formatNumber(c.nb_commandes)} commandes. Un classement au nombre d'affaires le ferait disparaître, alors que sa perte se verrait immédiatement dans le chiffre.`
                      : `Ce compte pèse en quantité (${formatPct(c.indice_quantite, 0)}) plus qu'en montant (${formatPct(c.indice_montant, 0)}) : ${formatNumber(c.nb_commandes)} commandes pour ${formatFcfa(c.ca_realise_xof)} FCFA. Un classement au CA le ferait disparaître, alors qu'il occupe l'équipe.`,
                    `Panier moyen : ${formatFcfa(c.panier_moyen_xof)} FCFA.`,
                  ],
                  kv: [
                    ["Indice montant", formatPct(c.indice_montant, 0)],
                    ["Indice quantité", formatPct(c.indice_quantite, 0)],
                    ["Écart", `${formatPct(c.ecart_lecture, 0)} points`],
                    ["CA réalisé", `${formatFcfa(c.ca_realise_xof)} FCFA`],
                    ["Commandes", formatNumber(c.nb_commandes)],
                    ["Panier moyen", `${formatFcfa(c.panier_moyen_xof)} FCFA`],
                  ],
                },
              }))}
            />
          </Tile>
        )}

        {topMarges.length > 0 && (
          <Tile
            span={12}
            title="Partenaires qui rapportent le plus"
            kick={`marge de revente · ${formatNumber(marges.length)} partenaires mesurés`}
            aide="Ce que vous gagnez en revendant la prestation de chaque partenaire. Une marge négative signale une revente à perte : le dossier a été vendu moins cher qu'il n'a coûté."
          >
            <HintLine>Cliquez un partenaire pour le détail de sa marge</HintLine>
            <Bars
              rows={topMarges.map((f) => {
                const perte = f.marge_sous_traitance_xof < 0;
                return {
                  name: f.name,
                  sub: [
                    `${formatNumber(f.nb_dossiers_lies)} dossier(s) lié(s)`,
                    `${formatFcfa(f.montant_total_xof)} achetés`,
                    `${formatPct(f.taux_dependance_pct, 1)} % des achats`,
                  ].join(" · "),
                  value: `${signedFcfa(f.marge_sous_traitance_xof)}`,
                  pct: (Math.abs(f.marge_sous_traitance_xof) / maxMarge) * 100,
                  variant: perte ? ("r" as const) : ("s" as const),
                  detail: {
                    kicker: "Partenaire · marge de revente",
                    title: f.name,
                    tag: perte ? "revente à perte" : "marge positive",
                    tagVariant: perte ? ("r" as const) : ("s" as const),
                    body: [
                      `La revente des prestations de ${f.name} dégage ${signedFcfa(f.marge_sous_traitance_xof)} FCFA, sur ${formatNumber(f.nb_dossiers_lies)} dossier(s) et ${formatFcfa(f.montant_total_xof)} FCFA d'achats.`,
                      perte
                        ? "La marge est négative : sur ces dossiers, ce qui a été facturé au client est inférieur à ce qui a été acheté au partenaire. À reprendre au chiffrage — c'est une décision commerciale, pas un problème d'exécution."
                        : "La revente est rentable sur le périmètre rapproché. C'est un partenaire sur lequel s'appuyer pour construire une offre.",
                      "La marge rapproche les achats et la facturation d'un même dossier. Elle ne couvre donc que les dossiers où les deux sont renseignés — un partenaire mal rapproché apparaît plus bas qu'il ne l'est réellement.",
                    ],
                    kv: [
                      ["Marge de revente", `${signedFcfa(f.marge_sous_traitance_xof)} FCFA`],
                      ["Montant acheté", `${formatFcfa(f.montant_total_xof)} FCFA`],
                      ["Dossiers liés", formatNumber(f.nb_dossiers_lies)],
                      ["Part des achats", `${formatPct(f.taux_dependance_pct, 1)} %`],
                      ["Commandes", formatNumber(f.nb_commandes)],
                    ],
                  },
                };
              })}
            />
            <Reste affiches={topMarges.length} total={marges.length} nom="partenaires" />
            <Note style={{ marginTop: 14 }}>
              Les achats du miroir ne remontent qu&apos;à 2024, alors que les ventes remontent à 2021 : ce
              classement porte sur une histoire plus courte que celle des comptes ci-dessus.
            </Note>
          </Tile>
        )}
      </Bento>
    </>
  );
}
