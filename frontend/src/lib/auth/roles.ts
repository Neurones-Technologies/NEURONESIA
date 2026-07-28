import { ProfileKey } from "@/lib/types";

/** Rôles bruts renvoyés par le backend (core/domain/user.py::UserRole). */
export type BackendRole =
  | "admin"
  | "user"
  | "viewer"
  | "dg"
  | "dir_commercial"
  | "dir_operations"
  | "presale"
  | "dir_financier"
  | "commercial";

const ROLE_TO_PROFILE: Record<string, ProfileKey> = {
  dg: "dg",
  dir_commercial: "dc",
  dir_operations: "do",
  dir_financier: "df",
  commercial: "am",
};

/** Profil cockpit correspondant au rôle backend, ou null si ce rôle n'a pas
 * (encore) de profil dédié (admin, presale, user, viewer). */
export function roleToProfile(role: string): ProfileKey | null {
  return ROLE_TO_PROFILE[role] ?? null;
}

export function isAdminRole(role: string): boolean {
  return role === "admin";
}

export const ROLE_LABELS: Record<string, string> = {
  admin: "Administrateur",
  dg: "Direction générale",
  dir_commercial: "Direction commerciale",
  dir_operations: "Direction des opérations",
  dir_financier: "Direction financière",
  commercial: "Account manager",
  presale: "Avant-vente",
  user: "Utilisateur",
  viewer: "Lecture seule",
};
