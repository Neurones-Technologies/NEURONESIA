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
  /** Entité du briefing (CI / BF / GN) quand un pays a été demandé et que le
   * rôle en a un (DG) ; `null` = briefing groupe. */
  entite?: string | null;
  section: BriefingSection | null;
}

/** `pays` (ci / bf / gn) : briefing de l'entité, pour les rôles qui en ont un
 * (le DG). Ignoré par le backend pour les autres rôles. */
export async function getBriefing(pays?: string): Promise<Briefing | null> {
  const q = pays ? `?pays=${encodeURIComponent(pays)}` : "";
  return apiFetch<Briefing | null>(`/v1/briefing${q}`, { allowForbidden: true });
}

/** Un élément que le débrief peut contenir, avec son état pour ce rôle. Le
 * catalogue vient du backend à chaque appel — le dupliquer ici divergerait dès
 * qu'un élément est ajouté ou renommé. */
export interface DebriefElement {
  id: string;
  libelle: string;
  description: string;
  actif: boolean;
}

export interface DebriefPreferences {
  role: string;
  elements: DebriefElement[];
  consigne: string;
  consigne_max: number;
  /** "defaut" = aucun réglage enregistré, le catalogue par défaut s'applique. */
  source: "defaut" | "reglee";
  updated_by: string | null;
  updated_at: string | null;
}

/** `null` quand le rôle demandé n'est pas celui du demandeur (403 non-admin) :
 * le bloc de réglage ne s'affiche alors pas, plutôt que de casser la page. */
export async function getBriefingPreferences(role?: string): Promise<DebriefPreferences | null> {
  const q = role ? `?role=${encodeURIComponent(role)}` : "";
  return apiFetch<DebriefPreferences | null>(`/v1/briefing/preferences${q}`, {
    allowForbidden: true,
  });
}
