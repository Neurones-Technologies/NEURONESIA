import { apiFetch } from "./client";

export interface ClientPortfolioEntry {
  client: string;
  nb_dossiers: number;
  ca_total_xof: number;
  reste_a_encaisser_xof: number;
  backlog_xof: number;
  premiere_commande: string | null;
  derniere_commande: string | null;
  secteur: string | null;
  contact_email: string | null;
  telephone: string | null;
  dernier_projet: string | null;
  signaux: string[];
}

export async function getClientPortfolio(limit = 50): Promise<ClientPortfolioEntry[] | null> {
  return apiFetch<ClientPortfolioEntry[] | null>(`/v1/clients/portfolio?limit=${limit}`, {
    allowForbidden: true,
  });
}

export interface ClientProfile {
  activite?: string;
  recommandations?: string[];
  ai_generated?: boolean;
}

export async function getClientProfile(client: string): Promise<ClientProfile | null> {
  return apiFetch<ClientProfile | null>("/v1/clients/profile", {
    method: "POST",
    body: JSON.stringify({ client }),
    allowForbidden: true,
  });
}
