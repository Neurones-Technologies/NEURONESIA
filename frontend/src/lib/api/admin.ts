import { ApiError, apiFetch } from "./client";

/** Lectures de l'écran Comptes — toutes réservées à l'administrateur côté
 * serveur (`api/v1/auth.py::_require_admin`). À n'appeler que depuis une page
 * déjà protégée (cf. `[profile]/admin/page.tsx`) : le 403 n'est pas rattrapé
 * ici, une page ouverte au mauvais rôle doit tomber, pas s'afficher à moitié. */

export interface AdminUser {
  id: number;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  last_login: string | null;
  created_at: string | null;
}

export interface AdminUsersPage {
  users: AdminUser[];
  /** Compteurs de l'effectif COMPLET, indépendants des filtres — « 1 compte
   * actif » sur une recherche à un résultat serait un contresens. */
  total: number;
  actifs: number;
  /** Comptes jamais utilisés : un accès ouvert que personne ne surveille, ce qui
   * n'est pas la même chose qu'un compte désactivé. */
  jamais_connectes: number;
  /** Sert à annoncer le garde-fou du dernier admin AVANT le clic. */
  admins_actifs: number;
  roles: string[];
}

export interface UsersFilters {
  q?: string;
  role?: string;
  /** `undefined` = les deux ; `true` actifs seuls ; `false` désactivés seuls. */
  actif?: boolean;
}

/** Périmètre effectif d'un compte, tel que le serveur l'applique réellement. */
export interface UserPerimetre {
  is_admin: boolean;
  modules: { view: string; allowed: boolean }[];
  total: number;
  autorises: number;
}

export interface UserActivite {
  questions_copilote: number;
  derniere_question: string | null;
  profils: { profile: string; questions: number }[];
}

export interface UserEmpreinte {
  decisions_creees: number;
  decisions_tranchees: number;
  derniere_decision: string | null;
  contextes_renseignes: number;
  reglages: { objet: string; cle: string; at: string | null }[];
}

export interface AuditLine {
  id: number;
  at: string | null;
  actor_email: string;
  action: string;
  target_email: string;
  target_id: number | null;
  /** Delta de l'action — forme variable selon `action`, jamais interprété comme
   * du HTML à l'affichage (cf. `AuditJournal`). */
  details: Record<string, unknown>;
}

export interface UserDetail {
  compte: AdminUser & {
    anciennete_jours: number | null;
    jamais_connecte: boolean;
    est_moi: boolean;
  };
  perimetre: UserPerimetre;
  activite: UserActivite;
  empreinte: UserEmpreinte;
  journal: AuditLine[];
}

export interface PermissionMatrix {
  roles: string[];
  views: string[];
  matrix: Record<string, Record<string, boolean>>;
}

export interface AuditPage {
  lignes: AuditLine[];
  total: number;
  limit: number;
}

/** Liste filtrée. Les filtres sont passés au serveur et non appliqués à
 * l'écran : un filtre seulement visuel laisserait croire à un périmètre qu'il
 * ne garantit pas, et la liste doit rester utilisable au-delà d'une page. */
export async function getUsers(filters: UsersFilters = {}): Promise<AdminUsersPage> {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.role) params.set("role", filters.role);
  if (filters.actif !== undefined) params.set("actif", String(filters.actif));
  const query = params.toString();
  return apiFetch<AdminUsersPage>(`/v1/auth/users${query ? `?${query}` : ""}`);
}

/** Fiche détaillée, ou `null` si le compte n'existe plus.
 *
 * Le `null` est le cas normal, pas une panne : la fiche ouverte vit dans l'URL
 * (`?compte=<id>`), et cette URL survit à la suppression du compte — un lien
 * partagé, un retour arrière, un rechargement après suppression. La page affiche
 * alors « ce compte n'existe plus » au lieu de tomber en erreur. */
export async function getUserDetail(id: number): Promise<UserDetail | null> {
  try {
    return await apiFetch<UserDetail>(`/v1/auth/users/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export async function getPermissions(): Promise<PermissionMatrix> {
  return apiFetch<PermissionMatrix>("/v1/auth/permissions");
}

export async function getAudit(limit = 30): Promise<AuditPage> {
  return apiFetch<AuditPage>(`/v1/auth/audit?limit=${limit}`);
}
