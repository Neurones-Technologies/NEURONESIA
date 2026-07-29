import { getArbitrageDossier, getArbitrageFile, getReliability, listDecisions } from "@/lib/api/arbitrage";
import type { ArbitrageCandidate, Decision } from "@/lib/api/arbitrage";
import { createDecisionAction, markReviewedAction } from "@/lib/actions/arbitrage";
import { ROLE_LABELS } from "@/lib/auth/roles";
import { formatDate, formatMFcfa, formatNumber } from "@/lib/format";
import { ProfileKey, Variant } from "@/lib/types";
import { Bars, FootNote, HintLine, StatTile, Tile } from "@/components/ui/bento";
import { Clickable, DetailCard } from "@/components/ui/detail";
import { Acts, Btn, MiniLabel, Note, Tag } from "@/components/ui/primitives";

/** Vue Arbitrages — connectée au backend réel (modules 26 à 29, cf.
 * `modules/uc_arbitrage`) : la file de dossiers est calculée en recoupant les
 * impayés (Direction financière) et les signaux commerciaux (renouvellement,
 * cross-sell) déjà produits par les autres modules — jamais un scénario
 * inventé. Rien n'est propre au profil : le mandat (`mandat_role`) décide qui
 * doit trancher, pas la route sur laquelle on se trouve. */

function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? (role || "—");
}

function statusVariant(status: string): Variant {
  if (status === "tranchee") return "s";
  if (status === "escaladee") return "r";
  if (status === "reportee" || status === "en_cours") return "w";
  return "n";
}

const STATUS_LABELS: Record<string, string> = {
  en_cours: "en cours",
  tranchee: "tranchée",
  reportee: "reportée",
  escaladee: "escaladée",
  suspendue: "suspendue",
};

const VERDICT_LABELS: Record<string, string> = {
  confirme: "confirmée",
  infirme: "infirmée",
  partiel: "partiellement",
};

const CONSEQUENCE_LABELS: Record<string, string> = {
  s: "favorable",
  r: "défavorable",
  w: "incertain",
  n: "neutre",
};

/** Le champ `echeance` d'un candidat vaut toujours la chaîne littérale
 * "aucune" côté backend (cf. aggregation.py) — ce n'est pas une date, jamais
 * la passer à `formatDate` sous peine d'afficher "Invalid Date". */
function echeanceLabel(echeance: string): string {
  if (!echeance || echeance === "aucune") return "aucune échéance déclarée";
  return formatDate(echeance);
}

function candidateDetail(c: ArbitrageCandidate): DetailCard {
  return {
    kicker: "Conflit détecté · file d'arbitrage",
    title: c.subject_label,
    tag: "non tranché",
    tagVariant: "r",
    body: [
      `Ce dossier remonte parce que ${c.subject_ref} cumule deux signaux incompatibles : ${c.positions
        .map((p) => `${roleLabel(p.role)} — ${p.text}`)
        .join(" ; ")}.`,
      `L'enjeu porte sur ${formatMFcfa(c.enjeu_xof)} M FCFA, avec un coût de report estimé à ${formatMFcfa(
        c.cout_report_xof_semaine
      )} M FCFA par semaine. Le mandat revient à ${roleLabel(c.mandat_role)}.`,
      ...(c.signaux_portefeuille.length
        ? [`Signaux de portefeuille actifs : ${c.signaux_portefeuille.join(" · ")}.`]
        : []),
    ],
    kv: [
      ["Enjeu", `${formatMFcfa(c.enjeu_xof)} M FCFA`],
      ["Coût du report", `${formatMFcfa(c.cout_report_xof_semaine)} M FCFA / semaine`],
      ["Échéance", echeanceLabel(c.echeance)],
      ["Mandat", roleLabel(c.mandat_role)],
      ["Profils impliqués", c.profils_impliques.map(roleLabel).join(" · ") || "—"],
      ...(c.backlog_xof !== null ? [["Backlog", `${formatMFcfa(c.backlog_xof)} M FCFA`]] : []),
      ...(c.reste_a_encaisser_xof !== null
        ? [["Reste à encaisser", `${formatMFcfa(c.reste_a_encaisser_xof)} M FCFA`]]
        : []),
    ],
    note: "Conflit obtenu par recoupement des sorties de moteurs (impayés, cross-sell, portefeuille) — aucune saisie manuelle. Ouvrir cette fiche n'écrit rien dans Odoo.",
  };
}

function decisionDetail(d: Decision): DetailCard {
  return {
    kicker: `Décision journalisée${d.created_at ? ` · ${formatDate(d.created_at)}` : ""}`,
    title: d.title,
    tag: STATUS_LABELS[d.status] ?? d.status,
    tagVariant: statusVariant(d.status),
    body: [
      d.context || d.subject_label || "Aucun contexte enregistré avec cette décision.",
      d.option_retenue
        ? `Option retenue : ${d.option_retenue}.`
        : "Aucune option n'a encore été retenue sur ce dossier.",
      d.review_verdict
        ? `Relue à échéance : recommandation ${VERDICT_LABELS[d.review_verdict] ?? d.review_verdict}${
            d.review_comment ? ` — ${d.review_comment}` : ""
          }.`
        : "Pas encore relue. Une décision sans revue n'est pas une décision, c'est une intention.",
    ],
    kv: [
      ["Propriétaire", d.owner || d.created_by || "—"],
      ["Créée le", formatDate(d.created_at)],
      ["Échéance", formatDate(d.due_date)],
      ...(d.enjeu_xof ? [["Enjeu", `${formatMFcfa(d.enjeu_xof)} M FCFA`]] : []),
      ["Mandat", d.mandat_role ? roleLabel(d.mandat_role) : "—"],
      ["Revue", d.review_verdict ? VERDICT_LABELS[d.review_verdict] ?? d.review_verdict : "à faire"],
      ...(d.outcome ? [["Issue constatée", d.outcome]] : []),
    ],
    note: "Chaque décision est relue à échéance : c'est cette relecture qui recalibre les recommandations suivantes.",
  };
}

export async function ArbitrageView({ profile }: { profile: ProfileKey }) {
  const [file, decisions, reliability] = await Promise.all([
    getArbitrageFile(),
    listDecisions(),
    getReliability(),
  ]);

  if (!file) {
    return <Note>Ce module n&apos;est pas disponible pour votre profil.</Note>;
  }

  const topCandidate = file.candidats[0];
  const dossier = topCandidate ? await getArbitrageDossier(topCandidate.subject_ref) : null;
  const recommended = dossier?.options.find((o) => o.recommandee);

  const registre = decisions ?? [];
  const aRelire = registre.filter((d) => d.status === "en_cours" && !d.review_verdict);
  const urgent = file.kpi.echeance_plus_proche_jours !== null && file.kpi.echeance_plus_proche_jours < 15;
  const tauxConfirmation = reliability?.taux_confirmation_pct ?? null;

  return (
    <>
      <div className="kpi-row">
        <StatTile
          span={4}
          label="Dossiers ouverts"
          value={formatNumber(file.kpi.dossiers_ouverts)}
          unit="dossiers"
          reading="conflits détectés + décisions en cours"
          detail={{
            kicker: "Indicateur · file d'arbitrage",
            title: "Dossiers ouverts",
            tag: file.kpi.dossiers_ouverts > 0 ? "à trancher" : "file vide",
            tagVariant: file.kpi.dossiers_ouverts > 0 ? "a" : "s",
            body: [
              `La file compte ${formatNumber(file.candidats.length)} conflit(s) détecté(s) automatiquement et ${formatNumber(
                file.decisions_ouvertes.length
              )} décision(s) déjà ouverte(s) mais non refermée(s).`,
              "Un conflit est détecté quand un même client cumule des factures échues et un signal commercial actif : les deux lectures sont vraies, elles ne peuvent simplement pas être suivies en même temps.",
            ],
            kv: [
              ["Conflits détectés", formatNumber(file.candidats.length)],
              ["Décisions ouvertes", formatNumber(file.decisions_ouvertes.length)],
              ["Enjeu cumulé", `${formatNumber(file.kpi.enjeu_cumule_m_fcfa)} M FCFA`],
            ],
            note: "Recoupement des sorties de moteurs, recalculé à chaque chargement — pas une liste tenue à la main.",
          }}
        />
        <StatTile
          span={4}
          label="Enjeu cumulé"
          value={formatNumber(file.kpi.enjeu_cumule_m_fcfa)}
          unit="M FCFA"
          reading="montant total en arbitrage"
          detail={{
            kicker: "Indicateur · enjeu",
            title: "Enjeu cumulé en arbitrage",
            tag: `${formatNumber(file.kpi.dossiers_ouverts)} dossiers`,
            tagVariant: "a",
            body: [
              `Les dossiers ouverts portent ensemble sur ${formatNumber(
                file.kpi.enjeu_cumule_m_fcfa
              )} M FCFA. C'est le montant que la décision déplace, pas une perte constatée.`,
              "L'enjeu additionne, pour chaque dossier, le montant exposé côté encaissement et le montant exposé côté commercial : c'est ce qui justifie qu'un arbitrage remonte au niveau du mandat plutôt que d'être tranché dans un service.",
            ],
            kv: [
              ["Enjeu cumulé", `${formatNumber(file.kpi.enjeu_cumule_m_fcfa)} M FCFA`],
              ["Coût du report", `${formatNumber(file.kpi.cout_report_m_fcfa_semaine)} M FCFA / semaine`],
            ],
            note: "Montants issus des factures et commandes du miroir Odoo, convertis en M FCFA.",
          }}
        />
        <StatTile
          span={4}
          label="Échéance la plus proche"
          value={file.kpi.echeance_plus_proche_jours !== null ? formatNumber(file.kpi.echeance_plus_proche_jours) : "—"}
          unit="jours"
          reading={
            file.kpi.echeance_plus_proche_jours === null
              ? "aucune échéance datée en cours"
              : urgent
                ? "sous le seuil de 15 jours"
                : "au-delà du seuil de 15 jours"
          }
          readingVariant={file.kpi.echeance_plus_proche_jours === null ? undefined : urgent ? "neg" : "wat"}
          detail={{
            kicker: "Indicateur · délai",
            title: "Échéance la plus proche",
            tag: urgent ? "fenêtre courte" : "fenêtre tenable",
            tagVariant: urgent ? "r" : "w",
            body: [
              file.kpi.echeance_plus_proche_jours !== null
                ? `Le dossier le plus contraint doit être tranché dans ${formatNumber(
                    file.kpi.echeance_plus_proche_jours
                  )} jours. Au-delà de cette date, l'option la plus favorable n'est plus disponible : le choix se fait par défaut.`
                : "Aucune décision ouverte ne porte d'échéance datée pour l'instant.",
              "Le seuil interne est de quinze jours : en dessous, la décision passe devant les autres sujets du mandat.",
            ],
            kv: [
              [
                "Jours restants",
                file.kpi.echeance_plus_proche_jours !== null
                  ? formatNumber(file.kpi.echeance_plus_proche_jours)
                  : "—",
              ],
              ["Seuil interne", "15 jours"],
              ["Coût hebdomadaire du report", `${formatNumber(file.kpi.cout_report_m_fcfa_semaine)} M FCFA`],
            ],
            note: "Échéance portée par le dossier lui-même (date de renouvellement, comité d'achat, fin de contrat).",
          }}
        />
        <StatTile
          span={4}
          label="Coût du report"
          value={formatNumber(file.kpi.cout_report_m_fcfa_semaine)}
          unit="M FCFA / semaine"
          reading="estimation, à retrancher chaque semaine sans décision"
          readingVariant="neg"
          detail={{
            kicker: "Indicateur · coût de l'attente",
            title: "Coût du report",
            tag: "estimation",
            tagVariant: "w",
            body: [
              `Ne pas trancher coûte environ ${formatNumber(
                file.kpi.cout_report_m_fcfa_semaine
              )} M FCFA par semaine, cumulés sur l'ensemble des dossiers ouverts.`,
              "C'est une estimation, pas une mesure : elle rapproche l'enjeu du dossier de la durée pendant laquelle il reste bloqué (2 % de l'enjeu par semaine). Elle sert à comparer deux reports entre eux, pas à provisionner un montant.",
            ],
            kv: [
              ["Coût hebdomadaire", `${formatNumber(file.kpi.cout_report_m_fcfa_semaine)} M FCFA`],
              ["Dossiers concernés", formatNumber(file.kpi.dossiers_ouverts)],
              ["Nature", "estimation, pas une mesure"],
            ],
            note: "Le cockpit préfère afficher une estimation signalée comme telle plutôt qu'un chiffre présenté comme exact.",
          }}
        />
        <StatTile
          span={4}
          label="Revues en retard"
          value={formatNumber(file.kpi.revues_en_retard)}
          unit="décisions"
          reading={
            file.kpi.revues_en_retard > 0
              ? "décisions non revues à leur échéance"
              : "toutes les décisions dues ont été revues"
          }
          readingVariant={file.kpi.revues_en_retard > 0 ? "wat" : "pos"}
          detail={{
            kicker: "Indicateur · registre",
            title: "Revues en retard",
            tag: file.kpi.revues_en_retard > 0 ? "à instruire" : "à jour",
            tagVariant: file.kpi.revues_en_retard > 0 ? "w" : "s",
            body: [
              file.kpi.revues_en_retard > 0
                ? `${formatNumber(
                    file.kpi.revues_en_retard
                  )} décision(s) ont dépassé leur date de revue sans verdict enregistré. Tant qu'elles ne sont pas relues, elles ne recalibrent rien.`
                : "Chaque décision arrivée à échéance a reçu son verdict de revue.",
              "La revue est le seul mécanisme qui rend l'outil vérifiable après coup : elle compare l'issue constatée à ce qui avait été recommandé.",
            ],
            kv: [
              ["Revues en retard", formatNumber(file.kpi.revues_en_retard)],
              ["Décisions au registre", formatNumber(registre.length)],
              ["Revues faites", formatNumber(registre.filter((d) => Boolean(d.review_verdict)).length)],
            ],
            note: "Le registre conserve tout, y compris les décisions antérieures à ce module.",
          }}
        />
      </div>

      {dossier && recommended && (
        <div className="dec" style={{ marginTop: 18 }}>
          <div className="dec-h">
            <h3>{dossier.subject_label}</h3>
            <p>
              Enjeu {formatMFcfa(dossier.enjeu_xof)} M FCFA · mandat {roleLabel(dossier.mandat_role)} · profils
              impliqués {dossier.profils_impliques.map(roleLabel).join(", ") || "—"}. Ne rien décider coûte{" "}
              {formatMFcfa(dossier.cout_report_xof_semaine)} M FCFA par semaine.
            </p>
          </div>
          <div className="dec-b">
            <MiniLabel>Positions en présence</MiniLabel>
            <div className="rows" style={{ marginBottom: 20 }}>
              {dossier.positions.map((p, i) => (
                <div className="row" key={i}>
                  <div className="cons" style={{ border: 0, padding: 0 }}>
                    <i>{roleLabel(p.role)}</i>
                    <span>{p.text}</span>
                  </div>
                </div>
              ))}
            </div>

            <MiniLabel>Options et conséquences par profil</MiniLabel>
            <HintLine>Cliquez une option pour ses conséquences détaillées</HintLine>
            <div className="opts">
              {dossier.options.map((opt) => (
                <Clickable
                  key={opt.code}
                  className={`opt${opt.recommandee ? " reco" : ""}`}
                  detail={{
                    kicker: `Option ${opt.code}`,
                    title: opt.titre,
                    tag: opt.recommandee ? "recommandée" : "écartée",
                    tagVariant: opt.recommandee ? "a" : "n",
                    body: [
                      opt.description,
                      opt.recommandee
                        ? "Le cockpit classe cette option en tête au regard des seuils du mandat. Il ne tranche pas : la décision retenue est journalisée au nom de l'utilisateur qui la prend."
                        : "Option conservée dans le dossier pour que le choix reste comparable après coup — une décision dont on ne voit plus les alternatives n'est plus auditable.",
                    ],
                    kv: opt.consequences.map(
                      (c) => [roleLabel(c.role), `${c.text} (${CONSEQUENCE_LABELS[c.variant] ?? c.variant})`] as [string, string]
                    ),
                    note: `Dossier ${dossier.subject_ref} · enjeu ${formatMFcfa(dossier.enjeu_xof)} M FCFA.`,
                  }}
                >
                  <div className="opt-h">
                    <span className="opt-n">Option {opt.code}</span>
                    {opt.recommandee && <Tag variant="a">recommandée</Tag>}
                  </div>
                  <div className="opt-h">
                    <b>{opt.titre}</b>
                  </div>
                  <div className="opt-d">{opt.description}</div>
                  {opt.consequences.map((c, i) => (
                    <div className="cons" key={i}>
                      <i>{roleLabel(c.role)}</i>
                      <span>{c.text}</span>
                      <span className={`tag tag--${c.variant}`} style={{ fontSize: 9 }}>
                        {CONSEQUENCE_LABELS[c.variant] ?? c.variant}
                      </span>
                    </div>
                  ))}
                </Clickable>
              ))}
            </div>

            <div className="split" style={{ marginTop: 22 }}>
              <div>
                <MiniLabel>Avocat du contraire · raisons de ne pas suivre la recommandation</MiniLabel>
                <div className="rows">
                  {dossier.contre_arguments.map((c, i) => (
                    <div className="row" key={i}>
                      <div className="row-s" style={{ margin: 0 }}>
                        {c}
                      </div>
                      <span className="ro">{String(i + 1).padStart(2, "0")}</span>
                    </div>
                  ))}
                  {dossier.contre_arguments.length === 0 && (
                    <div className="row">
                      <div className="row-s" style={{ margin: 0 }}>
                        Aucun contre-argument identifié sur ce dossier.
                      </div>
                    </div>
                  )}
                </div>
              </div>
              <div>
                <MiniLabel>Ce qui manque pour trancher</MiniLabel>
                <div className="rows">
                  {dossier.manque.map((m, i) => (
                    <div className="row-m" key={i}>
                      <div className="row-s" style={{ margin: 0 }}>
                        {m.text}
                      </div>
                      <div className="nums">{m.owner}</div>
                      <Tag variant="n">{m.delay}</Tag>
                    </div>
                  ))}
                  {dossier.manque.length === 0 && (
                    <div className="row">
                      <div className="row-s" style={{ margin: 0 }}>
                        Le dossier est complet : rien ne bloque la décision côté données.
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <FootNote>
              Le cockpit classe les options, il ne tranche pas. La décision et son motif sont journalisés au nom du
              profil qui la prend, et relus à échéance.
            </FootNote>

            <form action={createDecisionAction}>
              <input type="hidden" name="profile" value={profile} />
              <input type="hidden" name="title" value={`Arbitrage ${dossier.subject_ref}`} />
              <input type="hidden" name="context" value={dossier.subject_label} />
              <input type="hidden" name="subject_ref" value={dossier.subject_ref} />
              <input type="hidden" name="subject_label" value={dossier.subject_label} />
              <input type="hidden" name="enjeu_xof" value={dossier.enjeu_xof} />
              <input type="hidden" name="mandat_role" value={dossier.mandat_role} />
              <input type="hidden" name="profils_impliques" value={dossier.profils_impliques.join(",")} />
              <input type="hidden" name="option_retenue" value={`${recommended.code} · ${recommended.titre}`} />
              <Acts>
                <Btn primary type="submit">
                  Retenir l&apos;option {recommended.code} et journaliser
                </Btn>
              </Acts>
            </form>
          </div>
        </div>
      )}

      <div className="bento">
        <Tile span={12} title="File d'arbitrage" kick="conflits détectés · calcul réel">
          <HintLine>Cliquez un dossier pour son détail chiffré</HintLine>
          <div style={{ overflowX: "auto" }}>
            <table className="tb">
              <thead>
                <tr>
                  <th>Dossier</th>
                  <th>Profils</th>
                  <th className="r">Enjeu</th>
                  <th>Mandat</th>
                  <th>État</th>
                </tr>
              </thead>
              <tbody>
                {file.candidats.map((c) => (
                  <Clickable as="tr" key={c.subject_ref} detail={candidateDetail(c)}>
                    <td style={{ fontWeight: 500 }}>{c.subject_label}</td>
                    <td className="mono" style={{ fontSize: 11 }}>
                      {c.profils_impliques.map(roleLabel).join(" · ")}
                    </td>
                    <td className="r mono">{formatMFcfa(c.enjeu_xof)} M</td>
                    <td style={{ fontSize: 12.5, color: "var(--t2)" }}>{roleLabel(c.mandat_role)}</td>
                    <td>
                      <Tag variant="r">non tranché</Tag>
                    </td>
                  </Clickable>
                ))}
                {file.decisions_ouvertes.map((d) => (
                  <Clickable as="tr" key={`d-${d.id}`} detail={decisionDetail(d)}>
                    <td style={{ fontWeight: 500 }}>{d.subject_label || d.title}</td>
                    <td className="mono" style={{ fontSize: 11 }}>
                      {d.profils_impliques.map(roleLabel).join(" · ") || "—"}
                    </td>
                    <td className="r mono">{d.enjeu_xof ? `${formatMFcfa(d.enjeu_xof)} M` : "—"}</td>
                    <td style={{ fontSize: 12.5, color: "var(--t2)" }}>
                      {d.mandat_role ? roleLabel(d.mandat_role) : "—"}
                    </td>
                    <td>
                      <Tag variant={statusVariant(d.status)}>{STATUS_LABELS[d.status] ?? d.status}</Tag>
                    </td>
                  </Clickable>
                ))}
                {file.candidats.length === 0 && file.decisions_ouvertes.length === 0 && (
                  <tr>
                    <td colSpan={5} style={{ color: "var(--t2)" }}>
                      Aucun conflit détecté actuellement — aucun client en retard de paiement ne cumule un signal
                      commercial actif.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <FootNote>
            Un dossier est détecté quand un client cumule des factures échues ET un signal commercial actif
            (renouvellement, cross-sell) — recoupement automatique, pas une liste saisie à la main.
          </FootNote>
        </Tile>

        <Tile span={7} title="Registre des décisions" kick="toutes décisions, revues comprises">
          <HintLine>Cliquez une décision pour sa fiche</HintLine>
          <div style={{ overflowX: "auto" }}>
            <table className="tb">
              <thead>
                <tr>
                  <th>Créée le</th>
                  <th>Décision</th>
                  <th>Option retenue</th>
                  <th>État</th>
                  <th>Revue</th>
                </tr>
              </thead>
              <tbody>
                {registre.map((d) => (
                  <Clickable as="tr" key={d.id} detail={decisionDetail(d)}>
                    <td className="mono">{d.created_at ? d.created_at.slice(0, 10) : "—"}</td>
                    <td>
                      <b style={{ fontWeight: 500 }}>{d.title}</b>
                      <div style={{ color: "var(--t2)", fontSize: 12, marginTop: 2 }}>
                        {d.owner || d.created_by || "—"}
                      </div>
                    </td>
                    <td style={{ color: "var(--t2)", fontSize: 12.5 }}>{d.option_retenue || "—"}</td>
                    <td>
                      <Tag variant={statusVariant(d.status)}>{STATUS_LABELS[d.status] ?? d.status}</Tag>
                    </td>
                    <td>
                      {d.review_verdict ? (
                        <Tag
                          variant={
                            d.review_verdict === "confirme" ? "s" : d.review_verdict === "infirme" ? "r" : "w"
                          }
                        >
                          {VERDICT_LABELS[d.review_verdict] ?? d.review_verdict}
                        </Tag>
                      ) : (
                        <span className="ro">à faire</span>
                      )}
                    </td>
                  </Clickable>
                ))}
                {registre.length === 0 && (
                  <tr>
                    <td colSpan={5} style={{ color: "var(--t2)" }}>
                      Aucune décision enregistrée.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <FootNote>
            Chaque décision est relue à échéance : c&apos;est cette relecture qui recalibre les recommandations
            suivantes. Le registre conserve tout, y compris les décisions antérieures à ce module.
          </FootNote>
        </Tile>

        <Tile span={5} title="Fiabilité des recommandations" kick="registre · décisions revues">
          {reliability ? (
            <>
              <Bars
                rows={[
                  {
                    name: "Taux de confirmation",
                    sub:
                      tauxConfirmation !== null
                        ? `${formatNumber(reliability.nb_confirmees)} confirmées sur ${formatNumber(
                            reliability.nb_decisions_revues
                          )} revues`
                        : "historique insuffisant pour un taux",
                    value: tauxConfirmation !== null ? `${tauxConfirmation} %` : "—",
                    pct: Math.min(tauxConfirmation ?? 0, 100),
                    variant: reliability.historique_suffisant ? "s" : "w",
                  },
                  {
                    name: "Décisions revues",
                    sub: "seuil de représentativité : 5 revues",
                    value: formatNumber(reliability.nb_decisions_revues),
                    pct: Math.min((reliability.nb_decisions_revues / 5) * 100, 100),
                    variant: reliability.historique_suffisant ? "s" : "w",
                  },
                ]}
              />
              <Note>{reliability.note}</Note>
              <FootNote>
                Tant que l&apos;historique est insuffisant, aucun taux n&apos;est affiché comme définitif : mieux vaut
                l&apos;absence de chiffre qu&apos;un chiffre non représentatif.
              </FootNote>
            </>
          ) : (
            <Note style={{ marginTop: 0 }}>Score de fiabilité non accessible depuis ce profil.</Note>
          )}
        </Tile>

        {aRelire.length > 0 && (
          <Tile span={12} title="Revues à faire" kick={`${aRelire.length} décision(s) sans verdict`}>
            <div className="rows">
              {aRelire.map((d) => (
                <div className="row-m" key={d.id}>
                  <div>
                    <div className="row-n">{d.title}</div>
                    <div className="row-s">
                      {d.owner || d.created_by || "—"} · créée le {formatDate(d.created_at)}
                      {d.option_retenue ? ` · ${d.option_retenue}` : ""}
                    </div>
                  </div>
                  <div className="nums">{d.due_date ? `échéance ${formatDate(d.due_date)}` : "sans échéance"}</div>
                  <form action={markReviewedAction}>
                    <input type="hidden" name="profile" value={profile} />
                    <input type="hidden" name="decision_id" value={d.id} />
                    <input type="hidden" name="review_verdict" value="confirme" />
                    <Btn type="submit">Marquer revue</Btn>
                  </form>
                </div>
              ))}
            </div>
            <FootNote>
              Marquer une revue enregistre le verdict et la date : c&apos;est ce qui alimente le score de fiabilité
              ci-dessus. Une décision sans date de revue n&apos;est pas une décision, c&apos;est une intention.
            </FootNote>
          </Tile>
        )}
      </div>
    </>
  );
}
