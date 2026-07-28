import { apiFetch } from "./client";

export interface SupplierIntelligence {
  name: string;
  montant_total_xof: number;
  nb_commandes: number;
  taux_dependance_pct: number;
  credit_limit_xof: number | null;
  encours_du_xof: number;
  taux_consommation_credit_pct: number | null;
  cash_30j_xof: number;
  cash_60j_xof: number;
  cash_90j_xof: number;
  cash_plus_90j_xof: number;
  marge_sous_traitance_xof: number;
  nb_dossiers_lies: number;
  payment_term_name: string | null;
  payment_term_days: number | null;
  retard_moyen_jours: number | null;
  dossiers_a_risque_fournisseur_unique: number;
}

export async function getSupplierIntelligence(limit = 20): Promise<SupplierIntelligence[] | null> {
  return apiFetch<SupplierIntelligence[] | null>(`/v1/partners/intelligence?limit=${limit}`, {
    allowForbidden: true,
  });
}

export interface PartnersAnalysis {
  analysis: string;
  context?: Record<string, unknown>;
}

export async function getPartnersAnalysis(): Promise<PartnersAnalysis | null> {
  return apiFetch<PartnersAnalysis | null>("/v1/partners/analysis", {
    method: "POST",
    allowForbidden: true,
  });
}
