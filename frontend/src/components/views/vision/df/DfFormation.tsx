import { getFormation } from "@/lib/api/daf";
import { formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, HintLine, Lst, StatTile, Tile } from "@/components/ui/bento";
import { Note } from "@/components/ui/primitives";
import { Variant } from "@/lib/types";
import { estStatique } from "../dc/source";
import { ScreenNotes } from "@/components/ui/screen-notes";
import { ScreenLede } from "@/components/ui/screen-lede";

/** Volet transverse de la note DAF — Formation et qualité de la saisie.
 *
 * « Formation des utilisateurs aux bons usages de l'outil, afin d'éviter tout
 * impact négatif (erreur de saisie, corruption) sur les données. »
 *
 * Le parti pris de l'écran : une formation ne se pilote pas sur des intentions.
 * Le contenu pédagogique est posé, mais chaque module est adossé à un contrôle
 * MESURÉ sur les données réelles, et l'ordre des modules suit ces mesures. Un
 * plan de formation qui commence par le sujet le mieux tenu perd la salle.
 *
 * Chaque défaut est relié à l'indicateur qu'il casse : « le secteur n'est pas
 * renseigné » n'engage personne, « aucune lecture sectorielle du risque client
 * n'est possible » engage. Et les mêmes compteurs, relus un mois plus tard,
 * disent si la formation a produit un effet — c'est la seule évaluation
 * disponible sans questionnaire.
 */
const GRAVITE_TAG: Record<string, Variant> = { critique: "r", attention: "w", info: "n" };
const GRAVITE_BAR: Record<string, "r" | "w" | "s" | undefined> = {
  critique: "r",
  attention: "w",
  info: undefined,
};

export async function DfFormation() {
  const data = await getFormation();

  if (!data) {
    return (
      <Bento>
        <Tile span={12} title="Formation et qualité des données">
          <Note style={{ marginTop: 0 }}>
            Ce volet n&apos;est pas accessible depuis ce profil.
          </Note>
        </Tile>
      </Bento>
    );
  }

  const score = data.qualite.score_global_pct;
  const scoreFaible = score !== null && score < 70;
  const structurels = data.controles.filter((c) => c.structurel);

  return (
    <>
      <ScreenLede
        texte={
          `La qualité de saisie du miroir ressort à ${formatPct(score, 0)} sur 100. ` +
          `${formatNumber(structurels.length)} ${structurels.length > 1 ? "défauts relèvent" : "défaut relève"} ` +
          `d'un raccordement de données et non de la formation ; ` +
          `${formatNumber(data.modules.length)} modules sont proposés, pour ${formatNumber(data.duree_totale_min)} minutes au total.`
        }
        signaux={[
          { label: `score ${formatPct(score, 0)} / 100`, alerte: scoreFaible },
          {
            label: `${formatNumber(structurels.length)} défauts structurels`,
            alerte: structurels.length > 0,
          },
          { label: `${formatNumber(data.controles.length)} contrôles mesurés` },
        ]}
      />

      {/* La raison de provenance était portée par un `SourceNote` en pied : il ne
          rend rien quand la source est réelle, et la tuile qui l'accueillait
          devenait alors vide. Le panneau, lui, se masque de lui-même s'il n'a
          aucune note à publier. */}
      <ScreenNotes
        notes={[
          data.note,
          estStatique(data.source)
            ? "L'ordre des modules n'est pas figé : il est recalculé à chaque consultation sur les compteurs du jour. Une saisie corrigée fait donc reculer son module dans le plan, et c'est la seule façon de vérifier qu'une formation a produit un effet."
            : null,
        ]}
      />

      <div className="kpi-row">
        <StatTile
          span={4}
          rang="principal"
          label="Score de qualité de saisie"
          aide="Une note d'ensemble de la propreté des données. Plus elle est basse, moins les indicateurs du cockpit sont fiables."
          value={formatPct(score, 0)}
          unit="/ 100"
          reading={`${formatNumber(data.qualite.nb_critiques)} contrôles critiques sur ${formatNumber(data.qualite.nb_controles)}`}
          readingVariant={scoreFaible ? "neg" : "pos"}
          detail={{
            kicker: "Indicateur · mesuré sur les données réelles",
            title: "Qualité de la saisie",
            tag: scoreFaible ? "à redresser" : "acceptable",
            tagVariant: scoreFaible ? "r" : "s",
            body: [
              `Le score ressort à ${formatPct(score, 1)} sur 100, calculé sur ${formatNumber(data.qualite.nb_controles)} contrôles dont ${formatNumber(data.qualite.nb_critiques)} sont critiques.`,
              data.qualite.methode,
              `${formatNumber(data.qualite.nb_structurels)} de ces contrôles sont STRUCTURELS : aucune formation ne les corrigera seule, ils supposent un raccordement de données.`,
            ],
            kv: [
              ["Score global", `${formatPct(score, 1)} %`],
              ["Contrôles", formatNumber(data.qualite.nb_controles)],
              ["Critiques", formatNumber(data.qualite.nb_critiques)],
              ["Attention", formatNumber(data.qualite.nb_attention)],
              ["Structurels", formatNumber(data.qualite.nb_structurels)],
            ],
          }}
        />
        <StatTile
          span={4}
          rang="contexte"
          label="Modules de formation"
          aide="Le nombre de sessions de formation prévues. Leur ordre est déterminé par les erreurs réellement constatées, pas par un programme théorique."
          value={formatNumber(data.modules.length)}
          unit="modules"
          reading={`${formatNumber(Math.round(data.duree_totale_min / 60))} h de formation au total`}
          detail={{
            kicker: "Volet transverse · contenu posé",
            title: "Plan de formation",
            tag: "priorisé par les défauts mesurés",
            tagVariant: "a",
            body: [
              `${formatNumber(data.modules.length)} modules, ${formatNumber(data.duree_totale_min)} minutes au total, ordonnés par la gravité des défauts réellement constatés dans les données.`,
              data.note,
            ],
            kv: data.modules.map((m) => [
              `${m.rang}. ${m.titre}`,
              `${formatNumber(m.duree_min)} min · ${m.public}`,
            ]),
          }}
        />
        <StatTile
          span={4}
          label="Défauts structurels"
          aide="Les problèmes qu'aucune formation ne corrigera : ils viennent de la façon dont l'outil est configuré, pas de la saisie."
          value={formatNumber(structurels.length)}
          unit="à raccorder"
          reading="hors portée d'une formation seule"
          readingVariant="wat"
          detail={{
            kicker: "Contrôles · défaut de raccordement",
            title: "Ce qu'aucune formation ne corrigera",
            tag: "raccordement",
            tagVariant: "w",
            body: [
              "Ces contrôles ne signalent pas une saisie négligée mais une donnée absente du système : il faut raccorder une synchronisation ou conserver une information que l'ERP ne transmet pas.",
              ...structurels.map((c) => `${c.libelle} — casse : ${c.indicateur_casse}.`),
            ],
            kv: structurels.map((c) => [c.libelle, c.correction]),
          }}
        />
      </div>

      <Bento>
        <Tile
          span={7}
          title="Ce qui est réellement mal saisi"
          kick="contrôles mesurés"
          aide="Les erreurs de saisie effectivement trouvées dans les données, et leur fréquence. C'est ce qui détermine l'ordre des formations."
        >
          <HintLine>Cliquez un contrôle pour l&apos;indicateur qu&apos;il casse et sa correction</HintLine>
          <Bars
            rows={data.controles.map((c) => ({
              name: c.libelle,
              sub: `${formatNumber(c.nb_defaut)} sur ${formatNumber(c.nb_total)} · ${c.objet}`,
              value: `${formatPct(c.part_defaut_pct, 1)} %`,
              pct: c.part_defaut_pct,
              variant: GRAVITE_BAR[c.gravite],
              detail: {
                kicker: c.structurel ? "Contrôle · défaut structurel" : "Contrôle · défaut de saisie",
                title: c.libelle,
                tag: c.gravite,
                tagVariant: GRAVITE_TAG[c.gravite],
                body: [
                  `${formatNumber(c.nb_defaut)} lignes en défaut sur ${formatNumber(c.nb_total)} (${formatPct(c.part_defaut_pct, 1)} %), mesuré sur ${c.objet}.`,
                  `Ce que ce défaut casse : ${c.indicateur_casse}.`,
                  c.structurel
                    ? `Défaut structurel : la donnée n'existe pas dans le système, aucune formation ne la fera apparaître. ${c.correction}`
                    : `Correction : ${c.correction}`,
                ],
                kv: [
                  ["Lignes en défaut", formatNumber(c.nb_defaut)],
                  ["Assiette", formatNumber(c.nb_total)],
                  ["Part en défaut", `${formatPct(c.part_defaut_pct, 1)} %`],
                  ["Part conforme", `${formatPct(c.part_conforme_pct, 1)} %`],
                  ["Gravité", c.gravite],
                  ["Nature", c.structurel ? "raccordement de données" : "saisie"],
                  ["Indicateur impacté", c.indicateur_casse],
                ],
              },
            }))}
          />
          <Note style={{ marginTop: 14 }}>{data.qualite.methode}</Note>
        </Tile>

        <Tile
          span={5}
          title="Règles d'or de l'utilisation du cockpit"
          kick="à rappeler en ouverture"
          aide="Les quelques principes à retenir pour ne pas dégrader les données en les saisissant."
        >
          <Lst
            items={data.regles_or.map((r, i) => ({
              title: `Règle ${i + 1}`,
              sub: r,
              tag: "règle",
              tagVariant: "a" as const,
            }))}
          />
        </Tile>

        <Tile
          span={12}
          title="Plan de formation"
          kick={`${formatNumber(data.modules.length)} modules · ordre de priorité mesuré`}
          aide="Le programme complet : quels sujets, pour qui, et dans quel ordre. Les modules les plus urgents sont ceux qui corrigent les erreurs les plus fréquentes."
        >
          <HintLine>Cliquez un module pour son contenu et le défaut qu&apos;il vise</HintLine>
          <div style={{ overflowX: "auto" }}>
            <table className="tb">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Module</th>
                  <th>Public</th>
                  <th className="r">Durée</th>
                  <th className="r">Défaut visé</th>
                  <th>Gravité</th>
                </tr>
              </thead>
              <tbody>
                {data.modules.map((m) => (
                  <tr key={m.code}>
                    <td className="mono">{m.rang}</td>
                    <td>
                      <strong style={{ fontWeight: 500 }}>{m.titre}</strong>
                      <br />
                      <span style={{ color: "var(--t3)", fontSize: 12 }}>{m.objectif}</span>
                    </td>
                    <td>{m.public}</td>
                    <td className="r mono">{formatNumber(m.duree_min)} min</td>
                    <td className="r mono">
                      {m.controle
                        ? `${formatNumber(m.controle.nb_defaut)} / ${formatNumber(m.controle.nb_total)}`
                        : "—"}
                    </td>
                    <td>
                      {m.controle && (
                        <span className={`tag tag--${GRAVITE_TAG[m.controle.gravite]}`}>
                          {m.controle.gravite}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Tile>

        {data.modules.slice(0, 3).map((m) => (
          <Tile
            key={m.code}
            span={4}
            title={m.titre}
            kick={`${formatNumber(m.duree_min)} min · ${m.public}`}
          >
            <Note style={{ marginTop: 0 }}>{m.objectif}</Note>
            <Lst
              items={m.points.map((p, i) => ({
                title: `Point ${i + 1}`,
                sub: p,
                tag: "à retenir",
                tagVariant: "n" as const,
              }))}
            />
            <Note accent style={{ marginTop: 14 }}>
              Si ce module n&apos;est pas suivi : {m.risque_si_absent.charAt(0).toLowerCase()}
              {m.risque_si_absent.slice(1)}
            </Note>
          </Tile>
        ))}

      </Bento>
    </>
  );
}
