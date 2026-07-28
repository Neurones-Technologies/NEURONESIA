import { apiFetch } from "./client";

export interface CrossSellItem {
  client: string;
  titre: string;
  detail: string;
  montant_xof: number;
  age_mois?: number;
}

export interface CrossSellSignals {
  renouvellement: CrossSellItem[];
  obsolete: CrossSellItem[];
  cross_sell: CrossSellItem[];
  up_sell: CrossSellItem[];
}

export async function getCrossSellSignals(): Promise<CrossSellSignals | null> {
  return apiFetch<CrossSellSignals | null>("/v1/crosssell/signals", { allowForbidden: true });
}

export interface CrossSellAnalysis {
  analysis: string;
  context?: Record<string, unknown>;
}

export async function getCrossSellAnalysis(): Promise<CrossSellAnalysis | null> {
  return apiFetch<CrossSellAnalysis | null>("/v1/crosssell/analysis", {
    method: "POST",
    allowForbidden: true,
  });
}
