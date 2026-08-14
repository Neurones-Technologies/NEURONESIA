import { getComptesDc } from "@/lib/api/commercial";
import { formatDate, formatMFcfa, formatNumber, formatPct } from "@/lib/format";
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
  const comptes = await getComptesDc(20);

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

  return (
    <>
      <div className="kpi-row">
        {/* Le CA cumulé du portefeuille est l'assiette de l'écran : c'est lui
            qu'on vient situer, le pipe et les divergences le qualifient. */}
        <StatTile
          span={4}
          rang="principal"
          label="CA réalisé du portefeuille"
          value={formatMFcfa(top.totaux.ca_realise_xof)}
          unit="M FCFA historiques"
          reading={`${formatNumber(top.totaux.nb_comptes_classes)} comptes classés · top affiché = ${formatPct(top.totaux.part_ca_top_pct, 0)} % du CA`}
          detail={{
            kicker: "Indicateur · poids du réalisé",
            title: "Chiffre d'affaires cumulé des comptes classés",
            tag: "mesuré",
            tagVariant: "s",
            body: [
              `${formatNumber(top.totaux.nb_comptes_classes)} comptes portent un CA réalisé ou des opportunités à venir, pour ${formatMFcfa(top.totaux.ca_realise_xof)} M FCFA de commandes signées cumulées sur toute leur histoire.`,
              `Le top affiché concentre ${formatPct(top.totaux.part_ca_top_pct, 0)} % de ce CA : c'est la mesure de concentration du portefeuille, à lire avec le nombre de comptes qu'elle représente.`,
            ],
            kv: [
              ["Comptes classés", formatNumber(top.totaux.nb_comptes_classes)],
              ["CA réalisé cumulé", `${formatMFcfa(top.totaux.ca_realise_xof)} M FCFA`],
              ["Part du top affiché", `${formatPct(top.totaux.part_ca_top_pct, 0)} %`],
            ],
          }}
        />
        <StatTile
          span={4}
          label="Pipe à venir"
          value={formatMFcfa(top.totaux.pipe_a_venir_xof)}
          unit="M FCFA d'opportunités ouvertes"
          reading={`top affiché = ${formatPct(top.totaux.part_pipe_top_pct, 0)} % du pipe à venir`}
          detail={{
            kicker: "Indicateur · poids du futur",
            title: "Opportunités ouvertes dont l'échéance n'est pas passée",
            tag: "mesuré",
            tagVariant: "s",
            body: [
              `${formatMFcfa(top.totaux.pipe_a_venir_xof)} M FCFA d'opportunités ouvertes portent une échéance encore devant elles.`,
              "Les opportunités à échéance DÉPASSÉE sont comptées séparément et jamais dans ce total : les mêmes affaires servaient déjà de prévision à un trimestre révolu, et les compter comme du futur gonflerait le classement des comptes les moins bien tenus.",
            ],
            kv: [
              ["Pipe à venir", `${formatMFcfa(top.totaux.pipe_a_venir_xof)} M FCFA`],
              ["Part du top affiché", `${formatPct(top.totaux.part_pipe_top_pct, 0)} %`],
            ],
          }}
        />
        <StatTile
          span={4}
          rang="contexte"
          label="Comptes à lecture divergente"
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
        >
          <HintLine>Cliquez un compte pour ses quatre mesures</HintLine>
          <Bars
            rows={top.comptes.map((c) => ({
              name: c.compte,
              sub: [
                `${formatNumber(c.nb_commandes)} commandes`,
                `${formatNumber(c.nb_opp_a_venir)} opportunités à venir (${formatMFcfa(c.pipe_a_venir_xof)} M)`,
                c.lecture_divergente ? "lecture divergente" : null,
                c.alerte_impaye ? "impayé échu" : null,
              ]
                .filter(Boolean)
                .join(" · "),
              value: `${formatMFcfa(c.ca_realise_xof)} M`,
              pct: (c.ca_realise_xof / maxCa) * 100,
              variant: c.alerte_impaye ? ("r" as const) : c.lecture_divergente ? ("w" as const) : undefined,
              detail: {
                kicker: "Compte · classement combiné",
                title: c.compte,
                tag: `indice ${formatPct(c.indice_combine, 0)}`,
                tagVariant: c.lecture_divergente ? ("w" as const) : ("a" as const),
                body: [
                  `Réalisé : ${formatMFcfa(c.ca_realise_xof)} M FCFA sur ${formatNumber(c.nb_commandes)} commandes, panier moyen ${formatMFcfa(c.panier_moyen_xof)} M FCFA. À venir : ${formatNumber(c.nb_opp_a_venir)} opportunités ouvertes pour ${formatMFcfa(c.pipe_a_venir_xof)} M FCFA.`,
                  c.lecture_divergente
                    ? `Ce compte se juge différemment selon la dimension : ${formatPct(c.indice_montant, 0)} en montant contre ${formatPct(c.indice_quantite, 0)} en quantité. ${c.indice_montant > c.indice_quantite ? "Peu d'affaires, mais grosses — sa perte se voit immédiatement dans le chiffre." : "Beaucoup d'affaires, mais petites — sa perte se voit dans la charge, pas tout de suite dans le chiffre."}`
                    : `Les deux lectures concordent (${formatPct(c.indice_montant, 0)} en montant, ${formatPct(c.indice_quantite, 0)} en quantité) : le rang de ce compte ne dépend pas de la dimension regardée.`,
                  c.nb_opp_echues > 0
                    ? `${formatNumber(c.nb_opp_echues)} opportunité(s) de ce compte portent une échéance déjà dépassée pour ${formatMFcfa(c.pipe_echu_xof)} M FCFA : elles ne sont PAS comptées dans le pipe à venir ci-dessus, mais elles pèsent encore dans le forecast.`
                    : "Aucune opportunité de ce compte ne porte d'échéance dépassée.",
                  c.alerte_impaye
                    ? "Ce compte porte un impayé échu : toute relance commerciale se coordonne avec la Direction Financière."
                    : "",
                ].filter(Boolean),
                kv: [
                  ["CA réalisé", `${formatMFcfa(c.ca_realise_xof)} M FCFA`],
                  ["Commandes", formatNumber(c.nb_commandes)],
                  ["Panier moyen", `${formatMFcfa(c.panier_moyen_xof)} M FCFA`],
                  ["Opportunités à venir", formatNumber(c.nb_opp_a_venir)],
                  ["Pipe à venir", `${formatMFcfa(c.pipe_a_venir_xof)} M FCFA`],
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
          >
            <HintLine>Cliquez un compte pour voir l&apos;écart entre ses deux lectures</HintLine>
            <Lst
              items={divergents.map((c) => ({
                title: c.compte,
                sub: `${formatPct(c.indice_montant, 0)} en montant contre ${formatPct(c.indice_quantite, 0)} en quantité · ${formatNumber(c.nb_commandes)} commandes pour ${formatMFcfa(c.ca_realise_xof)} M`,
                tag: c.indice_montant > c.indice_quantite ? "gros tickets" : "volume",
                tagVariant: "w" as const,
                detail: {
                  kicker: "Compte · lecture divergente",
                  title: c.compte,
                  tag: `${formatPct(Math.abs(c.ecart_lecture), 0)} points d'écart`,
                  tagVariant: "w" as const,
                  body: [
                    c.indice_montant > c.indice_quantite
                      ? `Ce compte pèse lourd en montant (${formatPct(c.indice_montant, 0)}) et peu en quantité (${formatPct(c.indice_quantite, 0)}) : ${formatMFcfa(c.ca_realise_xof)} M FCFA sur seulement ${formatNumber(c.nb_commandes)} commandes. Un classement au nombre d'affaires le ferait disparaître, alors que sa perte se verrait immédiatement dans le chiffre.`
                      : `Ce compte pèse en quantité (${formatPct(c.indice_quantite, 0)}) plus qu'en montant (${formatPct(c.indice_montant, 0)}) : ${formatNumber(c.nb_commandes)} commandes pour ${formatMFcfa(c.ca_realise_xof)} M FCFA. Un classement au CA le ferait disparaître, alors qu'il occupe l'équipe.`,
                    `Panier moyen : ${formatMFcfa(c.panier_moyen_xof)} M FCFA.`,
                  ],
                  kv: [
                    ["Indice montant", formatPct(c.indice_montant, 0)],
                    ["Indice quantité", formatPct(c.indice_quantite, 0)],
                    ["Écart", `${formatPct(c.ecart_lecture, 0)} points`],
                    ["CA réalisé", `${formatMFcfa(c.ca_realise_xof)} M FCFA`],
                    ["Commandes", formatNumber(c.nb_commandes)],
                    ["Panier moyen", `${formatMFcfa(c.panier_moyen_xof)} M FCFA`],
                  ],
                },
              }))}
            />
          </Tile>
        )}
      </Bento>
    </>
  );
}
