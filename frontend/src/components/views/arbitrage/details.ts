import type {
  ArbitrageCandidate,
  ArbitrageDossier,
  ArbitrageOption,
  Decision,
  PayeurProfile,
} from "@/lib/api/arbitrage";
import type { DetailCard } from "@/components/ui/detail";
import { formatDate, formatMFcfa, formatNumber, mFcfa } from "@/lib/format";
import {
  CONSEQUENCE_LABELS,
  NATURE_VARIANT,
  PAYEUR_CLASSE_LABELS,
  STATUS_LABELS,
  VERDICT_LABELS,
  echeanceLabel,
  joursAvant,
  prioriteVariant,
  roleLabel,
  signalSummary,
  statusVariant,
} from "./shared";

/** Fiches du tiroir latéral. Un `DetailCard` est un objet sérialisable : il est
 * construit côté serveur puis traversé tel quel jusqu'aux composants client
 * (file de travail, registre) qui n'ont donc besoin d'aucune donnée brute. */

/** Fiche de détail du profil de payeur — le raisonnement complet derrière la
 * lecture affichée, pour qu'aucun de ces chiffres n'ait à être cru sur parole. */
export function payeurDetail(p: PayeurProfile, subjectRef: string): DetailCard {
  return {
    kicker: "Comportement de paiement · mesuré",
    title: `${subjectRef} — ${p.classe_label}`,
    tag: p.nature,
    tagVariant: NATURE_VARIANT[p.nature] ?? "n",
    body: [
      p.lecture,
      "Ce profil est lu sur les dates de paiement réellement synchronisées depuis Odoo — aucune inférence, aucun texte généré. C'est la seule partie du dossier qui compare le client à lui-même plutôt qu'à une norme interne.",
      "Le retard maximum, lui, n'entre pas dans le classement : il est tiré par les factures les plus anciennes du compte et vaut plus de 1 400 jours chez plusieurs clients qui règlent normalement. Comparer un client à son propre rythme récent est le seul écart qui distingue quelque chose.",
    ],
    kv: [
      ["Classe", p.classe_label],
      [
        "Délai de règlement récent",
        p.delai_recent_jours !== null
          ? `${formatNumber(p.delai_recent_jours)} j (${formatNumber(p.nb_paiements_recents)} règlement(s))`
          : `aucun règlement sur ${formatNumber(p.fenetre_mois ?? 18)} mois`,
      ],
      [
        "Délai de règlement antérieur",
        p.delai_ancien_jours !== null
          ? `${formatNumber(p.delai_ancien_jours)} j (${formatNumber(p.nb_paiements_anciens)} règlement(s))`
          : "—",
      ],
      ["Tendance", p.tendance_ratio !== null ? `${p.tendance_ratio}×` : "non calculable (fenêtres trop pauvres)"],
      ["Délai moyen tout historique", p.delai_habituel_jours !== null ? `${formatNumber(p.delai_habituel_jours)} j` : "—"],
      ["Délai contractuel accordé", p.delai_accorde_jours !== null ? `${formatNumber(p.delai_accorde_jours)} j` : "—"],
      ["Factures encaissées", formatNumber(p.nb_factures_payees)],
      ["Taux de recouvrement", p.taux_recouvrement_pct !== null ? `${p.taux_recouvrement_pct} %` : "—"],
      ["Dernier encaissement", p.dernier_paiement ? formatDate(p.dernier_paiement) : "aucun"],
      ["Retard le plus ancien (hors classement)", `${formatNumber(p.retard_max_jours)} jours`],
      ["Coût du report retenu", `${(p.cout_report_ratio_semaine * 100).toFixed(1)} % de l'enjeu / semaine`],
    ],
  };
}

export function candidateDetail(c: ArbitrageCandidate, seuilM: number): DetailCard {
  const enjeuM = mFcfa(c.enjeu_xof);
  const p = c.profil_payeur;
  return {
    kicker: "Conflit détecté · file d'arbitrage",
    title: c.subject_label,
    tag: c.priorite.label,
    tagVariant: prioriteVariant(c.priorite.niveau),
    body: [
      `Ce dossier remonte parce que ${c.subject_ref} cumule deux signaux incompatibles : ${c.positions
        .map((pos) => `${roleLabel(pos.role)} — ${pos.text}`)
        .join(" ; ")}.`,
      p.lecture,
      `Deux montants à ne pas confondre : ${formatMFcfa(c.impaye_xof)} M FCFA sont réellement dus (mesuré), tandis que l'enjeu de ${formatMFcfa(
        c.enjeu_xof
      )} M FCFA est le montant du signal commercial en jeu (${c.signal_nature}).`,
      `Le mandat revient à ${roleLabel(c.mandat_role)} : ${formatNumber(enjeuM)} M FCFA ${
        enjeuM >= seuilM ? "dépasse" : "reste sous"
      } le seuil de ${formatNumber(seuilM)} M FCFA.`,
      ...(c.signaux_portefeuille.length ? [`Signaux de portefeuille actifs : ${c.signaux_portefeuille.join(" · ")}.`] : []),
    ],
    kv: [
      ["Priorité", `${c.priorite.label} — ${c.priorite.raison}`],
      ["Comportement de paiement", `${p.classe_label} (${p.nature})`],
      [
        "Délai de règlement",
        p.delai_recent_jours !== null
          ? p.delai_ancien_jours !== null
            ? `${formatNumber(p.delai_ancien_jours)} j → ${formatNumber(p.delai_recent_jours)} j`
            : `${formatNumber(p.delai_recent_jours)} j (récent)`
          : `aucun règlement depuis ${formatNumber(p.jours_depuis_dernier_paiement ?? 0)} j`,
      ],
      ["Impayé constaté (mesuré)", `${formatMFcfa(c.impaye_xof)} M FCFA`],
      ["Factures échues", formatNumber(c.impaye_nb_factures)],
      ["Retard le plus ancien", `${formatNumber(c.retard_max_jours)} jours`],
      ["Enjeu commercial", `${formatMFcfa(c.enjeu_xof)} M FCFA (${c.signal_nature})`],
      ["Signal retenu", signalSummary(c)],
      ["Seuil de mandat DG", `${formatNumber(seuilM)} M FCFA (${enjeuM >= seuilM ? "dépassé" : "non atteint"})`],
      ["Mandat", roleLabel(c.mandat_role)],
      ["Profils impliqués", c.profils_impliques.map(roleLabel).join(" · ") || "—"],
      ...(c.commercial_compte ? [["Commercial du compte", c.commercial_compte]] : []),
      [
        "Coût du report (estimation)",
        `≈ ${formatMFcfa(c.cout_report_xof_semaine)} M FCFA / semaine (${(p.cout_report_ratio_semaine * 100).toFixed(
          1
        )} % de l'enjeu, ratio du profil de payeur)`,
      ],
      ["Échéance", echeanceLabel(c.echeance, formatDate)],
      ...(c.backlog_xof !== null ? [["Backlog", `${formatMFcfa(c.backlog_xof)} M FCFA`]] : []),
      ...(c.reste_a_encaisser_xof !== null ? [["Reste à encaisser", `${formatMFcfa(c.reste_a_encaisser_xof)} M FCFA`]] : []),
    ],
  };
}

export function decisionDetail(d: Decision): DetailCard {
  const reste = joursAvant(d.review_date);
  return {
    kicker: `Décision journalisée${d.created_at ? ` · ${formatDate(d.created_at)}` : ""}`,
    title: d.title,
    tag: STATUS_LABELS[d.status] ?? d.status,
    tagVariant: statusVariant(d.status),
    body: [
      d.context || d.subject_label || "Aucun contexte enregistré avec cette décision.",
      d.option_retenue ? `Option retenue : ${d.option_retenue}.` : "Aucune option n'a encore été retenue sur ce dossier.",
      d.option_recommandee
        ? d.reco_suivie === false
          ? `Le cockpit recommandait « ${d.option_recommandee} » : le mandataire s'en est écarté. Cet écart est enregistré tel quel — il alimente le taux de suivi, il n'est pas un reproche.`
          : `Recommandation du cockpit au moment de trancher : « ${d.option_recommandee} », suivie.`
        : "Cette décision est antérieure au suivi de la recommandation : on ne peut pas dire si elle l'a suivie ou écartée.",
      d.motif_decision ? `Motif consigné : « ${d.motif_decision} »` : "Aucun motif consigné avec cette décision.",
      d.review_verdict
        ? `Relue à échéance : recommandation ${VERDICT_LABELS[d.review_verdict] ?? d.review_verdict}${
            d.review_comment ? ` — ${d.review_comment}` : ""
          }.`
        : d.review_date
          ? reste !== null && reste < 0
            ? `Relecture due le ${formatDate(d.review_date)}, en retard de ${formatNumber(Math.abs(reste))} jour(s). Une décision sans revue n'est pas une décision, c'est une intention.`
            : `Relecture due le ${formatDate(d.review_date)}, pas encore faite.`
          : "Pas encore relue, et sans date de relecture (décision antérieure à ce module).",
    ],
    kv: [
      ["Propriétaire", d.owner || d.created_by || "—"],
      ["Créée le", formatDate(d.created_at)],
      ["Relecture due le", formatDate(d.review_date)],
      ...(d.enjeu_xof ? [["Enjeu", `${formatMFcfa(d.enjeu_xof)} M FCFA`]] : []),
      ["Mandat", d.mandat_role ? roleLabel(d.mandat_role) : "—"],
      ...(d.profil_payeur_classe
        ? [["Comportement de paiement au moment de trancher", PAYEUR_CLASSE_LABELS[d.profil_payeur_classe] ?? d.profil_payeur_classe]]
        : []),
      ["Option retenue", d.option_retenue || "—"],
      ["Option recommandée", d.option_recommandee || "non tracée"],
      ["Recommandation suivie", d.reco_suivie === null ? "non traçable" : d.reco_suivie ? "oui" : "non"],
      ["Revue", d.review_verdict ? VERDICT_LABELS[d.review_verdict] ?? d.review_verdict : "à faire"],
      ...(d.outcome ? [["Issue constatée", d.outcome]] : []),
    ],
  };
}

/** Fiche d'une option : ce qu'elle engage profil par profil, et pourquoi elle est
 * (ou n'est pas) celle que le cockpit place en tête. */
export function optionDetail(opt: ArbitrageOption, dossier: ArbitrageDossier): DetailCard {
  return {
    kicker: `Option ${opt.code}`,
    title: opt.titre,
    tag: opt.recommandee ? "recommandée" : "écartée",
    tagVariant: opt.recommandee ? "a" : "n",
    body: [
      opt.description,
      ...(opt.argumentaire ? [`À présenter au client : « ${opt.argumentaire} »`] : []),
      opt.recommandee
        ? `Le cockpit place cette option en tête parce que le client est classé « ${dossier.profil_payeur.classe_label} » : c'est cette lecture, et non le montant, qui détermine la recommandation. Il ne tranche pas — la décision retenue est journalisée au nom de l'utilisateur qui la prend, y compris si elle diffère.`
        : "Option conservée dans le dossier pour que le choix reste comparable après coup — une décision dont on ne voit plus les alternatives n'est plus auditable.",
      opt.code === "C"
        ? "Cette option est la seule à porter un engagement daté sur l'impayé lui-même. Elle ne déclenche pas encore l'action correspondante dans Odoo : le plan est arrêté ici, sa mise en œuvre reste manuelle."
        : "Cette option porte sur le futur engagement commercial. Elle ne déclenche aucune action de recouvrement (relance, mise en demeure) : ces leviers ne sont pas instrumentés dans le cockpit.",
    ],
    kv: [
      ...opt.consequences.map(
        (c) => [roleLabel(c.role), `${c.text} (${CONSEQUENCE_LABELS[c.variant] ?? c.variant})`] as [string, string]
      ),
      ...(opt.methode ? [["Méthode de calcul", opt.methode] as [string, string]] : []),
      ...(opt.redige_par
        ? [
            [
              "Formulation",
              opt.redige_par === "ia"
                ? "rédigée par l'IA (Claude) à partir du plan déjà calculé"
                : "repli déterministe — modèle indisponible",
            ] as [string, string],
          ]
        : []),
    ],
  };
}
