import { getAlertes, getComptesDc } from "@/lib/api/commercial";
import { formatDate, formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, HintLine, Lst, StatTile, Tile } from "@/components/ui/bento";
import { Note } from "@/components/ui/primitives";
import { SEVERITE_TAG } from "./source";

/** Onglet « Comptes et animation » — §1 et §2 du compte-rendu DC.
 *
 * Trois demandes du DC réunies parce qu'elles se lisent ensemble : quels comptes
 * vendent, lesquels s'emballent, lesquels arrivent.
 *
 * Le classement obéit à une exigence explicite du CR : « ces indicateurs doivent
 * être restitués en quantité et en montant simultanément — l'un des deux seuls ne
 * suffit pas à qualifier un compte ». Les quatre mesures brutes sont donc toutes
 * affichées, et les comptes dont les deux lectures divergent sont signalés : ce
 * sont ceux qu'un classement à une seule dimension aurait mal jugés.
 *
 * Sur les pics, ce que l'écran doit dire et redire : seul le rythme de COMMANDE
 * est mesurable. Le pic par sollicitation (devis, rendez-vous, appels) n'existe
 * pas dans le miroir, et la détection ne couvre que les comptes ayant assez
 * d'historique pour qu'une médiane ait un sens.
 */
export async function DcComptes() {
  const [comptes, alertes] = await Promise.all([getComptesDc(20), getAlertes(12)]);

  if (!comptes) {
    return (
      <Bento>
        <Tile span={12} title="Comptes et animation">
          <Note style={{ marginTop: 0 }}>
            L&apos;animation de compte n&apos;est pas accessible depuis ce profil.
          </Note>
        </Tile>
      </Bento>
    );
  }

  const { top_comptes: top, pics, acquisition } = comptes;
  const maxCa = Math.max(...top.comptes.map((c) => c.ca_realise_xof), 1);
  const maxAcq = Math.max(...acquisition.annees.map((a) => a.nb_comptes), 1);

  return (
    <>
      <div className="kpi-row">
        <StatTile
          span={4}
          label="Pics d'activité détectés"
          value={formatNumber(pics.couverture.nb_pics)}
          unit={`sur ${formatNumber(pics.fenetre_mois.length)} mois`}
          reading={`${formatNumber(pics.couverture.nb_comptes_eligibles)} comptes mesurables sur ${formatNumber(pics.couverture.nb_comptes_avec_commande)}`}
          readingVariant={pics.couverture.nb_pics > 0 ? "wat" : undefined}
          detail={{
            kicker: "Indicateur · détection de pic",
            title: "Comptes dont le rythme de commande s'emballe",
            tag: `× ${pics.seuils.facteur} la médiane`,
            tagVariant: "w",
            body: [
              `${formatNumber(pics.couverture.nb_pics)} pic(s) détecté(s) sur la fenêtre ${pics.fenetre_mois[0]} → ${pics.fenetre_mois[pics.fenetre_mois.length - 1]}. Un mois est un pic quand il pèse au moins ${pics.seuils.facteur} fois la médiane mensuelle du compte lui-même.`,
              `La détection ne couvre que ${formatNumber(pics.couverture.nb_comptes_eligibles)} comptes sur ${formatNumber(pics.couverture.nb_comptes_avec_commande)} ayant déjà commandé (${formatPct(pics.couverture.part_eligible_pct, 0)} %) : sous ${pics.seuils.min_commandes} commandes, une médiane n'a pas de sens statistique et le compte est déclaré non éligible plutôt que jugé sur deux points.`,
              pics.note,
            ],
            kv: [
              ["Pics détectés", formatNumber(pics.couverture.nb_pics)],
              ["Comptes éligibles", formatNumber(pics.couverture.nb_comptes_eligibles)],
              ["Part du portefeuille mesurable", `${formatPct(pics.couverture.part_eligible_pct, 0)} %`],
              ["Facteur de déclenchement", `× ${pics.seuils.facteur}`],
              ["Plancher de montant", `${formatMFcfa(pics.seuils.montant_plancher_xof)} M FCFA`],
            ],
          }}
        />
        <StatTile
          span={4}
          label={`Nouveaux comptes ${acquisition.annee_courante.annee}`}
          value={formatNumber(acquisition.annee_courante.nb_comptes)}
          unit="premières commandes"
          reading={`${formatNumber(acquisition.annee_courante.nb_comptes_annee_precedente)} sur l'exercice précédent complet`}
          detail={{
            kicker: "Indicateur · acquisition",
            title: "Comptes entrés en portefeuille cette année",
            tag: "mesuré",
            tagVariant: "s",
            body: [
              `${formatNumber(acquisition.annee_courante.nb_comptes)} comptes ont passé leur première commande en ${acquisition.annee_courante.annee}, pour ${formatMFcfa(acquisition.annee_courante.ca_xof)} M FCFA de CA cumulé depuis leur entrée.`,
              `L'exercice précédent en a compté ${formatNumber(acquisition.annee_courante.nb_comptes_annee_precedente)} sur douze mois complets : la comparaison n'est valable qu'à date équivalente.`,
              acquisition.note,
            ],
            kv: [
              ["Nouveaux comptes", formatNumber(acquisition.annee_courante.nb_comptes)],
              ["CA cumulé associé", `${formatMFcfa(acquisition.annee_courante.ca_xof)} M FCFA`],
              ["Exercice précédent", formatNumber(acquisition.annee_courante.nb_comptes_annee_precedente)],
            ],
          }}
        />
        <StatTile
          span={4}
          label="Vivier de prospects"
          value={formatNumber(acquisition.vivier.nb_prospects)}
          unit="jamais commandé"
          reading={`${formatNumber(acquisition.vivier.nb_comptes_avec_commande)} comptes ont déjà commandé`}
          detail={{
            kicker: "Indicateur · vivier",
            title: "Comptes du référentiel n'ayant jamais commandé",
            tag: "prospects",
            tagVariant: "n",
            body: [
              `${formatNumber(acquisition.vivier.nb_prospects)} comptes existent dans le référentiel clients sans avoir jamais passé de commande. Ce ne sont pas des clients perdus : ce sont des prospects.`,
              `${formatNumber(acquisition.vivier.nb_comptes_avec_commande)} comptes ont, eux, au moins une commande signée. C'est sur ceux-là seulement que le rythme, donc un pic ou un décrochage, est mesurable.`,
            ],
            kv: [
              ["Prospects", formatNumber(acquisition.vivier.nb_prospects)],
              ["Comptes clients", formatNumber(acquisition.vivier.nb_comptes_avec_commande)],
            ],
          }}
        />
      </div>

      <Bento>
        <Tile
          span={12}
          title="Comptes qui vendent le plus — en quantité et en montant"
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
                  ["Indice montant", formatPct(c.indice_montant, 0)],
                  ["Indice quantité", formatPct(c.indice_quantite, 0)],
                  ["Dernière commande", formatDate(c.derniere_commande)],
                  ["Commercial rattaché", c.commercial || "non renseigné"],
                ],
              },
            }))}
          />
          <Note style={{ marginTop: 14 }}>
            {top.note} Sur ce portefeuille, {formatNumber(top.totaux.nb_lectures_divergentes)} comptes se
            lisent différemment selon la dimension. Le top affiché concentre{" "}
            {formatPct(top.totaux.part_ca_top_pct, 0)} % du CA réalisé et{" "}
            {formatPct(top.totaux.part_pipe_top_pct, 0)} % du pipe à venir.
          </Note>
        </Tile>

        <Tile span={7} title="Pics d'activité sur la fenêtre récente" kick={`× ${pics.seuils.facteur} la médiane du compte`}>
          {pics.pics.length > 0 ? (
            <>
              <HintLine>Cliquez un pic pour son historique de rythme</HintLine>
              <Lst
                items={pics.pics.map((p) => ({
                  title: p.compte,
                  sub: `${p.mois}${p.mois_en_cours ? " (mois en cours)" : ""} · ${formatNumber(p.nb_commandes_mois)} commande(s) · médiane ${formatMFcfa(p.mediane_mensuelle_xof)} M`,
                  tag: `× ${formatPct(p.intensite, 1)}`,
                  tagVariant: "w" as const,
                  detail: {
                    kicker: "Compte · pic de commande",
                    title: p.compte,
                    tag: `${formatPct(p.intensite, 1)} fois sa médiane`,
                    tagVariant: "w" as const,
                    body: [
                      `${formatMFcfa(p.montant_xof)} M FCFA commandés sur ${p.mois} en ${formatNumber(p.nb_commandes_mois)} commande(s), contre une médiane mensuelle de ${formatMFcfa(p.mediane_mensuelle_xof)} M FCFA calculée sur ${formatNumber(p.nb_mois_historique)} mois d'historique.`,
                      p.mois_en_cours
                        ? "Le mois est encore en cours : le montant peut encore monter, et le pic est donc au moins celui affiché."
                        : "Le mois est clos : le pic est définitif.",
                      "Un compte qui accélère est un compte qui arbitre. La fenêtre de tir est courte — c'est le sens de l'alerte.",
                    ],
                    kv: [
                      ["Mois", p.mois],
                      ["Montant du mois", `${formatMFcfa(p.montant_xof)} M FCFA`],
                      ["Médiane mensuelle", `${formatMFcfa(p.mediane_mensuelle_xof)} M FCFA`],
                      ["Intensité", `× ${formatPct(p.intensite, 1)}`],
                      ["Mois d'historique", formatNumber(p.nb_mois_historique)],
                      ["Commercial rattaché", p.commercial || "non renseigné"],
                    ],
                  },
                }))}
              />
            </>
          ) : (
            <Note style={{ marginTop: 0 }}>
              Aucun compte ne dépasse {pics.seuils.facteur} fois sa médiane mensuelle sur la fenêtre
              observée.
            </Note>
          )}
          <Note style={{ marginTop: 14 }}>{pics.note}</Note>
        </Tile>

        <Tile span={5} title="Alertes en attente" kick={alertes ? `${formatNumber(alertes.totaux.nb_total)} au total` : "indisponible"}>
          {alertes && alertes.alertes.length > 0 ? (
            <>
              <HintLine>Cliquez une alerte pour l&apos;action recommandée</HintLine>
              <Lst
                items={alertes.alertes.slice(0, 7).map((a) => ({
                  title: a.titre,
                  sub: [a.commercial || null, a.depuis ? `signalé depuis le ${formatDate(a.depuis)}` : null]
                    .filter(Boolean)
                    .join(" · "),
                  tag: a.severity,
                  tagVariant: SEVERITE_TAG[a.severity] ?? "n",
                  detail: {
                    kicker: `Alerte · ${a.alert_type.replace(/_/g, " ")}`,
                    title: a.titre,
                    tag: a.severity,
                    tagVariant: SEVERITE_TAG[a.severity] ?? "n",
                    body: [
                      a.detail,
                      `Action recommandée : ${a.action}`,
                      a.depuis
                        ? `Cette alerte est apparue le ${formatDate(a.depuis)} et n'a pas été écartée depuis.`
                        : "",
                      alertes.diffusion.limite,
                    ].filter(Boolean),
                    kv: [
                      ["Sévérité", a.severity],
                      ["Montant concerné", `${formatMFcfa(a.montant_xof)} M FCFA`],
                      ["Commercial", a.commercial || "non renseigné"],
                      ["Signalée depuis", formatDate(a.depuis)],
                    ],
                  },
                }))}
              />
              <Note style={{ marginTop: 14 }}>
                {formatNumber(alertes.totaux.nb_total)} alertes produites,{" "}
                {formatNumber(alertes.totaux.nb_affichees)} affichées dont{" "}
                {formatNumber(alertes.totaux.nb_critiques)} critiques
                {alertes.totaux.nb_ecartees > 0
                  ? `, ${formatNumber(alertes.totaux.nb_ecartees)} déjà écartées`
                  : ""}
                . {alertes.diffusion.limite}
              </Note>
            </>
          ) : (
            <Note style={{ marginTop: 0 }}>Aucune alerte en attente sur le portefeuille.</Note>
          )}
        </Tile>

        <Tile span={12} title="Acquisition de nouveaux comptes par exercice" kick="première commande signée">
          <HintLine>Cliquez un exercice pour ses comptes entrants</HintLine>
          <Bars
            rows={acquisition.annees
              .slice()
              .reverse()
              .map((a) => ({
                name: String(a.annee),
                sub: `${formatMFcfa(a.ca_xof)} M FCFA de CA cumulé depuis leur entrée${a.annee === acquisition.annee_courante.annee ? " · exercice en cours" : ""}`,
                value: formatNumber(a.nb_comptes),
                pct: (a.nb_comptes / maxAcq) * 100,
                variant: a.annee === acquisition.annee_courante.annee ? ("s" as const) : undefined,
                detail: {
                  kicker: "Exercice · comptes entrants",
                  title: `${formatNumber(a.nb_comptes)} nouveaux comptes en ${a.annee}`,
                  tag: `${formatMFcfa(a.ca_xof)} M FCFA cumulés`,
                  tagVariant: "a" as const,
                  body: [
                    `${formatNumber(a.nb_comptes)} comptes ont passé leur première commande en ${a.annee}. Leur CA cumulé depuis l'entrée atteint ${formatMFcfa(a.ca_xof)} M FCFA — un montant qui court sur toutes les années suivantes, pas seulement sur ${a.annee}.`,
                    a.annee === acquisition.annee_courante.annee
                      ? "Exercice en cours : le compte n'est pas comparable à une année pleine."
                      : "Exercice complet.",
                  ],
                  kv: [
                    ["Nouveaux comptes", formatNumber(a.nb_comptes)],
                    ["CA cumulé", `${formatMFcfa(a.ca_xof)} M FCFA`],
                    ...a.comptes.slice(0, 6).map(
                      (c) =>
                        [c.compte, `${formatMFcfa(c.ca_total_xof)} M · ${formatNumber(c.nb_commandes)} cmd`] as [
                          string,
                          string,
                        ],
                    ),
                  ],
                },
              }))}
          />
          <Note style={{ marginTop: 14 }}>{acquisition.note}</Note>
        </Tile>
      </Bento>
    </>
  );
}
