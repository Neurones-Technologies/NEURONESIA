import { getVisites } from "@/lib/api/commercial";
import { formatDate, formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bento, HintLine, Lst, StatTile, Tile } from "@/components/ui/bento";
import { Note } from "@/components/ui/primitives";
import { SourceNote, sourceKick } from "./source";

/** Onglet « Visites terrain » — §6 du compte-rendu DC. GABARIT assumé.
 *
 * « Mise en place d'un fichier de visite permettant d'historiser les visites
 * clients. Chaque visite doit pouvoir être documentée par un compte-rendu de visite
 * directement intégré à l'outil. »
 *
 * Aucune table de visite n'existe. Cet écran sert deux buts explicites :
 *
 * 1. faire trancher les questions 43 à 47 du cadrage sur une forme CONCRÈTE (qui
 *    saisit, quand, quel contenu minimal, faut-il lire les comptes rendus ou
 *    seulement suivre un taux de couverture, rattachement compte ou opportunité) ;
 * 2. livrer tout de suite la moitié qui est mesurable : les comptes à couvrir. « Ce
 *    compte n'a pas été visité depuis quatre mois » n'est pas calculable, mais « ce
 *    compte à 4 274 M FCFA n'a pas commandé depuis onze mois » l'est.
 *
 * Les comptes affichés sont RÉELS, les visites sont posées à la main, et les
 * interlocuteurs sont des FONCTIONS et non des noms fabriqués : un compte-rendu
 * fictif attribué à une personne nommée est une pièce qui peut circuler hors de son
 * contexte.
 */
export async function DcVisites() {
  const fichier = await getVisites(12);

  if (!fichier) {
    return (
      <Bento>
        <Tile span={12} title="Visites terrain">
          <Note style={{ marginTop: 0 }}>
            Le portefeuille n&apos;est pas accessible depuis ce profil.
          </Note>
        </Tile>
      </Bento>
    );
  }

  const c = fichier.couverture;
  const avecCr = fichier.visites.filter((v) => v.compte_rendu).length;

  return (
    <>
      <div className="kpi-row">
        {/* Le fichier de visite est un gabarit : les visites « enregistrées » sont
            de démonstration et reculent d'un plan. Le seul chiffre mesuré de
            l'écran est la liste des comptes actifs sans visite, plus bas. */}
        <StatTile
          span={4}
          rang="contexte"
          label="Visites enregistrées"
          aide="Le nombre de visites clients consignées. Aucune visite réelle n'est encore saisie : ce module n'existe pas, ce que vous voyez est une maquette pour en décider la forme."
          value={formatNumber(c.nb_visites_enregistrees)}
          unit="au fichier"
          reading={`dont ${formatNumber(avecCr)} avec compte-rendu · données statiques`}
          readingVariant="wat"
          detail={{
            kicker: "Indicateur · fichier de visite (gabarit)",
            title: "Visites historisées dans l'outil",
            tag: "donnée statique",
            tagVariant: "n",
            body: [
              `Le gabarit porte ${formatNumber(c.nb_visites_enregistrees)} visites, dont ${formatNumber(avecCr)} documentées par un compte-rendu.`,
              fichier.raison,
              "Les interlocuteurs sont désignés par leur FONCTION et non par un nom : un compte-rendu de démonstration attribué à une personne nommée serait indiscernable d'un vrai document.",
            ],
            kv: [
              ["Visites au fichier", formatNumber(c.nb_visites_enregistrees)],
              ["Avec compte-rendu", formatNumber(avecCr)],
              ["Nature", "gabarit de démonstration"],
            ],
          }}
        />
        <StatTile
          span={4}
          label="Taux de couverture"
          aide="La part de vos clients actifs qui ont reçu une visite. C'est l'indicateur visé : suivre un taux plutôt que de lire chaque compte-rendu."
          value={formatPct(c.taux_couverture_pct, 1)}
          unit="% des comptes actifs"
          reading={`${formatNumber(c.nb_comptes_sans_visite)} comptes actifs sans visite enregistrée`}
          readingVariant="neg"
          detail={{
            kicker: "Indicateur · couverture terrain",
            title: "Comptes actifs couverts par une visite",
            tag: "gabarit",
            tagVariant: "w",
            body: [
              `${formatNumber(c.nb_comptes_couverts)} comptes actifs sur ${formatNumber(c.nb_comptes_actifs)} portent une visite au fichier, soit ${formatPct(c.taux_couverture_pct, 1)} %.`,
              c.lecture,
              "C'est l'indicateur que le DC visait à la question 46 du cadrage — suivre un taux plutôt que lire chaque compte-rendu. Il devient réel dès que les visites sont saisies, sans changer de forme.",
            ],
            kv: [
              ["Comptes actifs", formatNumber(c.nb_comptes_actifs)],
              ["Couverts", formatNumber(c.nb_comptes_couverts)],
              ["Sans visite", formatNumber(c.nb_comptes_sans_visite)],
              ["Taux de couverture", `${formatPct(c.taux_couverture_pct, 1)} %`],
              ["Seuil retenu", `${fichier.seuil_couverture_mois} mois`],
            ],
          }}
        />
        <StatTile
          span={4}
          rang="principal"
          label="Comptes à couvrir en priorité"
          aide="Les clients importants que personne n'est allé voir. Calculé sur des données réelles, contrairement aux visites elles-mêmes."
          value={formatNumber(fichier.comptes_a_visiter.length)}
          unit="affichés"
          reading="par CA historique — donnée réelle"
          detail={{
            kicker: "Indicateur · priorités de terrain",
            title: "Comptes actifs sans visite, par poids",
            tag: "mesuré",
            tagVariant: "s",
            body: [
              "Cette liste est la seule partie de l'écran entièrement mesurée : les comptes, leur CA et leur dernière commande viennent du miroir.",
              "Elle est utilisable dès aujourd'hui, avant même que le module de saisie existe : elle dit quels comptes pèsent le plus et depuis combien de temps ils n'ont pas commandé.",
            ],
            kv: [
              ["Comptes listés", formatNumber(fichier.comptes_a_visiter.length)],
              ["Total sans visite", formatNumber(c.nb_comptes_sans_visite)],
            ],
          }}
        />
      </div>

      <Bento>
        <Tile
          span={7}
          title="Fichier de visite"
          kick={sourceKick(fichier.source, "gabarit de saisie")}
          aide="À quoi ressemblerait le journal des visites une fois le module en place. Les lignes affichées sont des exemples, posées à la main pour juger la forme."
        >
          <HintLine>Cliquez une visite pour son compte-rendu</HintLine>
          <Lst
            items={fichier.visites.map((v) => ({
              title: `${formatDate(v.date)} · ${v.compte}`,
              sub: `${v.interlocuteur} · ${v.objet}`,
              tag: v.compte_rendu ? "compte-rendu" : "à documenter",
              tagVariant: v.compte_rendu ? ("s" as const) : ("w" as const),
              detail: {
                kicker: "Visite · exemple de saisie",
                title: v.compte,
                tag: v.compte_rendu ? "compte-rendu saisi" : "compte-rendu manquant",
                tagVariant: v.compte_rendu ? ("s" as const) : ("w" as const),
                body: [
                  `Visite du ${formatDate(v.date)}${v.mois_ecoules !== null ? `, il y a ${formatNumber(v.mois_ecoules)} mois` : ""}. Interlocuteur : ${v.interlocuteur}.`,
                  `Objet : ${v.objet}`,
                  `Prochaine action : ${v.prochaine_action}`,
                  v.opportunite_liee
                    ? `Opportunité rattachée : ${v.opportunite_liee}. Le rattachement à une opportunité reste une question ouverte du cadrage — une visite peut ne concerner qu'un compte.`
                    : "Aucune opportunité rattachée : cette visite ne concerne que le compte.",
                  "Ligne de démonstration : aucune visite n'est réellement enregistrée dans le système.",
                ],
                kv: [
                  ["Date", formatDate(v.date)],
                  ["Compte", v.compte],
                  ["Interlocuteur", v.interlocuteur],
                  ["Objet", v.objet],
                  ["Prochaine action", v.prochaine_action],
                  ["Opportunité rattachée", v.opportunite_liee || "—"],
                  ["Compte-rendu", v.compte_rendu ? "saisi" : "manquant"],
                ],
              },
            }))}
          />
          <SourceNote source={fichier.source} raison={fichier.raison} avertissement={fichier.avertissement} />
        </Tile>

        <Tile
          span={5}
          title="Contenu minimal d'un compte-rendu"
          aide="Ce qu'il faudrait saisir à chaque visite. Volontairement court : un formulaire trop long ne se remplit pas."
          quiet
        >
          <Lst
            items={fichier.contenu_minimal.map((champ, i) => ({
              title: champ,
              sub: `champ ${i + 1}`,
              tag: "à confirmer",
              tagVariant: "n" as const,
            }))}
          />
          <Note style={{ marginTop: 14 }}>
            Cette liste est la proposition à valider avec l&apos;équipe : c&apos;est elle qui déterminera
            le formulaire de saisie, et donc ce qui pourra être suivi ensuite.
          </Note>
        </Tile>

        <Tile
          span={12}
          title="Comptes actifs sans visite enregistrée"
          kick="mesuré · par CA historique"
          aide="Vos clients qui achètent mais que personne ne va voir, les plus gros d'abord. Cette liste est réelle et exploitable dès maintenant."
        >
          <HintLine>Cliquez un compte pour son historique de commande</HintLine>
          <Lst
            items={fichier.comptes_a_visiter.map((cp) => ({
              title: cp.compte,
              sub: [
                `${formatMFcfa(cp.ca_total_xof)} M FCFA historiques`,
                cp.mois_silence !== null ? `${formatNumber(cp.mois_silence)} mois sans commande` : null,
                cp.nb_opp_ouvertes > 0 ? `${formatNumber(cp.nb_opp_ouvertes)} opportunités ouvertes` : null,
                cp.commercial || null,
              ]
                .filter(Boolean)
                .join(" · "),
              tag:
                cp.mois_silence !== null && cp.mois_silence >= fichier.seuil_couverture_mois
                  ? `${formatNumber(cp.mois_silence)} mois`
                  : "actif",
              tagVariant:
                cp.mois_silence !== null && cp.mois_silence >= fichier.seuil_couverture_mois
                  ? ("w" as const)
                  : ("s" as const),
              detail: {
                kicker: "Compte · à couvrir",
                title: cp.compte,
                tag: "aucune visite enregistrée",
                tagVariant: "w" as const,
                body: [
                  `${formatMFcfa(cp.ca_total_xof)} M FCFA de CA historique. Dernière commande le ${formatDate(cp.derniere_commande)}${cp.mois_silence !== null ? `, soit ${formatNumber(cp.mois_silence)} mois` : ""}.`,
                  cp.nb_opp_ouvertes > 0
                    ? `${formatNumber(cp.nb_opp_ouvertes)} opportunités ouvertes sur ce compte : il y a du travail commercial en cours.`
                    : "Aucune opportunité ouverte sur ce compte.",
                  "Ces éléments sont mesurés. Ce qui manque, et que seule la saisie apportera, c'est la date de la dernière visite — le silence commercial et le silence de commande ne sont pas la même chose.",
                ],
                kv: [
                  ["CA historique", `${formatMFcfa(cp.ca_total_xof)} M FCFA`],
                  ["Dernière commande", formatDate(cp.derniere_commande)],
                  ["Silence", cp.mois_silence !== null ? `${formatNumber(cp.mois_silence)} mois` : "—"],
                  ["Opportunités ouvertes", formatNumber(cp.nb_opp_ouvertes)],
                  ["Commercial rattaché", cp.commercial || "non renseigné"],
                  ["Dernière visite", cp.derniere_visite ? formatDate(cp.derniere_visite) : "aucune"],
                ],
              },
            }))}
          />
          <Note style={{ marginTop: 14 }}>{c.lecture}</Note>
        </Tile>

        <Tile
          span={12}
          title="Décisions à prendre avant de construire ce module"
          aide="Les questions à trancher avant tout développement : qui saisit, à quel moment, et rattaché à quoi."
          quiet
        >
          <Lst
            items={fichier.questions_ouvertes.map((q, i) => ({
              title: `Question ${i + 1}`,
              sub: q,
              tag: "à trancher",
              tagVariant: "n" as const,
            }))}
          />
          <Note accent style={{ marginTop: 14 }}>
            {fichier.raison}
          </Note>
        </Tile>
      </Bento>
    </>
  );
}
