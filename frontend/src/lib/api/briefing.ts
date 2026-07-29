import { apiFetch } from "./client";

export interface BriefingSection {
  facts: Record<string, unknown>;
  bullets: string[];
  /** Résumé en 5 lignes affiché en tête de cockpit. Absent des briefings
   * générés avant l'ajout du résumé — traiter comme optionnel. */
  resume?: string[];
  /** Décision du jour, choisie par un calcul déterministe (jamais le LLM) —
   * absente des briefings générés avant son ajout, traiter comme optionnelle. */
  action?: string;
  analysis: string;
}

export interface Briefing {
  generated_at: string | null;
  triggered_by: string | null;
  role: string;
  section: BriefingSection | null;
}

export async function getBriefing(): Promise<Briefing | null> {
  return apiFetch<Briefing | null>("/v1/briefing", { allowForbidden: true });
}
