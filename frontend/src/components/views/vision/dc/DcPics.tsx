import { getAlertes, getComptesDc } from "@/lib/api/commercial";
import { formatDate, formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bento, HintLine, Lst, StatTile, Tile } from "@/components/ui/bento";
import { Note } from "@/components/ui/primitives";
import { SEVERITE_TAG } from "./source";

/** « Pics et alertes » — chapitre 1 du compte-rendu DC.
 *
 * « Détection des pics d'activité : l'outil doit être capable d'identifier
 * automatiquement les moments de pic d'activité chez un compte et de déclencher une
 * alerte proactive auprès du commercial. »
 *
 * Deux choses que cet écran doit dire et redire, sous peine de promettre ce qu'il
 * ne tient pas :
 *
 * - un pic se mesure contre le PASSÉ DU COMPTE, pas dans l'absolu. Un compte qui
 *   commande 200 M quand il en fait 180 d'habitude ne fait pas un pic ;
 * - seul le rythme de COMMANDE est mesurable. Le pic par sollicitation (demandes de
 *   devis, rendez-vous, appels, e-mails) n'existe pas dans le miroir, et la
 *   détection ne couvre que les comptes ayant assez d'historique pour qu'une médiane
 *   ait un sens.
 *
 * L'alerte, elle, s'arrête à l'application : aucun canal sortant n'existe. C'est
 * écrit sous la file, pas en note de bas de page.
 */
export async function DcPics() {
  const [comptes, alertes] = await Promise.all([getComptesDc(20), getAlertes(20)]);

  if (!comptes) {
    return (
      <Bento>
        <Tile span={12} title="Pics et alertes">
          <Note style={{ marginTop: 0 }}>
            L&apos;animation de compte n&apos;est pas accessible depuis ce profil.
          </Note>
        </Tile>
      </Bento>
    );
  }

  const { pics } = comptes;
  // Commande la mise en page à deux colonnes : sans la tuile « Nature », la
  // colonne de gauche n'a qu'une rangée et « Alertes en attente » ne doit pas en
  // couvrir deux — elle laisserait une rangée vide sous elle.
  const natureAffichee = Boolean(alertes && alertes.totaux.par_type.length > 0);

  return (
    <>
      <div className="kpi-row">
        {/* Les pics sont l'objet de l'écran ; le portefeuille mesurable dit sur
            quelle fraction du parc la détection est possible — c'est une limite,
            pas un résultat. */}
        <StatTile
          span={4}
          rang="principal"
          label="Pics d'activité détectés"
          aide="Les clients qui commandent nettement plus que leur habitude en ce moment. Un pic se juge par rapport au rythme du compte lui-même, pas au montant : un gros client qui commande normalement n'est pas un pic."
          value={formatNumber(pics.couverture.nb_pics)}
          unit={`sur ${formatNumber(pics.fenetre_mois.length)} mois`}
          reading={`fenêtre ${pics.fenetre_mois[0]} → ${pics.fenetre_mois[pics.fenetre_mois.length - 1]}`}
          readingVariant={pics.couverture.nb_pics > 0 ? "wat" : undefined}
          detail={{
            kicker: "Indicateur · détection de pic",
            title: "Comptes dont le rythme de commande s'emballe",
            tag: `× ${pics.seuils.facteur} la médiane`,
            tagVariant: "w",
            body: [
              `${formatNumber(pics.couverture.nb_pics)} pic(s) détecté(s) sur la fenêtre ${pics.fenetre_mois[0]} → ${pics.fenetre_mois[pics.fenetre_mois.length - 1]}. Un mois est un pic quand il pèse au moins ${pics.seuils.facteur} fois la médiane mensuelle du compte lui-même.`,
              `Le seuil est un MULTIPLE de la médiane du compte, et non un montant : un compte qui commande 200 M quand il en fait 180 d'habitude ne fait pas un pic, un compte à 40 M qui saute à 150 M en fait un.`,
              `Un plancher de ${formatMFcfa(pics.seuils.montant_plancher_xof)} M FCFA écarte le bruit : sans lui, un compte dont la médiane est à 800 000 FCFA alerterait à 2 M.`,
            ],
            kv: [
              ["Pics détectés", formatNumber(pics.couverture.nb_pics)],
              ["Facteur de déclenchement", `× ${pics.seuils.facteur}`],
              ["Plancher de montant", `${formatMFcfa(pics.seuils.montant_plancher_xof)} M FCFA`],
              ["Fenêtre observée", `${pics.fenetre_mois.length} mois`],
            ],
          }}
        />
        <StatTile
          span={4}
          rang="contexte"
          label="Portefeuille mesurable"
          aide="Le nombre de clients pour lesquels la détection peut fonctionner. Il faut assez de commandes passées pour savoir ce qui est habituel : un client trop récent ne peut pas être surveillé."
          value={formatNumber(pics.couverture.nb_comptes_eligibles)}
          unit={`comptes sur ${formatNumber(pics.couverture.nb_comptes_avec_commande)}`}
          reading={`${formatPct(pics.couverture.part_eligible_pct, 0)} % des comptes ayant déjà commandé`}
          readingVariant={pics.couverture.part_eligible_pct < 50 ? "wat" : undefined}
          detail={{
            kicker: "Indicateur · couverture de la détection",
            title: "Comptes sur lesquels un pic est mesurable",
            tag: `${formatPct(pics.couverture.part_eligible_pct, 0)} %`,
            tagVariant: "w",
            body: [
              `La détection ne couvre que ${formatNumber(pics.couverture.nb_comptes_eligibles)} comptes sur ${formatNumber(pics.couverture.nb_comptes_avec_commande)} ayant déjà commandé.`,
              `Sous ${pics.seuils.min_commandes} commandes, une « médiane » n'a pas de sens statistique : le compte est déclaré non éligible plutôt que jugé sur deux points. C'est la limite structurelle de cet indicateur, et elle ne se corrige pas par du développement — seulement par de l'historique.`,
              pics.note,
            ],
            kv: [
              ["Comptes éligibles", formatNumber(pics.couverture.nb_comptes_eligibles)],
              ["Comptes ayant commandé", formatNumber(pics.couverture.nb_comptes_avec_commande)],
              ["Part mesurable", `${formatPct(pics.couverture.part_eligible_pct, 0)} %`],
              ["Minimum de commandes", formatNumber(pics.seuils.min_commandes)],
            ],
          }}
        />
        <StatTile
          span={4}
          label="Alertes produites"
          aide="Les signalements générés automatiquement et qui vous attendent ici. Ils ne partent pas en e-mail ni en notification : il faut venir les consulter."
          value={alertes ? formatNumber(alertes.totaux.nb_total) : "—"}
          unit={alertes ? `dont ${formatNumber(alertes.totaux.nb_critiques)} critiques` : "indisponible"}
          reading={alertes ? alertes.diffusion.canal : "file d'alertes inaccessible"}
          readingVariant={alertes && alertes.totaux.nb_critiques > 0 ? "neg" : undefined}
          detail={{
            kicker: "Indicateur · volume d'alertes",
            title: "Ce que le système signale, et par quel canal",
            tag: alertes ? alertes.diffusion.canal : "—",
            tagVariant: "w",
            body: [
              alertes
                ? `${formatNumber(alertes.totaux.nb_total)} alertes sont produites à date, dont ${formatNumber(alertes.totaux.nb_critiques)} critiques et ${formatNumber(alertes.totaux.nb_ecartees)} déjà écartées. ${formatNumber(alertes.totaux.nb_affichees)} sont affichées.`
                : "La file d'alertes n'est pas accessible depuis ce profil.",
              alertes?.diffusion.limite ??
                "Aucun canal sortant n'existe : une alerte ne peut s'afficher que dans le cockpit.",
              alertes?.note ?? "",
            ].filter(Boolean),
            kv: alertes
              ? [
                  ["Produites", formatNumber(alertes.totaux.nb_total)],
                  ["Affichées", formatNumber(alertes.totaux.nb_affichees)],
                  ["Critiques", formatNumber(alertes.totaux.nb_critiques)],
                  ["Écartées", formatNumber(alertes.totaux.nb_ecartees)],
                  ...alertes.totaux.par_type.map(
                    (t) => [t.libelle, formatNumber(t.nb)] as [string, string],
                  ),
                ]
              : [],
          }}
        />
      </div>

      <Bento>
        {/* Deux colonnes : « Pics d'activité » et « Nature des alertes » empilés à
            gauche, « Alertes en attente » à droite en vis-à-vis des deux (d'où son
            `rows={2}`). Les deux tuiles de gauche partagent la même largeur.
            L'ordre du DOM place Pics puis Nature avant Alertes : la grille remplit
            rangée par rangée, donc Alertes doit être déclarée entre les deux pour
            démarrer sur la première rangée — ce n'est pas l'ordre de LECTURE, qui
            reste colonne de gauche puis colonne de droite. */}
        <Tile
          span={7}
          title="Pics d'activité sur la fenêtre récente"
          kick={`× ${pics.seuils.facteur} la médiane du compte`}
          aide="Le détail des clients en accélération sur les derniers mois : lesquels, de combien, et à quel moment. C'est la liste sur laquelle appeler pendant que le besoin est là."
        >
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

        {/* Colonne de droite, en vis-à-vis des DEUX tuiles de gauche. Sa liste est
            repliée à 5 lignes : c'est elle qui dictait la hauteur des deux rangées,
            et l'excédent retombait en espace vide entre « Pics » et « Nature ».
            Repliée, elle cadre sur la colonne de gauche ; les alertes suivantes
            restent à un clic. */}
        <Tile
          span={5}
          rows={natureAffichee ? 2 : undefined}
          title="Alertes en attente"
          kick={alertes ? `${formatNumber(alertes.totaux.nb_total)} produites` : "indisponible"}
          aide="Ce que le cockpit a repéré et qui n'a pas encore été traité, du plus urgent au moins urgent."
        >
          {alertes && alertes.alertes.length > 0 ? (
            <>
              <HintLine>Cliquez une alerte pour l&apos;action recommandée</HintLine>
              <Lst
                replierApres={5}
                nom="alertes"
                items={alertes.alertes.slice(0, 10).map((a) => ({
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

        {/* Deuxième tuile de la colonne de GAUCHE, sous « Pics d'activité » —
            déclarée après « Alertes en attente » parce que la grille remplit
            rangée par rangée. Même largeur que Pics. */}
        {alertes && alertes.totaux.par_type.length > 0 && (
          <Tile
            span={7}
            title="Nature des alertes produites"
            aide="De quoi parlent les alertes en cours : clients qui décrochent, pics, échéances. Si une seule catégorie domine, c'est souvent le réglage qu'il faut revoir, pas le portefeuille."
            quiet
          >
            <Lst
              items={alertes.totaux.par_type.map((t) => ({
                title: t.libelle,
                sub: `${formatNumber(t.nb)} alerte(s) sur ${formatNumber(alertes.totaux.nb_total)}`,
                tag: formatNumber(t.nb),
                tagVariant: "n" as const,
              }))}
            />
            <Note accent style={{ marginTop: 14 }}>
              {alertes.note}
            </Note>
          </Tile>
        )}
      </Bento>
    </>
  );
}
