import { apiFetch } from "./client";

/** Nature épistémique d'un signal (cf. `aggregation._SIGNAL_NATURE`) : lu dans le
 * miroir, absence constatée, ou déduit d'un cycle supposé. */
export type SignalNature = "mesuré" | "observé" | "inféré";

export interface ArbitragePosition {
  role: string;
  text: string;
  nature?: SignalNature;
}

/** Classe de comportement de paiement du client (cf. `payeur.CLASSE_LABELS`).
 *
 * `non_calcule` n'existe pas côté backend : c'est la valeur posée ici quand la
 * réponse ne porte pas de profil, cas d'un backend plus ancien que ce front (les
 * deux sont déployés séparément derrière nginx). Une classe explicite vaut mieux
 * qu'un `undefined` qui casse le rendu de tout l'écran, et mieux qu'un repli sur
 * « historique insuffisant » qui ferait passer une absence de calcul pour un
 * constat sur le client. */
export type PayeurClasse =
  | "intragroupe"
  | "amelioration"
  | "stable_rapide"
  | "stable_lent"
  | "stable"
  | "vigilance"
  | "degradation"
  | "paiements_stoppes"
  | "defaillance_probable"
  | "historique_insuffisant"
  | "non_calcule";

/** Comportement de paiement RÉELLEMENT observé du client débiteur — lu sur les
 * dates de paiement Odoo, jamais inféré (cf. `modules/uc_arbitrage/payeur.py`).
 *
 * `delai_ancien_jours` → `delai_recent_jours` est la lecture qui décide : c'est
 * la tendance, et non le montant échu ni le retard maximum, qui distingue un
 * client qui a cessé de payer d'un client dont le retard est le rythme habituel. */
export interface PayeurProfile {
  classe: PayeurClasse;
  classe_label: string;
  nature: SignalNature;
  delai_habituel_jours: number | null;
  delai_accorde_jours: number | null;
  nb_factures_payees: number;
  taux_recouvrement_pct: number | null;
  retard_max_jours: number;
  delai_recent_jours: number | null;
  delai_ancien_jours: number | null;
  nb_paiements_recents: number;
  nb_paiements_anciens: number;
  /** Délai récent / délai ancien. `null` quand une des deux fenêtres est trop
   * pauvre pour comparer — jamais 1.0 par défaut : l'inconnu n'est pas le stable. */
  tendance_ratio: number | null;
  dernier_paiement: string | null;
  jours_depuis_dernier_paiement: number | null;
  fenetre_mois: number | null;
  recommandation: "conditionner" | "poursuivre" | "echeancier";
  cout_report_ratio_semaine: number;
  lecture: string;
}

/** Plan d'apurement calculé sur le rythme de paiement mesuré du client. */
export interface ArbitrageEcheancier {
  nb_echeances: number;
  horizon_jours: number;
  pas_jours: number;
  tranche_xof: number;
  montant_total_xof: number;
  premiere_echeance_jours: number;
  delai_reference_jours: number;
  declencheur: string;
  methode: string;
}

/** Priorité de traitement — croise l'enjeu ET la fenêtre d'action réelle, là où
 * le tri par enjeu seul plaçait en tête les plus gros montants sans regarder
 * s'il y avait quelque chose à y faire. Ne touche pas au mandat. */
export interface ArbitragePriorite {
  niveau: 0 | 1 | 2 | 3;
  label: string;
  score: number;
  raison: string;
}

export interface ArbitrageCandidate {
  subject_ref: string;
  subject_label: string;
  profils_impliques: string[];
  /** Montant du signal COMMERCIAL retenu — jamais le montant dû (cf. `impaye_xof`). */
  enjeu_xof: number;
  echeance: string;
  cout_report_xof_semaine: number;
  mandat_role: string;
  positions: ArbitragePosition[];
  backlog_xof: number | null;
  reste_a_encaisser_xof: number | null;
  signaux_portefeuille: string[];
  /** Exposition financière réelle : montant échu, nombre de factures, retard max. */
  impaye_xof: number;
  impaye_nb_factures: number;
  retard_max_jours: number;
  signal_type: string;
  signal_nature: SignalNature;
  /** Nombre de signaux commerciaux du client — celui retenu est le plus gros montant. */
  signaux_commerciaux_nb: number;
  signal_age_mois: number | null;
  signal_cycle_mois: number | null;
  commercial_compte: string | null;
  profil_payeur: PayeurProfile;
  /** `null` quand un échéancier n'aurait pas de sens (client qui ne paie plus,
   * historique insuffisant) — l'option C est alors absente du dossier. */
  echeancier: ArbitrageEcheancier | null;
  priorite: ArbitragePriorite;
}

export interface Decision {
  id: number;
  title: string;
  context: string;
  decision_type: string;
  status: string;
  owner: string;
  due_date: string | null;
  outcome: string;
  created_by: string;
  created_at: string | null;
  decided_at: string | null;
  subject_ref: string;
  subject_label: string;
  enjeu_xof: number;
  cout_report_xof_semaine: number;
  mandat_role: string;
  profils_impliques: string[];
  option_retenue: string;
  review_date: string | null;
  review_verdict: string;
  review_comment: string;
  /** Ce que l'outil recommandait au moment de trancher. Sans elle, on ne peut pas
   * dire si le mandataire a suivi la recommandation ou l'a écartée — et le taux
   * de confirmation n'était donc pas interprétable. */
  option_recommandee: string;
  motif_decision: string;
  profil_payeur_classe: string;
  /** `null` sur les décisions antérieures à ce suivi — surtout pas `false`, qui
   * se lirait comme « la recommandation a été écartée ». */
  reco_suivie: boolean | null;
}

/** État du filtre d'entrée en arbitrage appliqué à la liste (cf.
 * `modules/uc_arbitrage/conditions.py`).
 *
 * `candidats` est restreint aux conditions cochées par le profil ; les KPI, eux,
 * restent ceux de la file entière — un réglage d'affichage ne doit pas faire
 * baisser l'enjeu cumulé. `nb_ecartes` est donc l'écart à afficher, jamais à
 * taire : une file rétrécie sans explication se lit comme une file vide. */
export interface ArbitrageFiltre {
  profil: string;
  conditions_actives: string[];
  nb_total: number;
  nb_retenus: number;
  nb_ecartes: number;
}

export interface ArbitrageFile {
  kpi: {
    dossiers_ouverts: number;
    enjeu_cumule_m_fcfa: number;
    echeance_plus_proche_jours: number | null;
    cout_report_m_fcfa_semaine: number;
    revues_en_retard: number;
    /** Enjeu au-delà duquel le mandat bascule à la DG (cf. aggregation.py). */
    seuil_mandat_dg_m_fcfa: number;
  };
  candidats: ArbitrageCandidate[];
  decisions_ouvertes: Decision[];
  filtre: ArbitrageFiltre;
}

/** Profil posé quand la réponse serveur n'en porte pas — cf. `PayeurClasse`.
 * Aucun chiffre n'est inventé : tout est à `null`, et la lecture dit pourquoi. */
const PAYEUR_NON_CALCULE: PayeurProfile = {
  classe: "non_calcule",
  classe_label: "profil non calculé",
  nature: "observé",
  delai_habituel_jours: null,
  delai_accorde_jours: null,
  nb_factures_payees: 0,
  taux_recouvrement_pct: null,
  retard_max_jours: 0,
  delai_recent_jours: null,
  delai_ancien_jours: null,
  nb_paiements_recents: 0,
  nb_paiements_anciens: 0,
  tendance_ratio: null,
  dernier_paiement: null,
  jours_depuis_dernier_paiement: null,
  fenetre_mois: null,
  recommandation: "conditionner",
  cout_report_ratio_semaine: 0,
  lecture:
    "Le serveur n'a pas renvoyé de comportement de paiement pour ce client — ce dossier est donc " +
    "instruit sur son seul impayé. À ne pas lire comme « ce client n'a pas d'historique » : c'est le " +
    "calcul qui est absent, pas les paiements.",
};

const PRIORITE_NON_CALCULEE: ArbitragePriorite = {
  niveau: 1,
  label: "priorité non calculée",
  score: 0,
  raison: "le serveur n'a pas renvoyé de priorité pour ce dossier",
};

/** Complète un candidat des champs que ce front attend et qu'un backend plus
 * ancien ne renvoie pas. Sans ce filet, l'écran entier tombe en erreur de rendu
 * pendant la fenêtre où les deux services ne sont pas à la même version — un
 * cockpit de direction doit dégrader, pas disparaître. */
function normalizeCandidate<T extends ArbitrageCandidate>(c: T): T {
  return {
    ...c,
    profil_payeur: c.profil_payeur ?? PAYEUR_NON_CALCULE,
    priorite: c.priorite ?? PRIORITE_NON_CALCULEE,
    echeancier: c.echeancier ?? null,
  };
}

function normalizeDecision(d: Decision): Decision {
  return {
    ...d,
    option_recommandee: d.option_recommandee ?? "",
    motif_decision: d.motif_decision ?? "",
    profil_payeur_classe: d.profil_payeur_classe ?? "",
    reco_suivie: d.reco_suivie ?? null,
  };
}

export async function getArbitrageFile(): Promise<ArbitrageFile | null> {
  const file = await apiFetch<ArbitrageFile | null>("/v1/arbitrage/file", { allowForbidden: true });
  if (!file) return file;
  const candidats = (file.candidats ?? []).map(normalizeCandidate);
  return {
    ...file,
    candidats,
    decisions_ouvertes: (file.decisions_ouvertes ?? []).map(normalizeDecision),
    // Backend antérieur aux conditions d'entrée : la liste reçue EST la file
    // entière. On le dit ainsi plutôt que d'afficher « 0 sur 0 », qui laisserait
    // croire à un filtre actif ayant tout écarté.
    filtre: file.filtre ?? {
      profil: "",
      conditions_actives: [],
      nb_total: candidats.length,
      nb_retenus: candidats.length,
      nb_ecartes: 0,
    },
  };
}

/** Une condition d'entrée en arbitrage du catalogue. Le catalogue est figé dans
 * le code du backend (`uc_arbitrage/conditions.py`) : l'écran ne peut qu'activer
 * ou désactiver, jamais rédiger — une condition décide de ce qui est soumis à
 * décision, elle doit rester relisible et testée. */
export interface ArbitrageCondition {
  code: string;
  libelle: string;
  explication: string;
  /** Seuil affichable (« 730 jours »), vide quand la condition n'en a pas. */
  seuil: string;
  champs: string[];
  recommandee_pour: string[];
}

/** Effet mesuré sur la file réelle. `refs_par_condition` porte, pour chaque
 * condition prise seule, les dossiers qu'elle retient : l'écran en déduit
 * l'effet de n'importe quelle combinaison par intersection, sans appel réseau.
 * C'est ce qui rend le compteur vivant pendant que l'utilisateur coche — les
 * conditions se combinant en ET, deux cases raisonnables peuvent vider la file. */
export interface ArbitrageConditionsMesure {
  nb_total: number;
  nb_retenus: number;
  nb_ecartes: number;
  refs_par_condition: Record<string, string[]>;
  refs_total: string[];
}

export interface ArbitrageConditionsReglage {
  catalogue: ArbitrageCondition[];
  /** Rôle du demandeur. `admin` n'est pas un profil métier : il règle ceux des
   * autres et sa propre file n'est jamais filtrée. */
  profil: string;
  profils_parametrables: string[];
  conditions_actives: string[];
  par_profil: Record<string, string[]>;
  mesure: ArbitrageConditionsMesure;
}

export async function getArbitrageConditions(): Promise<ArbitrageConditionsReglage | null> {
  const reglage = await apiFetch<ArbitrageConditionsReglage | null>("/v1/arbitrage/conditions", {
    allowForbidden: true,
  });
  if (!reglage) return reglage;
  return {
    ...reglage,
    catalogue: reglage.catalogue ?? [],
    profils_parametrables: reglage.profils_parametrables ?? [],
    conditions_actives: reglage.conditions_actives ?? [],
    par_profil: reglage.par_profil ?? {},
    mesure: reglage.mesure ?? {
      nb_total: 0,
      nb_retenus: 0,
      nb_ecartes: 0,
      refs_par_condition: {},
      refs_total: [],
    },
  };
}

export interface ArbitrageOptionConsequence {
  role: string;
  text: string;
  variant: "s" | "r" | "w" | "n";
}

export interface ArbitrageOption {
  code: string;
  titre: string;
  description: string;
  recommandee: boolean;
  consequences: ArbitrageOptionConsequence[];
  /** Option C uniquement : d'où sortent les chiffres de l'échéancier. */
  methode?: string;
  /** Option C uniquement : formulation négociable rédigée par le LLM à partir du
   * plan déjà calculé. `redige_par` dit lequel des deux est affiché, plutôt que
   * de laisser croire à une rédaction du modèle quand l'appel a échoué. */
  argumentaire?: string;
  redige_par?: "ia" | "repli";
}

/** Contribution du commercial du compte sur un dossier — la réponse aux questions
 * que le dossier lui posait sans offrir d'endroit pour y répondre. */
export interface ArbitrageContexte {
  id: number;
  subject_ref: string;
  motif_retard: string;
  dossier_toujours_actif: string;
  created_by: string;
  created_role: string;
  created_at: string | null;
}

export interface ArbitrageMissingInfo {
  text: string;
  owner: string;
  delay: string;
}

export interface ArbitrageDossier extends ArbitrageCandidate {
  options: ArbitrageOption[];
  contre_arguments: string[];
  manque: ArbitrageMissingInfo[];
  decisions_liees: Decision[];
  contextes_terrain: ArbitrageContexte[];
}

export async function getArbitrageDossier(subjectRef: string): Promise<ArbitrageDossier | null> {
  const dossier = await apiFetch<ArbitrageDossier | null>(
    `/v1/arbitrage/dossier/${encodeURIComponent(subjectRef)}`,
    { allowForbidden: true }
  );
  if (!dossier) return dossier;
  return {
    ...normalizeCandidate(dossier),
    options: dossier.options ?? [],
    contre_arguments: dossier.contre_arguments ?? [],
    manque: dossier.manque ?? [],
    decisions_liees: (dossier.decisions_liees ?? []).map(normalizeDecision),
    contextes_terrain: dossier.contextes_terrain ?? [],
  };
}

export async function listDecisions(): Promise<Decision[] | null> {
  const decisions = await apiFetch<Decision[] | null>("/v1/arbitrage/decisions", {
    allowForbidden: true,
  });
  return decisions ? decisions.map(normalizeDecision) : decisions;
}

export interface ReliabilityStats {
  nb_decisions_revues: number;
  nb_confirmees: number;
  taux_confirmation_pct: number | null;
  historique_suffisant: boolean;
  note: string;
  /** Taux de SUIVI — les mandataires retiennent-ils l'option recommandée ?
   * Disponible sans attendre les revues, contrairement au taux de confirmation. */
  nb_decisions_tracees: number;
  nb_reco_suivies: number;
  taux_suivi_pct: number | null;
  /** Confirmation restreinte aux décisions où la recommandation a été suivie —
   * les seules qui disent quelque chose de l'outil plutôt que du mandataire. */
  nb_suivies_revues: number;
  taux_confirmation_reco_suivie_pct: number | null;
  note_suivi: string;
}

export async function getReliability(): Promise<ReliabilityStats | null> {
  const stats = await apiFetch<ReliabilityStats | null>("/v1/arbitrage/reliability", {
    allowForbidden: true,
  });
  if (!stats) return stats;
  // Le taux de suivi n'existe que depuis l'ajout d'`option_recommandee`. Absent,
  // il reste à `null` — jamais à 0, qui se lirait « aucune recommandation suivie »
  // alors que la mesure n'a simplement pas été faite.
  return {
    ...stats,
    nb_decisions_tracees: stats.nb_decisions_tracees ?? 0,
    nb_reco_suivies: stats.nb_reco_suivies ?? 0,
    taux_suivi_pct: stats.taux_suivi_pct ?? null,
    nb_suivies_revues: stats.nb_suivies_revues ?? 0,
    taux_confirmation_reco_suivie_pct: stats.taux_confirmation_reco_suivie_pct ?? null,
    note_suivi: stats.note_suivi ?? "Taux de suivi non renvoyé par le serveur.",
  };
}
