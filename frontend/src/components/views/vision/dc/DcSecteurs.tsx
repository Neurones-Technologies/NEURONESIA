import { getMarcheDc } from "@/lib/api/commercial";
import { formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, HintLine, Lst, StatTile, Tile } from "@/components/ui/bento";
import { Note } from "@/components/ui/primitives";
import { SourceNote, sourceKick } from "./source";

/** « Tendance des secteurs » — chapitre 4 du compte-rendu DC. GABARIT assumé.
 *
 * « Tendance des secteurs : besoin d'une analyse de la performance commerciale
 * ventilée par secteur d'activité. »
 *
 * Point mort du dossier en l'état des données : le secteur d'activité n'est
 * renseigné que pour une poignée de clients sur les quinze cents du référentiel.
 * Aucun développement ne contourne cela.
 *
 * L'écran sert donc deux buts, et il les sert ensemble :
 *
 * 1. montrer la FORME de l'indicateur, prête à s'alimenter ;
 * 2. faire valider la NOMENCLATURE — c'est la question 35 du cadrage (« une dizaine
 *    de grandes catégories, ou plus fin ? »), et c'est elle qui déterminera la
 *    saisie à mener. Faire saisir 1 500 secteurs avant d'avoir tranché la
 *    nomenclature reviendrait à la refaire deux fois.
 *
 * La couverture RÉELLE est affichée en regard du gabarit, jamais séparément : le
 * gabarit seul serait trompeur, la couverture seule serait incompréhensible.
 */
export async function DcSecteurs() {
  const marche = await getMarcheDc(12);

  if (!marche) {
    return (
      <Bento>
        <Tile span={12} title="Tendance des secteurs">
          <Note style={{ marginTop: 0 }}>
            L&apos;analyse sectorielle n&apos;est pas accessible depuis ce profil.
          </Note>
        </Tile>
      </Bento>
    );
  }

  const { secteurs } = marche;
  const reel = secteurs.couverture_reelle;
  const maxSecteur = Math.max(...secteurs.secteurs.map((s) => s.ca_xof), 1);
  const enBaisse = secteurs.secteurs.filter((s) => s.croissance_pct < 0);

  return (
    <>
      <div className="kpi-row">
        {/* Écran en gabarit assumé : le seul chiffre mesuré est le taux de
            renseignement, et c'est lui qui explique pourquoi les deux autres ne
            sont pas des tendances. Il porte donc le rang principal — la
            nomenclature proposée, elle, est du cadrage et recule d'un plan. */}
        <StatTile
          span={4}
          rang="principal"
          label="Secteur renseigné"
          aide="Le nombre de clients dont on connaît le domaine d'activité. C'est la limite de tout cet écran : sans secteur saisi, aucune analyse sectorielle n'est possible."
          value={formatNumber(reel.nb_avec_secteur)}
          unit={`client sur ${formatNumber(reel.nb_clients)}`}
          reading="analyse sectorielle réelle impossible en l'état"
          readingVariant="neg"
          detail={{
            kicker: "Indicateur · qualité du référentiel clients",
            title: "Taux de renseignement du secteur d'activité",
            tag: `${formatPct(reel.couverture_pct, 2)} %`,
            tagVariant: "r",
            body: [
              reel.verdict,
              secteurs.raison,
              "Ce chiffre est affiché précisément parce qu'il est mauvais : un écran vide sans explication se lit comme une panne, alors qu'il s'agit d'une donnée à saisir. Aucun développement ne le corrigera.",
            ],
            kv: [
              ["Clients au référentiel", formatNumber(reel.nb_clients)],
              ["Avec un secteur", formatNumber(reel.nb_avec_secteur)],
              ["Couverture", `${formatPct(reel.couverture_pct, 2)} %`],
              ["Valeurs distinctes", formatNumber(reel.nb_secteurs_distincts)],
              ...reel.valeurs
                .slice(0, 4)
                .map((v) => [v.secteur, `${formatNumber(v.nb_clients)} client(s)`] as [string, string]),
            ],
          }}
        />
        <StatTile
          span={4}
          rang="contexte"
          label="Nomenclature proposée"
          aide="La liste de secteurs suggérée pour classer vos clients. Elle est à valider avant toute saisie en masse : la corriger après coup coûte beaucoup plus cher."
          value={formatNumber(secteurs.secteurs.length)}
          unit="catégories à valider"
          reading="c'est elle qui déterminera la saisie à mener"
          readingVariant="wat"
          detail={{
            kicker: "Indicateur · nomenclature",
            title: "Catégories sectorielles soumises à validation",
            tag: "à trancher",
            tagVariant: "w",
            body: [
              `${formatNumber(secteurs.secteurs.length)} catégories sont proposées : ${secteurs.secteurs.map((s) => s.secteur).join(", ")}.`,
              "Question 35 du cadrage : une dizaine de grandes catégories, ou plus fin ? Et s'agit-il du secteur du CLIENT ou du domaine de l'OFFRE vendue ? Le compte-rendu évoque « la santé du marché orienté IA et infrastructure », ce qui renvoie plutôt à l'offre — traitée par les axes de marché, dans l'onglet Tendances et marché.",
              "Trancher la nomenclature avant la saisie évite de la refaire deux fois sur quinze cents comptes.",
            ],
            kv: secteurs.secteurs.map((s) => [s.secteur, `${formatNumber(s.nb_clients)} clients (gabarit)`] as [string, string]),
          }}
        />
        <StatTile
          span={4}
          label="Secteurs en recul"
          aide="Les domaines d'activité où votre chiffre baisse d'une année sur l'autre. À prendre comme une indication tant que peu de clients portent un secteur."
          value={formatNumber(enBaisse.length)}
          unit={`sur ${formatNumber(secteurs.secteurs.length)} · gabarit`}
          reading="données statiques — aucune tendance mesurée"
          readingVariant="wat"
          detail={{
            kicker: "Indicateur · tendance (gabarit)",
            title: "Ce que l'écran dira quand il sera alimenté",
            tag: "donnée statique",
            tagVariant: "n",
            body: [
              enBaisse.length > 0
                ? `Le gabarit place ${formatNumber(enBaisse.length)} secteur(s) en recul : ${enBaisse.map((s) => `${s.secteur} (${formatPct(s.croissance_pct, 1)} %)`).join(", ")}.`
                : "Le gabarit ne place aucun secteur en recul.",
              "Une fois le secteur renseigné, cette tendance se calculera sur le CA réel par secteur et par exercice — exactement comme le fait déjà l'onglet Comptes par ventes sur les comptes.",
              secteurs.avertissement,
            ],
            kv: enBaisse.map((s) => [s.secteur, `${formatPct(s.croissance_pct, 1)} %`] as [string, string]),
          }}
        />
      </div>

      <Bento>
        <Tile
          span={12}
          title="Performance commerciale par secteur d'activité"
          kick={sourceKick(secteurs.source, "nomenclature à valider")}
          aide="Votre activité ventilée par domaine client. Repose sur la poignée de clients dont le secteur est connu : à lire comme une esquisse, pas comme un état des lieux."
        >
          <HintLine>Cliquez un secteur pour ce que le gabarit suppose</HintLine>
          <Bars
            rows={secteurs.secteurs.map((s) => ({
              name: s.secteur,
              sub: [
                `${formatNumber(s.nb_clients)} clients`,
                `${formatPct(s.part_ca_pct, 0)} % du CA`,
                `croissance ${s.croissance_pct > 0 ? "+" : ""}${formatPct(s.croissance_pct, 1)} %`,
                s.part_marche_pct !== null ? `part de marché supposée ${formatPct(s.part_marche_pct, 2)} %` : null,
              ]
                .filter(Boolean)
                .join(" · "),
              value: `${formatMFcfa(s.ca_xof)} M`,
              pct: (s.ca_xof / maxSecteur) * 100,
              variant: s.croissance_pct < 0 ? ("r" as const) : undefined,
              detail: {
                kicker: "Secteur · gabarit",
                title: s.secteur,
                tag: "donnée statique",
                tagVariant: "n" as const,
                body: [
                  `Le gabarit pose ${formatMFcfa(s.ca_xof)} M FCFA de CA sur ${formatNumber(s.nb_clients)} clients pour ce secteur, soit ${formatPct(s.part_ca_pct, 0)} % du CA, avec une croissance de ${formatPct(s.croissance_pct, 1)} %.`,
                  s.part_marche_pct !== null
                    ? `Rapporté à une taille de marché supposée de ${formatMFcfa(s.taille_marche_xof)} M FCFA, cela donnerait une part de marché de ${formatPct(s.part_marche_pct, 2)} %. Cette taille de marché est un ordre de grandeur de travail, à remplacer par une étude ou des données publiques.`
                    : "Aucune taille de marché n'est associée à ce secteur.",
                  secteurs.raison,
                ],
                kv: [
                  ["CA (gabarit)", `${formatMFcfa(s.ca_xof)} M FCFA`],
                  ["Clients (gabarit)", formatNumber(s.nb_clients)],
                  ["Part du CA", `${formatPct(s.part_ca_pct, 0)} %`],
                  ["Croissance", `${formatPct(s.croissance_pct, 1)} %`],
                  ["Taille de marché supposée", `${formatMFcfa(s.taille_marche_xof)} M FCFA`],
                  ["Part de marché supposée", s.part_marche_pct !== null ? `${formatPct(s.part_marche_pct, 2)} %` : "—"],
                ],
              },
            }))}
          />
          <SourceNote source={secteurs.source} raison={secteurs.raison} avertissement={secteurs.avertissement} />
        </Tile>

        <Tile
          span={7}
          title="Ce que le référentiel porte réellement"
          kick="mesuré"
          aide="L'état réel de votre fichier client : ce qui est renseigné et ce qui ne l'est pas. Dit ce qu'il faudrait saisir pour que l'analyse par secteur tienne debout."
        >
          <Bars
            rows={[
              {
                name: "Clients avec un secteur renseigné",
                sub: `sur ${formatNumber(reel.nb_clients)} comptes du référentiel`,
                value: formatNumber(reel.nb_avec_secteur),
                pct: Math.max(1, reel.couverture_pct),
                variant: "r" as const,
              },
              {
                name: "Valeurs de secteur distinctes en base",
                sub: "une nomenclature ne peut pas se déduire d'aussi peu de valeurs",
                value: formatNumber(reel.nb_secteurs_distincts),
                pct: Math.min(100, reel.nb_secteurs_distincts * 10),
                variant: "r" as const,
              },
            ]}
          />
          {reel.valeurs.length > 0 && (
            <>
              <HintLine>Valeurs réellement présentes</HintLine>
              <Lst
                items={reel.valeurs.map((v) => ({
                  title: v.secteur,
                  sub: `${formatNumber(v.nb_clients)} client(s) portant cette valeur`,
                  tag: formatNumber(v.nb_clients),
                  tagVariant: "n" as const,
                }))}
              />
            </>
          )}
          <Note accent style={{ marginTop: 14 }}>
            {reel.verdict}
          </Note>
        </Tile>

        <Tile
          span={5}
          title="Décisions à prendre avant la saisie"
          aide="Les choix à arbitrer avant de lancer la saisie des secteurs : quelle liste, qui saisit, jusqu'où remonter."
          quiet
        >
          <Lst
            items={[
              {
                title: "Granularité",
                sub: "Une dizaine de grandes catégories, ou plus fin ?",
                tag: "à trancher",
                tagVariant: "n" as const,
              },
              {
                title: "Secteur du client ou domaine de l'offre",
                sub: "Le compte-rendu évoque « le marché orienté IA et infrastructure », ce qui renvoie à l'offre — déjà traitée par les axes de marché.",
                tag: "à trancher",
                tagVariant: "n" as const,
              },
              {
                title: "Qui renseigne, et dans quel délai",
                sub: `${formatNumber(reel.nb_clients - reel.nb_avec_secteur)} comptes restent à qualifier.`,
                tag: "à trancher",
                tagVariant: "n" as const,
              },
              {
                title: "Univers de référence de la part de marché",
                sub: "Sans source externe de taille de marché, seule une part de notre propre portefeuille est calculable.",
                tag: "à trancher",
                tagVariant: "n" as const,
              },
            ]}
          />
          <Note style={{ marginTop: 14 }}>{secteurs.raison}</Note>
        </Tile>
      </Bento>
    </>
  );
}
