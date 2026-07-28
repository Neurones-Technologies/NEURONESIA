import { apiFetch } from "./client";

export interface ArbitragePosition {
  role: string;
  text: string;
}

export interface ArbitrageCandidate {
  subject_ref: string;
  subject_label: string;
  profils_impliques: string[];
  enjeu_xof: number;
  echeance: string;
  cout_report_xof_semaine: number;
  mandat_role: string;
  positions: ArbitragePosition[];
  backlog_xof: number | null;
  reste_a_encaisser_xof: number | null;
  signaux_portefeuille: string[];
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
}

export interface ArbitrageFile {
  kpi: {
    dossiers_ouverts: number;
    enjeu_cumule_m_fcfa: number;
    echeance_plus_proche_jours: number | null;
    cout_report_m_fcfa_semaine: number;
    revues_en_retard: number;
  };
  candidats: ArbitrageCandidate[];
  decisions_ouvertes: Decision[];
}

export async function getArbitrageFile(): Promise<ArbitrageFile | null> {
  return apiFetch<ArbitrageFile | null>("/v1/arbitrage/file", { allowForbidden: true });
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
}

export async function getArbitrageDossier(subjectRef: string): Promise<ArbitrageDossier | null> {
  return apiFetch<ArbitrageDossier | null>(
    `/v1/arbitrage/dossier/${encodeURIComponent(subjectRef)}`,
    { allowForbidden: true }
  );
}

export async function listDecisions(): Promise<Decision[] | null> {
  return apiFetch<Decision[] | null>("/v1/arbitrage/decisions", { allowForbidden: true });
}

export interface ReliabilityStats {
  nb_decisions_revues: number;
  nb_confirmees: number;
  taux_confirmation_pct: number | null;
  historique_suffisant: boolean;
  note: string;
}

export async function getReliability(): Promise<ReliabilityStats | null> {
  return apiFetch<ReliabilityStats | null>("/v1/arbitrage/reliability", { allowForbidden: true });
}
