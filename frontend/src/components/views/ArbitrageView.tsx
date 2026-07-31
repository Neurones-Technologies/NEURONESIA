import { getArbitrageDossier, getArbitrageFile, listDecisions } from "@/lib/api/arbitrage";
import type {
  ArbitrageCandidate,
  ArbitrageDossier,
  Decision,
  PayeurClasse,
  PayeurProfile,
  SignalNature,
} from "@/lib/api/arbitrage";
import { addContexteAction, createDecisionAction } from "@/lib/actions/arbitrage";
import { apiFetch } from "@/lib/api/client";
import { isAdminRole, ROLE_LABELS, roleToProfile } from "@/lib/auth/roles";
import { META } from "@/lib/data/profiles";
import { formatDate, formatMFcfa, formatNumber, mFcfa } from "@/lib/format";
import { ProfileKey, Variant } from "@/lib/types";
import { /* FootNote, */ HintLine, StatTile, Tile } from "@/components/ui/bento";
import { Clickable, DetailCard } from "@/components/ui/detail";
import { Acts, Btn, MiniLabel, Note, Tag } from "@/components/ui/primitives";
import { ArbitrageScopeToggle } from "@/components/views/ArbitrageScopeToggle";

/** Vue Arbitrages — connectée au backend réel (modules 26 à 29, cf.
 * `modules/uc_arbitrage`) : la file de dossiers est calculée en recoupant les
 * impayés (Direction financière) et les signaux commerciaux (renouvellement,
 * cross-sell) déjà produits par les autres modules — jamais un scénario inventé.
 *
 * Le mandat (`mandat_role`) est la seule autorité qui peut engager OU refermer un
 * dossier : vérifié ici pour l'affichage, et côté backend (`create_decision` et
 * `update_decision`) pour l'exécution. Chaque chiffre affiché porte sa nature
 * (mesuré / observé / inféré) pour qu'une déduction ne se lise pas comme un fait. */

interface Me {
  role: string;
}

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

/** Un fait lu dans le miroir est fiable, une déduction sur cycle supposé ne l'est
 * pas au même titre — la teinte le dit sans avoir à lire la note de méthode. */
const NATURE_VARIANT: Record<SignalNature, Variant> = {
  mesuré: "s",
  observé: "n",
  inféré: "w",
};

/** Libellés des classes de payeur — doublon assumé de `payeur.CLASSE_LABELS`
 * côté backend : une décision journalisée conserve la CLASSE brute qui a servi à
 * la prendre (`profil_payeur_classe`), pas son libellé, pour que le registre reste
 * relisible même si la formulation évolue. Il faut donc pouvoir la traduire ici. */
const PAYEUR_CLASSE_LABELS: Record<string, string> = {
  intragroupe: "entité du groupe",
  amelioration: "paie mieux qu'avant",
  stable_rapide: "payeur rapide et stable",
  stable_lent: "payeur lent mais stable",
  stable: "comportement stable",
  vigilance: "ralentissement modéré",
  degradation: "ralentissement marqué",
  paiements_stoppes: "paiements arrêtés",
  defaillance_probable: "défaillance probable",
  historique_insuffisant: "historique insuffisant",
  non_calcule: "profil non calculé",
};

/** Teinte de la classe de payeur. Le vert n'est pas « bon client » mais « rien
 * dans son comportement de paiement ne justifie de bloquer » — la nuance compte,
 * un client stable peut devoir 3 milliards. */
const PAYEUR_VARIANT: Record<PayeurClasse, Variant> = {
  paiements_stoppes: "r",
  defaillance_probable: "r",
  degradation: "r",
  vigilance: "w",
  historique_insuffisant: "w",
  stable: "n",
  stable_lent: "s",
  stable_rapide: "s",
  amelioration: "s",
  intragroupe: "n",
  non_calcule: "n",
};

/** Ce que la classe implique comme conduite, en une ligne — la traduction du
 * constat en langage de décision, sans reprendre la recommandation d'option. */
const PAYEUR_PORTEE: Record<PayeurClasse, string> = {
  paiements_stoppes: "le client s'est arrêté de payer : appeler avant de décider",
  defaillance_probable: "aucun encaissement jamais constaté",
  degradation: "ralentissement réel — c'est le cas où bloquer se justifie",
  vigilance: "à signaler, pas encore à sanctionner",
  historique_insuffisant: "trop peu de paiements pour conclure",
  stable: "rien de nouveau côté risque client",
  stable_lent: "retard structurel, pas une défaillance",
  stable_rapide: "probable incident de facturation",
  amelioration: "dynamique favorable, un blocage la casserait",
  intragroupe: "compte courant du groupe, pas un impayé client",
  non_calcule: "calcul absent — dossier instruit sur le seul impayé",
};

/** Trajectoire de paiement affichée : `36 j → 52 j`, ou le fait qu'elle n'existe
 * pas. Un client sans règlement récent n'a pas de trajectoire — il a un silence,
 * et c'est ce silence qu'on montre à sa place. */
function payeurTrajectoire(p: PayeurProfile): { valeur: string; avant: string | null; legende: string } {
  if (p.classe === "paiements_stoppes" || p.nb_paiements_recents === 0) {
    return {
      valeur: p.jours_depuis_dernier_paiement !== null ? `${formatNumber(p.jours_depuis_dernier_paiement)} j` : "—",
      avant: p.delai_ancien_jours !== null ? `${formatNumber(p.delai_ancien_jours)} j` : null,
      legende: "sans aucun encaissement",
    };
  }
  if (p.delai_recent_jours === null) {
    return { valeur: "—", avant: null, legende: "délai de paiement non mesurable" };
  }
  return {
    valeur: `${formatNumber(p.delai_recent_jours)} j`,
    avant: p.delai_ancien_jours !== null ? `${formatNumber(p.delai_ancien_jours)} j` : null,
    legende: p.delai_ancien_jours !== null ? "délai de règlement, avant → maintenant" : "délai de règlement récent",
  };
}

/** Fiche de détail du profil de payeur — le raisonnement complet derrière la
 * lecture affichée, pour qu'aucun de ces chiffres n'ait à être cru sur parole. */
function payeurDetail(p: PayeurProfile, subjectRef: string): DetailCard {
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
    // note: "Fenêtre de comparaison : 18 mois. Sous 2 règlements dans l'une des deux fenêtres, la tendance n'est pas calculée du tout plutôt que présentée comme stable.",
  };
}

/** Bandeau de lecture du comportement de paiement, placé avant les montants :
 * c'est lui qui décide de la conduite à tenir, les montants disent seulement
 * combien elle pèse. */
function PayeurBandeau({ profil, subjectRef }: { profil: PayeurProfile; subjectRef: string }) {
  const t = payeurTrajectoire(profil);
  const variant = PAYEUR_VARIANT[profil.classe] ?? "n";
  return (
    <Clickable className={`pay pay--${variant}`} detail={payeurDetail(profil, subjectRef)}>
      <div>
        <div className="pay-t">
          {t.avant && (
            <>
              <s>{t.avant}</s>
              <i>→</i>
            </>
          )}
          <b>{t.valeur}</b>
        </div>
        <div className="pay-l">{t.legende}</div>
      </div>
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
          <Tag variant={variant}>{profil.classe_label}</Tag>
          <Tag variant={NATURE_VARIANT[profil.nature] ?? "n"}>{profil.nature}</Tag>
          <span className="ro">{PAYEUR_PORTEE[profil.classe]}</span>
        </div>
        <p className="pay-b">{profil.lecture}</p>
      </div>
    </Clickable>
  );
}

const ACTIF_LABELS: Record<string, string> = {
  oui: "dossier commercial toujours d'actualité",
  non: "dossier commercial abandonné côté client",
  incertain: "actualité du dossier incertaine",
};

/** Contribution du terrain sur un dossier.
 *
 * C'est la seule action de cet écran ouverte à un profil SANS mandat, et c'est
 * délibéré : le dossier réclame explicitement le motif du retard en désignant le
 * compte comme détenteur de l'information, alors que l'account manager n'a jamais
 * le mandat (celui-ci revient à la direction financière ou à la DG selon le
 * montant). Le profil qui détient le fait décisif n'avait donc aucun moyen de le
 * verser au dossier. Les contributions s'empilent au lieu de s'écraser : si le
 * motif change entre deux passages en comité, ce changement est lui-même une
 * information que la revue à 30 jours doit pouvoir relire. */
function ContexteTerrain({ dossier, profile }: { dossier: ArbitrageDossier; profile: ProfileKey }) {
  const contextes = dossier.contextes_terrain ?? [];
  return (
    <div style={{ marginTop: 22 }}>
      <MiniLabel>Contexte terrain · ce que seul le compte peut dire</MiniLabel>
      <p style={{ fontSize: 11.5, color: "var(--t3)", fontStyle: "italic", margin: "0 0 10px" }}>
        Aucun mandat requis pour contribuer ici : apporter un fait n&apos;est pas engager l&apos;entreprise.
        {dossier.commercial_compte ? ` Compte suivi par ${dossier.commercial_compte}.` : ""}
      </p>

      {contextes.length > 0 && (
        <div className="rows" style={{ marginBottom: 12 }}>
          {contextes.map((c) => (
            <div className="row-m" key={c.id}>
              <div>
                <div className="row-n">{c.motif_retard || "— (aucun motif renseigné)"}</div>
                <div className="row-s">
                  {roleLabel(c.created_role)} · {c.created_by}
                  {c.created_at ? ` · ${formatDate(c.created_at)}` : ""}
                </div>
              </div>
              <div />
              {c.dossier_toujours_actif ? (
                <Tag variant={c.dossier_toujours_actif === "non" ? "r" : c.dossier_toujours_actif === "oui" ? "s" : "w"}>
                  {ACTIF_LABELS[c.dossier_toujours_actif] ?? c.dossier_toujours_actif}
                </Tag>
              ) : (
                <span className="ro">—</span>
              )}
            </div>
          ))}
        </div>
      )}

      <form action={addContexteAction}>
        <input type="hidden" name="profile" value={profile} />
        <input type="hidden" name="subject_ref" value={dossier.subject_ref} />
        <div className="dform" style={{ borderTop: 0, paddingTop: 0 }}>
          <div className="dform-r">
            <label htmlFor="ctx-motif">Motif du retard</label>
            <textarea
              id="ctx-motif"
              className="txa"
              name="motif_retard"
              placeholder="Ce que le client a répondu — attente de mandatement, litige sur une prestation, changement d'interlocuteur… Le miroir Odoo ne contient rien de tout cela."
            />
          </div>
          <div className="dform-r">
            <label htmlFor="ctx-actif">Dossier commercial encore d&apos;actualité ?</label>
            <select id="ctx-actif" className="sel" name="dossier_toujours_actif" defaultValue="">
              <option value="">Sans réponse</option>
              <option value="oui">Oui — le client confirme</option>
              <option value="non">Non — le client a renoncé</option>
              <option value="incertain">Incertain — pas de réponse claire</option>
            </select>
          </div>
        </div>
        <Acts>
          <Btn type="submit">Verser au dossier</Btn>
        </Acts>
      </form>
      {/* <FootNote>
        Les contributions ne s&apos;écrasent pas : chacune est datée et signée. Un motif qui change entre deux
        comités est lui-même une information — c&apos;est ce qui permet de juger, à la relecture, si la décision
        avait été prise sur un contexte encore valable.
      </FootNote> */}
    </div>
  );
}

/** Le champ `echeance` d'un candidat vaut toujours la chaîne littérale "aucune"
 * côté backend (aucune échéance contractuelle exploitable dans le miroir) — ce
 * n'est pas une date, jamais la passer à `formatDate`. */
function echeanceLabel(echeance: string): string {
  if (!echeance || echeance === "aucune") return "aucune échéance contractuelle dans le miroir";
  return formatDate(echeance);
}

/** Comment lire le signal commercial retenu : son type, sa nature, et le fait
 * qu'il a été choisi sur le montant le plus élevé quand le client en portait
 * plusieurs — un critère de tri, pas un jugement d'urgence. */
function signalSummary(c: ArbitrageCandidate): string {
  const parts = [`${c.signal_type} (${c.signal_nature})`];
  if (c.signaux_commerciaux_nb > 1) {
    parts.push(`retenu comme le plus gros montant parmi ${formatNumber(c.signaux_commerciaux_nb)} signaux du client`);
  }
  if (c.signal_age_mois !== null && c.signal_cycle_mois) {
    const reste = c.signal_cycle_mois - c.signal_age_mois;
    parts.push(
      reste > 0
        ? `dernier achat il y a ${formatNumber(c.signal_age_mois)} mois, cycle supposé de ${formatNumber(c.signal_cycle_mois)} mois → fenêtre estimée dans ~${formatNumber(reste)} mois`
        : `dernier achat il y a ${formatNumber(c.signal_age_mois)} mois, cycle supposé de ${formatNumber(c.signal_cycle_mois)} mois déjà dépassé`
    );
  } else if (c.signal_age_mois !== null) {
    parts.push(`dernier achat il y a ${formatNumber(c.signal_age_mois)} mois`);
  }
  return parts.join(" · ");
}

function candidateDetail(c: ArbitrageCandidate, seuilM: number): DetailCard {
  const enjeuM = mFcfa(c.enjeu_xof);
  const p = c.profil_payeur;
  return {
    kicker: "Conflit détecté · file d'arbitrage",
    title: c.subject_label,
    tag: c.priorite.label,
    tagVariant: c.priorite.niveau >= 3 ? "r" : c.priorite.niveau === 2 ? "w" : "n",
    body: [
      `Ce dossier remonte parce que ${c.subject_ref} cumule deux signaux incompatibles : ${c.positions
        .map((p) => `${roleLabel(p.role)} — ${p.text}`)
        .join(" ; ")}.`,
      p.lecture,
      `Deux montants à ne pas confondre : ${formatMFcfa(c.impaye_xof)} M FCFA sont réellement dus (mesuré), tandis que l'enjeu de ${formatMFcfa(
        c.enjeu_xof
      )} M FCFA est le montant du signal commercial en jeu (${c.signal_nature}).`,
      `Le mandat revient à ${roleLabel(c.mandat_role)} : ${formatNumber(enjeuM)} M FCFA ${
        enjeuM >= seuilM ? "dépasse" : "reste sous"
      } le seuil de ${formatNumber(seuilM)} M FCFA.`,
      ...(c.signaux_portefeuille.length
        ? [`Signaux de portefeuille actifs : ${c.signaux_portefeuille.join(" · ")}.`]
        : []),
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
        `≈ ${formatMFcfa(c.cout_report_xof_semaine)} M FCFA / semaine (${(
          p.cout_report_ratio_semaine * 100
        ).toFixed(1)} % de l'enjeu, ratio du profil de payeur)`,
      ],
      ["Échéance", echeanceLabel(c.echeance)],
      ...(c.backlog_xof !== null ? [["Backlog", `${formatMFcfa(c.backlog_xof)} M FCFA`]] : []),
      ...(c.reste_a_encaisser_xof !== null
        ? [["Reste à encaisser", `${formatMFcfa(c.reste_a_encaisser_xof)} M FCFA`]]
        : []),
    ],
    // note: "Conflit obtenu par recoupement des sorties de moteurs (impayés, cross-sell, portefeuille) — aucune saisie manuelle. Ouvrir cette fiche n'écrit rien dans Odoo.",
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
        : d.review_date
          ? `Relecture due le ${formatDate(d.review_date)}, pas encore faite. Une décision sans revue n'est pas une décision, c'est une intention.`
          : "Pas encore relue, et sans date de relecture (décision antérieure à ce module).",
    ],
    kv: [
      ["Propriétaire", d.owner || d.created_by || "—"],
      ["Créée le", formatDate(d.created_at)],
      ["Relecture due le", formatDate(d.review_date)],
      ...(d.enjeu_xof ? [["Enjeu", `${formatMFcfa(d.enjeu_xof)} M FCFA`]] : []),
      ["Mandat", d.mandat_role ? roleLabel(d.mandat_role) : "—"],
      ["Revue", d.review_verdict ? VERDICT_LABELS[d.review_verdict] ?? d.review_verdict : "à faire"],
      ...(d.outcome ? [["Issue constatée", d.outcome]] : []),
    ],
    // note: "Chaque décision est relue à échéance : c'est cette relecture qui recalibre les recommandations suivantes.",
  };
}

/** Profils concernés par un dossier : celui qui a mandat + ceux dont la position
 * est citée. Une ligne sans aucun rôle rattaché (décision antérieure à ce module,
 * ex. un GO/NO-BID d'avant-vente) n'est dans le périmètre de personne — elle
 * n'apparaît qu'en « Tous les dossiers », plutôt que d'être présentée à chacun
 * comme si elle le concernait. */
function concernedProfiles(mandatRole: string, profilsImpliques: string[]): ProfileKey[] {
  return [mandatRole, ...profilsImpliques]
    .map((r) => roleToProfile(r))
    .filter((p): p is ProfileKey => p !== null);
}

function isRowRelevant(profile: ProfileKey, isAdmin: boolean, mandatRole: string, profilsImpliques: string[]): boolean {
  if (isAdmin) return true;
  return concernedProfiles(mandatRole, profilsImpliques).includes(profile);
}

export async function ArbitrageView({ profile }: { profile: ProfileKey }) {
  // `listDecisions` reste appelé sans que le registre soit affiché : le KPI
  // « Revues en retard » a besoin du compte réel de décisions et de revues faites
  // pour être lisible autrement qu'en valeur brute.
  const [file, decisions, me] = await Promise.all([
    getArbitrageFile(),
    listDecisions(),
    apiFetch<Me>("/v1/auth/me"),
  ]);

  if (!file) {
    return <Note>Ce module n&apos;est pas disponible pour votre profil.</Note>;
  }

  const isAdmin = isAdminRole(me.role);
  const seuilM = file.kpi.seuil_mandat_dg_m_fcfa;

  const relevantCandidate = (c: ArbitrageCandidate) => isRowRelevant(profile, isAdmin, c.mandat_role, c.profils_impliques);
  const mesCandidats = file.candidats.filter(relevantCandidate);
  const hasRelevantCandidate = mesCandidats.length > 0;
  const topCandidate = mesCandidats[0] ?? null;
  const monEnjeuM = mesCandidats.reduce((sum, c) => sum + mFcfa(c.enjeu_xof), 0);
  const monImpayeM = mesCandidats.reduce((sum, c) => sum + mFcfa(c.impaye_xof), 0);

  const dossier = topCandidate ? await getArbitrageDossier(topCandidate.subject_ref) : null;
  const recommended = dossier?.options.find((o) => o.recommandee);
  const hasMandate = dossier ? isAdmin || roleToProfile(dossier.mandat_role) === profile : false;

  const registre = decisions ?? [];
  const urgent = file.kpi.echeance_plus_proche_jours !== null && file.kpi.echeance_plus_proche_jours < 15;

  return (
    <>
      <div className="kpi-row">
        <StatTile
          span={4}
          label="Dossiers ouverts"
          value={formatNumber(file.kpi.dossiers_ouverts)}
          unit="dossiers"
          reading={
            isAdmin
              ? "conflits détectés + décisions en cours"
              : `dont ${formatNumber(mesCandidats.length)} dans votre périmètre`
          }
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
              `${formatNumber(mesCandidats.length)} de ces dossiers relèvent de votre périmètre (mandat ou position citée) — les KPI de ce bandeau restent, eux, calculés sur l'ensemble.`,
            ],
            kv: [
              ["Conflits détectés", formatNumber(file.candidats.length)],
              ["Dans votre périmètre", formatNumber(mesCandidats.length)],
              ["Décisions ouvertes", formatNumber(file.decisions_ouvertes.length)],
              ["Enjeu cumulé (tous profils)", `${formatNumber(file.kpi.enjeu_cumule_m_fcfa)} M FCFA`],
            ],
            // note: "Recoupement des sorties de moteurs, recalculé à chaque chargement — pas une liste tenue à la main.",
          }}
        />
        <StatTile
          span={4}
          label="Enjeu cumulé"
          value={formatNumber(file.kpi.enjeu_cumule_m_fcfa)}
          unit="M FCFA"
          reading={isAdmin ? "tous profils confondus" : `dont ${formatNumber(monEnjeuM)} M dans votre périmètre`}
          detail={{
            kicker: "Indicateur · enjeu",
            title: "Enjeu cumulé en arbitrage",
            tag: `${formatNumber(file.kpi.dossiers_ouverts)} dossiers`,
            tagVariant: "a",
            body: [
              `Les dossiers ouverts portent ensemble sur ${formatNumber(
                file.kpi.enjeu_cumule_m_fcfa
              )} M FCFA de signaux commerciaux. Attention : c'est le montant que la décision déplace côté commerce, PAS le montant dû.`,
              `L'exposition financière réellement échue sur votre périmètre est de ${formatNumber(
                monImpayeM
              )} M FCFA — les deux échelles sont distinctes et doivent être lues séparément.`,
              `Au-delà de ${formatNumber(seuilM)} M FCFA d'enjeu, le mandat bascule automatiquement à la Direction générale : c'est ce seuil qui explique pourquoi la plupart des dossiers sont mandat DG.`,
            ],
            kv: [
              ["Enjeu cumulé (tous profils)", `${formatNumber(file.kpi.enjeu_cumule_m_fcfa)} M FCFA`],
              ["Enjeu de votre périmètre", `${formatNumber(monEnjeuM)} M FCFA`],
              ["Impayé de votre périmètre", `${formatNumber(monImpayeM)} M FCFA`],
              ["Seuil de mandat DG", `${formatNumber(seuilM)} M FCFA`],
            ],
            // note: "Montants issus des factures et commandes du miroir Odoo, convertis en M FCFA.",
          }}
        />
        <StatTile
          span={4}
          label="Prochaine échéance"
          value={file.kpi.echeance_plus_proche_jours !== null ? formatNumber(file.kpi.echeance_plus_proche_jours) : "—"}
          unit="jours"
          reading={
            file.kpi.echeance_plus_proche_jours === null
              ? "aucune décision ouverte n'est datée"
              : urgent
                ? "sous le seuil de 15 jours"
                : "au-delà du seuil de 15 jours"
          }
          readingVariant={file.kpi.echeance_plus_proche_jours === null ? undefined : urgent ? "neg" : "wat"}
          detail={{
            kicker: "Indicateur · délai",
            title: "Prochaine échéance de décision",
            tag: urgent ? "fenêtre courte" : "fenêtre tenable",
            tagVariant: urgent ? "r" : "w",
            body: [
              file.kpi.echeance_plus_proche_jours !== null
                ? `La décision ouverte la plus contrainte arrive à échéance de relecture dans ${formatNumber(
                    file.kpi.echeance_plus_proche_jours
                  )} jours.`
                : "Aucune décision ouverte ne porte de date. Toute décision journalisée depuis cet écran reçoit désormais une échéance de relecture à 30 jours ; les décisions antérieures à ce module n'en ont pas.",
              "Cet indicateur porte sur les décisions déjà prises et à relire, pas sur les conflits détectés : ces derniers n'ont aucune échéance contractuelle exploitable dans le miroir Odoo.",
            ],
            kv: [
              [
                "Jours restants",
                file.kpi.echeance_plus_proche_jours !== null
                  ? formatNumber(file.kpi.echeance_plus_proche_jours)
                  : "—",
              ],
              ["Seuil de vigilance", "15 jours"],
              ["Délai de relecture par défaut", "30 jours"],
            ],
            // note: "Échéance lue sur les décisions ouvertes du registre (date butoir, sinon date de relecture).",
          }}
        />
        <StatTile
          span={4}
          label="Coût du report"
          value={`≈ ${formatNumber(file.kpi.cout_report_m_fcfa_semaine)}`}
          unit="M FCFA / semaine"
          reading="estimation calibrée par client, pas une mesure"
          readingVariant="wat"
          detail={{
            kicker: "Indicateur · coût de l'attente",
            title: "Coût du report",
            tag: "estimation",
            tagVariant: "w",
            body: [
              `Ne pas trancher coûterait environ ${formatNumber(
                file.kpi.cout_report_m_fcfa_semaine
              )} M FCFA par semaine, cumulés sur l'ensemble des dossiers ouverts.`,
              "Cela reste une convention de calcul, pas une mesure : un pourcentage de l'enjeu par semaine. Elle sert à comparer deux reports entre eux et à ordonner la file — jamais à provisionner un montant ni à alimenter un plan de trésorerie.",
              "Le taux n'est plus le même pour tous : il va de 0,5 % chez un client dont le rythme de paiement s'améliore à 5 % chez un client qui a cessé de payer. Un taux uniforme revenait à affirmer qu'attendre coûte autant dans les deux cas, alors que c'est précisément ce que la file doit distinguer.",
            ],
            kv: [
              ["Coût hebdomadaire estimé", `≈ ${formatNumber(file.kpi.cout_report_m_fcfa_semaine)} M FCFA`],
              ["Méthode", "% de l'enjeu par semaine, taux fonction du comportement de paiement du client"],
              ["Plage de taux", "0,5 % (rythme en amélioration) à 5 % (paiements arrêtés)"],
              ["Dossiers concernés", formatNumber(file.kpi.dossiers_ouverts)],
              ["Nature", "estimation, pas une mesure"],
            ],
            // note: "Le cockpit préfère afficher une estimation signalée comme telle plutôt qu'un chiffre présenté comme exact. Le taux retenu pour chaque dossier est visible dans sa fiche.",
          }}
        />
        <StatTile
          span={4}
          label="Revues en retard"
          value={formatNumber(file.kpi.revues_en_retard)}
          unit="décisions"
          reading={
            file.kpi.revues_en_retard > 0
              ? "échéance de relecture dépassée sans verdict"
              : `${formatNumber(registre.filter((d) => Boolean(d.review_verdict)).length)} revue(s) faite(s) sur ${formatNumber(registre.length)} décision(s)`
          }
          readingVariant={file.kpi.revues_en_retard > 0 ? "wat" : undefined}
          detail={{
            kicker: "Indicateur · registre",
            title: "Revues en retard",
            tag: file.kpi.revues_en_retard > 0 ? "à instruire" : "aucune en retard",
            tagVariant: file.kpi.revues_en_retard > 0 ? "w" : "n",
            body: [
              file.kpi.revues_en_retard > 0
                ? `${formatNumber(
                    file.kpi.revues_en_retard
                  )} décision(s) ont dépassé leur échéance de relecture sans verdict enregistré. Tant qu'elles ne sont pas relues, elles ne recalibrent rien.`
                : `Aucune décision n'a dépassé son échéance de relecture. À ne pas lire comme « tout a été relu » : ${formatNumber(
                    registre.filter((d) => Boolean(d.review_verdict)).length
                  )} revue(s) ont été réellement faites sur ${formatNumber(registre.length)} décision(s) au registre.`,
              "La revue est le seul mécanisme qui rend l'outil vérifiable après coup : elle compare l'issue constatée à ce qui avait été recommandé. Son verdict est choisi par celui qui a le mandat, jamais imposé par l'outil.",
              "Cet écran n'affiche plus le registre ni le formulaire de revue : cet indicateur signale l'encours, il ne permet pas de le traiter ici.",
            ],
            kv: [
              ["Revues en retard", formatNumber(file.kpi.revues_en_retard)],
              ["Décisions au registre", formatNumber(registre.length)],
              ["Revues faites", formatNumber(registre.filter((d) => Boolean(d.review_verdict)).length)],
              ["Sans date de relecture", formatNumber(registre.filter((d) => !d.review_date).length)],
            ],
            // note: "Le registre conserve tout, y compris les décisions antérieures à ce module (qui n'ont pas de date de relecture).",
          }}
        />
      </div>

      {dossier && recommended ? (
        <div className="dec" style={{ marginTop: 18 }}>
          <div className="dec-h">
            <h3>{dossier.subject_label}</h3>
            <p>
              Mandat {roleLabel(dossier.mandat_role)} · profils impliqués{" "}
              {dossier.profils_impliques.map(roleLabel).join(", ") || "—"}
              {dossier.commercial_compte ? ` · commercial du compte ${dossier.commercial_compte}` : ""}.
              <br />
              Seuil de mandat DG : {formatNumber(seuilM)} M FCFA — l&apos;enjeu commercial (
              {formatNumber(mFcfa(dossier.enjeu_xof))} M){" "}
              {mFcfa(dossier.enjeu_xof) >= seuilM ? "le dépasse" : "reste en dessous"}, d&apos;où le mandat{" "}
              {roleLabel(dossier.mandat_role)}. Priorité de traitement :{" "}
              {dossier.priorite.label} ({dossier.priorite.raison}). Ne rien décider coûte ≈{" "}
              {formatMFcfa(dossier.cout_report_xof_semaine)} M FCFA par semaine — estimation à{" "}
              {(dossier.profil_payeur.cout_report_ratio_semaine * 100).toFixed(1)} % de l&apos;enjeu, taux
              retenu au vu du comportement de paiement du client et non appliqué uniformément.
            </p>
          </div>
          <div className="dec-b">
            <MiniLabel>Ce que ce client paie réellement — la lecture qui décide</MiniLabel>
            <HintLine>Cliquez le bandeau pour le détail des délais mesurés</HintLine>
            <PayeurBandeau profil={dossier.profil_payeur} subjectRef={dossier.subject_ref} />

            <MiniLabel>Les deux montants en présence — à ne pas confondre</MiniLabel>
            <div className="rows" style={{ marginBottom: 20 }}>
              <div className="row-m">
                <div>
                  <div className="row-n">Impayé constaté</div>
                  <div className="row-s">
                    {formatNumber(dossier.impaye_nb_factures)} facture(s) échue(s) · retard le plus ancien{" "}
                    {formatNumber(dossier.retard_max_jours)} jours
                  </div>
                </div>
                <div className="num">{formatMFcfa(dossier.impaye_xof)} M FCFA</div>
                <Tag variant={NATURE_VARIANT.mesuré}>mesuré</Tag>
              </div>
              <div className="row-m">
                <div>
                  <div className="row-n">Enjeu commercial ({dossier.signal_type.toLowerCase()})</div>
                  <div className="row-s">{signalSummary(dossier)}</div>
                </div>
                <div className="num">{formatMFcfa(dossier.enjeu_xof)} M FCFA</div>
                <Tag variant={NATURE_VARIANT[dossier.signal_nature] ?? "w"}>{dossier.signal_nature}</Tag>
              </div>
            </div>

            <MiniLabel>Positions en présence</MiniLabel>
            <div className="rows" style={{ marginBottom: 20 }}>
              {dossier.positions.map((p, i) => (
                <div className="row" key={i}>
                  <div className="cons" style={{ border: 0, padding: 0 }}>
                    <i>{roleLabel(p.role)}</i>
                    <span>{p.text}</span>
                    {p.nature && (
                      <span className={`tag tag--${NATURE_VARIANT[p.nature] ?? "n"}`} style={{ fontSize: 9 }}>
                        {p.nature}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <MiniLabel>Options et conséquences par profil</MiniLabel>
            <HintLine>
              Cliquez une option pour ses conséquences détaillées — l&apos;option recommandée découle du
              comportement de paiement mesuré ci-dessus, pas d&apos;une règle unique
            </HintLine>
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
                    // note:
                    //   opt.code === "C"
                    //     ? `Dossier ${dossier.subject_ref}. Les montants, le nombre d'échéances et l'horizon sont calculés à partir du délai de règlement réellement observé chez ce client — l'IA n'en modifie aucun, elle ne rédige que la formulation négociable.`
                    //     : `Dossier ${dossier.subject_ref}. Options A et B : structures de compromis déterministes, seuls les montants varient d'un dossier à l'autre. L'option C, quand elle existe, est calculée sur le comportement de paiement du client.`,
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
                  {opt.argumentaire && (
                    <div
                      className="opt-d"
                      style={{ fontStyle: "italic", color: "var(--t3)", marginTop: 6 }}
                    >
                      À dire au client : « {opt.argumentaire} »
                      {opt.redige_par === "repli" && " (repli — modèle indisponible)"}
                    </div>
                  )}
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

            <ContexteTerrain dossier={dossier} profile={profile} />

            {/* <FootNote>
              Le cockpit classe les options, il ne tranche pas : vous retenez celle que vous voulez, y compris
              contre la recommandation — l&apos;écart entre les deux est enregistré et alimente le taux de suivi.
              La décision est journalisée au nom du profil qui la prend, avec une échéance de relecture à 30
              jours. Reporter ou escalader est aussi une décision : c&apos;est journalisé comme tel, avec son
              motif, plutôt que de laisser le dossier sans trace.
            </FootNote> */}

            {hasMandate ? (
              <form action={createDecisionAction}>
                <input type="hidden" name="profile" value={profile} />
                <input type="hidden" name="title" value={`Arbitrage ${dossier.subject_ref}`} />
                <input type="hidden" name="context" value={dossier.subject_label} />
                <input type="hidden" name="subject_ref" value={dossier.subject_ref} />
                <input type="hidden" name="subject_label" value={dossier.subject_label} />
                <input type="hidden" name="enjeu_xof" value={dossier.enjeu_xof} />
                <input type="hidden" name="cout_report_xof_semaine" value={dossier.cout_report_xof_semaine} />
                <input type="hidden" name="mandat_role" value={dossier.mandat_role} />
                <input type="hidden" name="profils_impliques" value={dossier.profils_impliques.join(",")} />
                {/* Ce que l'outil recommandait, envoyé quel que soit le choix du
                    mandataire : c'est la comparaison des deux qui rend le score
                    de fiabilité interprétable. */}
                <input
                  type="hidden"
                  name="option_recommandee"
                  value={`${recommended.code} · ${recommended.titre}`}
                />
                <input type="hidden" name="profil_payeur_classe" value={dossier.profil_payeur.classe} />
                <div className="dform">
                  <div className="dform-r">
                    <label htmlFor="opt-ret">Option retenue</label>
                    <select
                      id="opt-ret"
                      className="sel"
                      name="option_retenue"
                      defaultValue={`${recommended.code} · ${recommended.titre}`}
                    >
                      {dossier.options.map((opt) => (
                        <option key={opt.code} value={`${opt.code} · ${opt.titre}`}>
                          {opt.code} — {opt.titre}
                          {opt.recommandee ? " (recommandée)" : ""}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="dform-r">
                    <label htmlFor="dec-statut">Issue</label>
                    <select id="dec-statut" className="sel" name="status" defaultValue="tranchee">
                      <option value="tranchee">Trancher — l&apos;option retenue engage l&apos;entreprise</option>
                      <option value="reportee">Reporter — ne pas trancher aujourd&apos;hui (motif requis)</option>
                      <option value="escaladee">
                        Escalader — remonter au comité ou à la DG (motif requis)
                      </option>
                    </select>
                  </div>
                  <div className="dform-r">
                    <label htmlFor="dec-motif">Motif</label>
                    <textarea
                      id="dec-motif"
                      className="txa"
                      name="motif_decision"
                      placeholder="Ce qui fonde ce choix — obligatoire pour un report ou une escalade, c'est ce que la revue à 30 jours relira."
                    />
                  </div>
                </div>
                <Acts>
                  <Btn primary type="submit">
                    Journaliser la décision
                  </Btn>
                </Acts>
              </form>
            ) : (
              <Note>
                Cette décision relève du mandat de {roleLabel(dossier.mandat_role)} — dossier visible pour
                information, non actionnable depuis ce profil. Le serveur refuse toute journalisation et toute
                clôture de revue hors mandat, quel que soit l&apos;écran d&apos;où elles sont tentées. Vous
                pouvez en revanche apporter le contexte terrain ci-dessus : cela ne demande aucun mandat.
              </Note>
            )}
          </div>
        </div>
      ) : (
        !isAdmin && (
          <Note style={{ marginTop: 18 }}>
            Aucun dossier ne relève de votre périmètre actuellement.{" "}
            {file.candidats.length > 0
              ? `${formatNumber(file.candidats.length)} dossier(s) sont ouverts mais concernent d'autres profils — basculez sur « Tous les dossiers » dans la file ci-dessous pour les consulter.`
              : "Aucun conflit n'est détecté pour le moment, pour aucun profil."}{" "}
            À noter : ce module ne détecte à ce jour qu&apos;un seul type de tension — impayé client contre signal
            commercial actif. Les conflits propres à la livraison (plan de charge, fournisseurs, staffing) ne sont pas
            encore modélisés, leur absence ici ne signifie donc pas qu&apos;il n&apos;y en a aucun.
          </Note>
        )
      )}

      <div className="bento">
        <Tile span={12} title="File d'arbitrage" kick="conflits détectés · calcul réel">
          <ArbitrageScopeToggle hasRelevant={hasRelevantCandidate} perimeterLabel={META[profile].name}>
            <HintLine>Cliquez un dossier pour son détail chiffré</HintLine>
            <div style={{ overflowX: "auto" }}>
              <table className="tb">
                <thead>
                  <tr>
                    <th>Priorité</th>
                    <th>Dossier</th>
                    <th>Comportement de paiement</th>
                    <th className="r">Impayé</th>
                    <th className="r">Enjeu</th>
                    <th>Mandat</th>
                    <th>État</th>
                  </tr>
                </thead>
                <tbody>
                  {file.candidats.map((c) => (
                    <Clickable
                      as="tr"
                      key={c.subject_ref}
                      detail={candidateDetail(c, seuilM)}
                      dataAttrs={{ "data-relevant": String(relevantCandidate(c)) }}
                    >
                      <td>
                        <Tag
                          variant={
                            c.priorite.niveau >= 3 ? "r" : c.priorite.niveau === 2 ? "w" : c.priorite.niveau === 1 ? "n" : "s"
                          }
                        >
                          {c.priorite.label}
                        </Tag>
                      </td>
                      <td style={{ fontWeight: 500 }}>{c.subject_label}</td>
                      <td style={{ fontSize: 12 }}>
                        <span style={{ color: "var(--t1)" }}>{c.profil_payeur.classe_label}</span>
                        <div className="mono" style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>
                          {c.profil_payeur.delai_recent_jours !== null
                            ? c.profil_payeur.delai_ancien_jours !== null
                              ? `${formatNumber(c.profil_payeur.delai_ancien_jours)} j → ${formatNumber(
                                  c.profil_payeur.delai_recent_jours
                                )} j`
                              : `${formatNumber(c.profil_payeur.delai_recent_jours)} j`
                            : c.profil_payeur.jours_depuis_dernier_paiement !== null
                              ? `aucun paiement depuis ${formatNumber(
                                  c.profil_payeur.jours_depuis_dernier_paiement
                                )} j`
                              : "non mesurable"}
                        </div>
                      </td>
                      <td className="r mono">{formatMFcfa(c.impaye_xof)} M</td>
                      <td className="r mono">{formatMFcfa(c.enjeu_xof)} M</td>
                      <td style={{ fontSize: 12.5, color: "var(--t2)" }}>{roleLabel(c.mandat_role)}</td>
                      <td>
                        <Tag variant="r">non tranché</Tag>
                      </td>
                    </Clickable>
                  ))}
                  {file.decisions_ouvertes.map((d) => (
                    <Clickable
                      as="tr"
                      key={`d-${d.id}`}
                      detail={decisionDetail(d)}
                      dataAttrs={{
                        "data-relevant": String(
                          isRowRelevant(profile, isAdmin, d.mandat_role, d.profils_impliques)
                        ),
                      }}
                    >
                      <td>
                        <span className="ro">décision ouverte</span>
                      </td>
                      <td style={{ fontWeight: 500 }}>{d.subject_label || d.title}</td>
                      <td style={{ fontSize: 12, color: "var(--t2)" }}>
                        {d.profil_payeur_classe
                          ? PAYEUR_CLASSE_LABELS[d.profil_payeur_classe] ?? d.profil_payeur_classe
                          : "—"}
                        <div className="mono" style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>
                          {d.profils_impliques.map(roleLabel).join(" · ") || "—"}
                        </div>
                      </td>
                      <td className="r mono">—</td>
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
                      <td colSpan={7} style={{ color: "var(--t2)" }}>
                        Aucun conflit détecté actuellement — aucun client en retard de paiement ne cumule un signal
                        commercial actif.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {/* <FootNote>
              Un dossier est détecté quand un client cumule des factures échues ET un signal commercial actif
              (renouvellement, cross-sell) — recoupement automatique, pas une liste saisie à la main. Le
              classement croise l&apos;enjeu ET le comportement de paiement du client : trier par montant seul
              plaçait en tête les plus grosses créances, y compris chez des clients qui règlent normalement, en
              reléguant des dossiers plus petits où quelque chose venait réellement de changer. Aucun dossier
              n&apos;est masqué, seul son rang change — et la priorité ne touche pas au mandat, qui reste fondé
              sur le montant et bascule à la Direction générale au-delà de {formatNumber(seuilM)} M FCFA.
            </FootNote> */}
          </ArbitrageScopeToggle>
        </Tile>
      </div>
    </>
  );
}
