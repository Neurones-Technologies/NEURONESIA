import Link from "next/link";
import { getBriefing } from "@/lib/api/briefing";
import { getClientPortfolio, getClientProfile, ClientProfile } from "@/lib/api/clients";
import { getCrossSellAnalysis, getCrossSellSignals } from "@/lib/api/crosssell";
import { getNextActions } from "@/lib/api/dashboard";
import { formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, Brief, /* FootNote, */ HintLine, Lst, StatTile, Tile } from "@/components/ui/bento";
import { AnalysisSlot } from "@/components/ui/analysis-slot";
import { Narr, Note } from "@/components/ui/primitives";

function daysSince(dateStr: string | null): number | null {
  if (!dateStr) return null;
  const diff = Date.now() - new Date(dateStr).getTime();
  return Math.floor(diff / (1000 * 60 * 60 * 24));
}

export async function AmVision() {
  // Narration LLM exclue du Promise.all — voir components/ui/analysis-slot.tsx :
  // figée à la journée, mais 10-20 s si le calcul de secours se déclenche.
  const [portfolio, actions, crosssell, briefing] = await Promise.all([
    getClientPortfolio(50),
    getNextActions(8),
    getCrossSellSignals(),
    getBriefing(),
  ]);

  const briefLines = briefing?.section?.resume?.length
    ? briefing.section.resume
    : (briefing?.section?.bullets ?? []).slice(0, 5);

  const totalCa = (portfolio ?? []).reduce((s, c) => s + c.ca_total_xof, 0);
  const totalReste = (portfolio ?? []).reduce((s, c) => s + c.reste_a_encaisser_xof, 0);
  const focusClient = portfolio?.[0];
  const profile: ClientProfile | null = focusClient ? await getClientProfile(focusClient.client) : null;

  const rupture = (portfolio ?? [])
    .map((c) => ({ ...c, jours: daysSince(c.derniere_commande) }))
    .filter((c) => c.jours !== null && c.jours > 90)
    .sort((a, b) => (b.jours ?? 0) - (a.jours ?? 0))
    .slice(0, 5);

  const totalActionsValue = (actions?.actions ?? []).reduce((s, a) => s + a.montant_xof, 0);
  const topAction = actions?.actions[0];
  const worstRupture = rupture[0];
  const topClientCa = portfolio?.[0]?.ca_total_xof ?? 0;

  return (
    <>
      <Brief
        kicker="Portefeuille · terrain"
        headline={
          topAction
            ? `${formatNumber(actions?.actions.length ?? 0)} actions prioritaires, ${formatMFcfa(totalActionsValue)} M FCFA en jeu.`
            : `${formatNumber((portfolio ?? []).length)} comptes suivis, ${formatMFcfa(totalCa)} M FCFA facturés.`
        }
        lines={
          briefLines.length
            ? briefLines
            : [
                topAction
                  ? `Action la plus urgente : ${topAction.client}, ${topAction.type.toLowerCase()} pour ${formatMFcfa(topAction.montant_xof)} M FCFA.`
                  : "Aucune action prioritaire détectée sur votre portefeuille.",
                worstRupture
                  ? `${worstRupture.client} : ${formatNumber(worstRupture.jours ?? 0)} jours sans commande, le plus long silence du portefeuille.`
                  : "Aucun compte au-delà de 90 jours sans commande.",
                totalReste > 0
                  ? `${formatMFcfa(totalReste)} M FCFA restent à encaisser sur l'ensemble de vos comptes.`
                  : "Aucun reste à encaisser sur le portefeuille.",
              ]
        }
        pills={[
          { label: `${formatNumber((portfolio ?? []).length)} comptes` },
          { label: `${formatNumber(actions?.actions.length ?? 0)} actions prioritaires`, hot: (actions?.actions.length ?? 0) > 0 },
          { label: `${formatNumber(rupture.length)} sans commande > 90 j`, hot: rupture.length > 0 },
          { label: `${formatMFcfa(totalReste)} M à encaisser`, hot: totalReste > 0 },
        ]}
      />

      <Bento>
        <StatTile
          span={4}
          label="CA cumulé du portefeuille"
          aide="Ce que vos clients vous ont acheté au total. C'est le poids de votre portefeuille."
          value={formatMFcfa(totalCa)}
          unit="M FCFA"
          reading={`${formatNumber((portfolio ?? []).length)} comptes actifs`}
          detail={{
            kicker: "Indicateur · portefeuille",
            title: "Chiffre d'affaires du portefeuille",
            tag: `${formatNumber((portfolio ?? []).length)} comptes`,
            tagVariant: "a",
            body: [
              `Vos ${formatNumber((portfolio ?? []).length)} comptes cumulent ${formatMFcfa(totalCa)} M FCFA de facturation.`,
              focusClient
                ? `Le premier d'entre eux, ${focusClient.client}, pèse ${formatMFcfa(focusClient.ca_total_xof)} M FCFA, soit ${totalCa ? formatPct((focusClient.ca_total_xof / totalCa) * 100, 0) : "—"} % de votre portefeuille.`
                : "Aucun compte facturé sur le portefeuille.",
            ],
            kv: [
              ["CA cumulé", `${formatMFcfa(totalCa)} M FCFA`],
              ["Comptes", formatNumber((portfolio ?? []).length)],
              ["Reste à encaisser", `${formatMFcfa(totalReste)} M FCFA`],
            ],
            // note: "Somme des factures rattachées aux comptes de votre portefeuille dans le miroir Odoo.",
          }}
        />
        <StatTile
          span={4}
          label="Reste à encaisser"
          aide="Ce que vos clients vous doivent encore. Une partie de votre travail consiste à faire rentrer cet argent."
          value={formatMFcfa(totalReste)}
          unit="M FCFA"
          reading={totalReste > 0 ? "sur l'ensemble du portefeuille" : "portefeuille soldé"}
          readingVariant={totalReste > 0 ? "wat" : "pos"}
          detail={{
            kicker: "Indicateur · encaissement",
            title: "Reste à encaisser sur le portefeuille",
            tag: totalReste > 0 ? "en attente" : "soldé",
            tagVariant: totalReste > 0 ? "w" : "s",
            body: [
              `${formatMFcfa(totalReste)} M FCFA de facturation émise sur vos comptes n'ont pas encore été réglés.`,
              "Un encours ouvert change la façon d'aborder un rendez-vous : mieux vaut connaître le montant avant d'entrer que de le découvrir en séance.",
            ],
            kv: [
              ["Reste à encaisser", `${formatMFcfa(totalReste)} M FCFA`],
              ["CA cumulé", `${formatMFcfa(totalCa)} M FCFA`],
              [
                "Part non encaissée",
                totalCa ? `${formatPct((totalReste / totalCa) * 100, 0)} %` : "—",
              ],
            ],
            // note: "Le détail par facture est réservé aux profils financiers.",
          }}
        />
        <StatTile
          span={4}
          label="Comptes sans commande > 90 j"
          aide="Vos clients qui n'ont rien commandé depuis plus de trois mois. Au-delà de ce délai, la relation se distend et le client peut être en train de partir ailleurs."
          value={formatNumber(rupture.length)}
          unit={`sur ${formatNumber((portfolio ?? []).length)}`}
          reading={
            worstRupture
              ? `le plus long : ${formatNumber(worstRupture.jours ?? 0)} jours`
              : "aucune rupture de rythme"
          }
          readingVariant={rupture.length > 0 ? "neg" : "pos"}
          detail={{
            kicker: "Indicateur · rupture de rythme",
            title: "Comptes en silence prolongé",
            tag: rupture.length > 0 ? "à relancer" : "aucun",
            tagVariant: rupture.length > 0 ? "r" : "s",
            body: [
              rupture.length > 0
                ? `${formatNumber(rupture.length)} compte(s) de votre portefeuille n'ont pas commandé depuis plus de 90 jours.`
                : "Tous vos comptes ont commandé dans les 90 derniers jours.",
              worstRupture
                ? `Le cas le plus marqué est ${worstRupture.client}, silencieux depuis ${formatNumber(worstRupture.jours ?? 0)} jours alors qu'il a déjà passé ${formatNumber(worstRupture.nb_dossiers)} commande(s). Un compte qui a acheté puis se tait n'est pas un compte froid : c'est un compte à rappeler.`
                : "Aucun signal de rupture à traiter cette semaine.",
            ],
            kv: [
              ["Comptes en rupture", formatNumber(rupture.length)],
              ["Seuil retenu", "90 jours sans commande"],
              ...(worstRupture
                ? [
                    ["Cas le plus ancien", worstRupture.client],
                    ["Silence", `${formatNumber(worstRupture.jours ?? 0)} jours`],
                  ]
                : []),
            ],
            // note: "Écart entre la date de dernière commande et la date du jour. L'historique d'intervalle individuel n'est pas instrumenté.",
          }}
        />

        {focusClient && (
          <Tile
            span={7}
            title="Fiche compte"
            kick={focusClient.client}
            aide="Tout ce qu'il faut savoir sur un client avant de l'appeler : ce qu'il achète, ce qu'il doit, où en sont les affaires en cours."
          >
            <Narr style={{ fontSize: 13.5, marginBottom: 14 }}>
              {profile?.activite && <p>{profile.activite}</p>}
              {(profile?.recommandations ?? []).map((r, i) => (
                <p key={i}>
                  <b>À faire :</b> {r}
                </p>
              ))}
              {focusClient.signaux.map((s, i) => (
                <p key={`sig-${i}`}>{s}</p>
              ))}
            </Narr>
            <div className="kv">
              <div>
                <span>CA cumulé</span>
                <b>{formatMFcfa(focusClient.ca_total_xof)} M FCFA</b>
              </div>
              <div>
                <span>Dossiers</span>
                <b>{formatNumber(focusClient.nb_dossiers)}</b>
              </div>
              <div>
                <span>Reste à encaisser</span>
                <b>{formatMFcfa(focusClient.reste_a_encaisser_xof)} M FCFA</b>
              </div>
              <div>
                <span>Dernière commande</span>
                <b>{focusClient.derniere_commande ?? "—"}</b>
              </div>
              <div>
                <span>Dernier projet</span>
                <b>{focusClient.dernier_projet ?? "—"}</b>
              </div>
            </div>
          </Tile>
        )}

        <Tile
          span={5}
          title="Ma prochaine action"
          kick={`${formatNumber(actions?.actions.length ?? 0)} actions`}
          aide="Ce qu'il y a de plus utile à faire maintenant, dans l'ordre. Une liste de travail, pas un tableau de bord à interpréter."
        >
          {actions && actions.actions.length > 0 ? (
            <>
              <HintLine>Cliquez une action pour son contexte</HintLine>
              <Lst
                items={actions.actions.map((a) => ({
                  title: a.client,
                  sub: a.texte,
                  tag: `${formatMFcfa(a.montant_xof)} M`,
                  tagVariant:
                    a.type === "Recouvrement" ? ("r" as const) : a.type === "Renouvellement" ? ("w" as const) : ("a" as const),
                  detail: {
                    kicker: `Action · ${a.type}`,
                    title: a.client,
                    tag: a.type,
                    tagVariant:
                      a.type === "Recouvrement"
                        ? ("r" as const)
                        : a.type === "Renouvellement"
                          ? ("w" as const)
                          : ("a" as const),
                    body: [
                      a.texte,
                      `Montant engagé : ${formatMFcfa(a.montant_xof)} M FCFA. Cette action est classée par montant parmi ${formatNumber(actions.actions.length)} signaux, pour un total de ${formatMFcfa(totalActionsValue)} M FCFA.`,
                    ],
                    kv: [
                      ["Client", a.client],
                      ["Type", a.type],
                      ["Montant engagé", `${formatMFcfa(a.montant_xof)} M FCFA`],
                    ],
                    // note: actions.note ?? "Signaux issus des modules Portefeuille, Montée en valeur et Trésorerie.",
                  },
                }))}
              />
              {/* <FootNote>{actions.note}</FootNote> */}
            </>
          ) : (
            <Note style={{ marginTop: 0 }}>Aucune action prioritaire détectée actuellement.</Note>
          )}
        </Tile>

        <Tile
          span={7}
          title="Mon portefeuille par poids"
          kick="CA facturé"
          aide="Vos clients classés par ce qu'ils vous rapportent. Sert à répartir votre temps en connaissance de cause."
        >
          {portfolio && portfolio.length > 0 ? (
            <>
              <HintLine>Cliquez un compte pour sa fiche</HintLine>
              <Bars
                rows={portfolio.slice(0, 6).map((c) => {
                  const jours = daysSince(c.derniere_commande);
                  const part = totalCa ? (c.ca_total_xof / totalCa) * 100 : 0;
                  return {
                    name: c.client,
                    sub: `${formatNumber(c.nb_dossiers)} dossier(s) · ${jours !== null ? `dernière commande il y a ${formatNumber(jours)} j` : "date inconnue"}`,
                    value: `${formatMFcfa(c.ca_total_xof)} M`,
                    pct: topClientCa ? (c.ca_total_xof / topClientCa) * 100 : 0,
                    variant:
                      jours !== null && jours > 90
                        ? ("r" as const)
                        : c.reste_a_encaisser_xof > 0
                          ? ("w" as const)
                          : undefined,
                    detail: {
                      kicker: "Compte du portefeuille",
                      title: c.client,
                      tag:
                        jours !== null && jours > 90
                          ? "silence prolongé"
                          : c.reste_a_encaisser_xof > 0
                            ? "encours ouvert"
                            : "compte sain",
                      tagVariant:
                        jours !== null && jours > 90
                          ? ("r" as const)
                          : c.reste_a_encaisser_xof > 0
                            ? ("w" as const)
                            : ("s" as const),
                      body: [
                        `${c.client} totalise ${formatMFcfa(c.ca_total_xof)} M FCFA sur ${formatNumber(c.nb_dossiers)} dossier(s), soit ${formatPct(part, 0)} % de votre portefeuille.`,
                        jours !== null && jours > 90
                          ? `Aucune commande depuis ${formatNumber(jours)} jours. Sur un compte qui a déjà acheté, ce silence est le signal le plus actionnable de la fiche.`
                          : c.reste_a_encaisser_xof > 0
                            ? `${formatMFcfa(c.reste_a_encaisser_xof)} M FCFA restent à encaisser : à connaître avant toute nouvelle négociation.`
                            : "Compte à jour, sans encours ouvert ni rupture de rythme.",
                        ...c.signaux,
                      ],
                      kv: [
                        ["CA cumulé", `${formatMFcfa(c.ca_total_xof)} M FCFA`],
                        ["Part du portefeuille", `${formatPct(part, 0)} %`],
                        ["Dossiers", formatNumber(c.nb_dossiers)],
                        ["Reste à encaisser", `${formatMFcfa(c.reste_a_encaisser_xof)} M FCFA`],
                        ["Dernière commande", c.derniere_commande ?? "—"],
                        ["Dernier projet", c.dernier_projet ?? "—"],
                      ],
                      // note: "Fiche assemblée à partir des commandes et factures réelles du compte.",
                    },
                  };
                })}
              />
            </>
          ) : (
            <Note style={{ marginTop: 0 }}>Portefeuille vide ou module non disponible.</Note>
          )}
        </Tile>

        <Tile
          span={5}
          title="Alerte rupture de rythme"
          kick="sans commande > 90 j"
          aide="Les clients qui commandaient régulièrement et se sont tus. Le silence d'un habitué est un signal, pas une pause."
        >
          {rupture.length > 0 ? (
            <Lst
              items={rupture.map((c) => ({
                title: c.client,
                sub: `Dernière commande le ${c.derniere_commande} · ${formatNumber(c.nb_dossiers)} dossier(s)`,
                tag: `${formatNumber(c.jours ?? 0)} j`,
                tagVariant: "r" as const,
                detail: {
                  kicker: "Rupture de rythme",
                  title: c.client,
                  tag: `${formatNumber(c.jours ?? 0)} jours de silence`,
                  tagVariant: "r" as const,
                  body: [
                    `Dernière commande le ${c.derniere_commande}, soit ${formatNumber(c.jours ?? 0)} jours sans activité, sur un compte qui a déjà passé ${formatNumber(c.nb_dossiers)} commande(s) pour ${formatMFcfa(c.ca_total_xof)} M FCFA.`,
                    "Le cockpit ne connaît pas la cause du silence : budget gelé, interlocuteur parti, ou besoin traité ailleurs. C'est précisément ce qu'un appel permet de trancher.",
                  ],
                  kv: [
                    ["Silence", `${formatNumber(c.jours ?? 0)} jours`],
                    ["Dernière commande", c.derniere_commande ?? "—"],
                    ["CA historique", `${formatMFcfa(c.ca_total_xof)} M FCFA`],
                    ["Dossiers", formatNumber(c.nb_dossiers)],
                    ["Reste à encaisser", `${formatMFcfa(c.reste_a_encaisser_xof)} M FCFA`],
                  ],
                  // note: "Seuil de 90 jours, sans historique d'intervalle individuel (feuilles de temps hors périmètre).",
                },
              }))}
            />
          ) : (
            <Note style={{ marginTop: 0 }}>
              Aucun compte du portefeuille n&apos;a dépassé 90 jours sans commande.
            </Note>
          )}
        </Tile>

        <Tile
          span={12}
          title="Radar renouvellement et obsolescence"
          kick="narration"
          aide="Les contrats et équipements qui arrivent en fin de vie chez vos clients. Autant d'occasions de revenir les voir avant un concurrent."
        >
          <AnalysisSlot load={getCrossSellAnalysis} />
          {crosssell && (
            <div style={{ marginTop: 18 }}>
              <HintLine>Cliquez un signal pour son détail</HintLine>
              <Lst
                items={[...crosssell.renouvellement, ...crosssell.obsolete]
                  .sort((a, b) => b.montant_xof - a.montant_xof)
                  .slice(0, 6)
                  .map((it) => {
                    const isRenew = crosssell.renouvellement.includes(it);
                    return {
                      title: it.client,
                      sub: it.detail,
                      tag: it.titre,
                      tagVariant: isRenew ? ("w" as const) : ("n" as const),
                      detail: {
                        kicker: isRenew ? "Signal · renouvellement" : "Signal · obsolescence",
                        title: it.client,
                        tag: it.titre,
                        tagVariant: isRenew ? ("w" as const) : ("n" as const),
                        body: [
                          it.detail,
                          `Montant historique associé : ${formatMFcfa(it.montant_xof)} M FCFA.`,
                          isRenew
                            ? "Un renouvellement se prépare avant l'échéance, pas après : passé la date, la discussion se fait en position défensive."
                            : "Une catégorie en fin de cycle est une porte d'entrée : le besoin existe déjà, il s'agit de le requalifier avant qu'un concurrent ne le fasse.",
                        ],
                        kv: [
                          ["Montant", `${formatMFcfa(it.montant_xof)} M FCFA`],
                          ["Type de signal", it.titre],
                        ],
                        // note: "Calculé sur les vraies lignes de commande (catégories achetées et ancienneté).",
                      },
                    };
                  })}
              />
            </div>
          )}
        </Tile>

        <Tile
          span={12}
          quiet
          title="Aide à la rédaction contextualisée"
          kick="narration"
          aide="De quoi rédiger un message ou une proposition à partir de ce que le cockpit sait déjà du client."
        >
          <p style={{ margin: "0 0 4px", fontSize: 14, color: "var(--t2)", lineHeight: 1.6 }}>
            Le Copilote rédige relances, propositions et comptes rendus à partir des données réelles du compte.
            Demandez par exemple : « Rédige une relance pour {focusClient?.client ?? "un client"} ».
          </p>
          <div className="acts">
            <Link className="btn btn--p" href="/am/copilot">
              Ouvrir Mon Copilote
            </Link>
          </div>
        </Tile>
      </Bento>
    </>
  );
}
