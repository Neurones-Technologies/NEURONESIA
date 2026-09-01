import type { AuditLine } from "@/lib/api/admin";
import { ROLE_LABELS } from "@/lib/auth/roles";
import { moduleLabel } from "@/lib/data/modules";

/** Mise en phrase du journal d'administration.
 *
 * Le backend enregistre un DELTA structuré (`{role: {avant, apres}}`) et non une
 * phrase : une phrase figée dans la base ne se retraduit pas, ne se filtre pas,
 * et vieillit mal — un libellé de module renommé rendrait toutes les lignes
 * anciennes fausses. La mise en mots se fait donc ici, à la lecture.
 *
 * Conséquence assumée : une action dont la forme changerait côté backend
 * s'afficherait en repli (`_repli`), c'est-à-dire lisible mais brute. C'est le
 * bon échec pour un journal — jamais une ligne muette.
 *
 * Module ordinaire (ni `"use client"` ni `"use server"`) : lu par des composants
 * serveur (le journal, la fiche) qui n'ont pas besoin d'un bundle client.
 */

const ACTION_LABELS: Record<string, string> = {
  "user.create": "Compte créé",
  "user.update": "Compte modifié",
  "user.delete": "Compte supprimé",
  "permission.update": "Droit modifié",
  "permission.reset": "Droits réinitialisés",
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action;
}

/** Champs d'un `user.update`, dans un ordre de lecture stable — l'ordre des clés
 * d'un objet JSON ne l'est pas, et deux lignes identiques ne doivent pas se lire
 * différemment d'un rendu à l'autre. */
const CHAMPS: readonly [string, string][] = [
  ["role", "rôle"],
  ["is_active", "statut"],
  ["email", "adresse"],
  ["full_name", "nom"],
  ["password", "mot de passe"],
];

function valeur(champ: string, brut: unknown): string {
  if (champ === "role") return ROLE_LABELS[String(brut)] ?? String(brut);
  if (champ === "is_active") return brut === true ? "actif" : "désactivé";
  return String(brut);
}

function _repli(details: Record<string, unknown>): string {
  const clés = Object.keys(details);
  return clés.length > 0 ? clés.join(", ") : "—";
}

/** Ce que la ligne a changé, en une phrase. */
export function auditDetail(ligne: AuditLine): string {
  const d = ligne.details ?? {};

  switch (ligne.action) {
    case "user.create":
      return `rôle ${valeur("role", d.role)}${d.full_name ? ` · ${d.full_name}` : ""}`;

    case "user.delete":
      return `rôle ${valeur("role", d.role)} · ${
        d.is_active === false ? "compte déjà désactivé" : "compte encore actif"
      }`;

    case "user.update": {
      const morceaux = CHAMPS.filter(([clé]) => clé in d).map(([clé, libellé]) => {
        if (clé === "password") return "mot de passe réinitialisé";
        const delta = d[clé] as { avant?: unknown; apres?: unknown } | undefined;
        if (!delta || !("apres" in delta)) return libellé;
        return `${libellé} : ${valeur(clé, delta.avant)} → ${valeur(clé, delta.apres)}`;
      });
      return morceaux.length > 0 ? morceaux.join(" · ") : _repli(d);
    }

    case "permission.update": {
      if (typeof d.view !== "string" || typeof d.role !== "string") return _repli(d);
      return `${moduleLabel(d.view)} — ${ROLE_LABELS[d.role] ?? d.role} : ${
        d.avant === true ? "autorisé" : "refusé"
      } → ${d.apres === true ? "autorisé" : "refusé"}`;
    }

    case "permission.reset": {
      const n = Number(d.surcharges_effacees ?? 0);
      return n === 0
        ? "aucune surcharge n'était enregistrée — retour aux défauts sans effet"
        : `${n} surcharge(s) effacée(s), retour aux défauts du code`;
    }

    default:
      return _repli(d);
  }
}
