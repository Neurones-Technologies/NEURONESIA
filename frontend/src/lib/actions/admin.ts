"use server";

import { revalidatePath } from "next/cache";
import type { AdminActionState } from "@/lib/actions/admin-state";
import { ApiError, apiFetch } from "@/lib/api/client";
import { ROLE_LABELS } from "@/lib/auth/roles";

/** Actions de l'écran Comptes.
 *
 * Le contrôle reste ENTIÈREMENT serveur : `_require_admin` sur chaque endpoint,
 * protection du dernier admin actif, refus de l'auto-suppression. Ce qui est
 * vérifié ici ne dispense de rien — cela évite d'envoyer une requête dont on
 * sait déjà qu'elle sera refusée, et donne au refus une phrase posée au bon
 * champ plutôt qu'un rechargement muet.
 *
 * Les règles dupliquées (longueur minimale du mot de passe, présence d'un « @ »)
 * sont des ÉCHOS de la règle backend, pas la règle : si les deux divergent, c'est
 * le serveur qui tranche, et le message affiché sera le sien (cf. `fromError`,
 * qui préfère toujours le `detail` du backend). */

const MDP_MIN = 6; // écho de `create_user` / `update_user` (api/v1/auth.py)

function ok(message: string): AdminActionState {
  return { status: "ok", message, at: Date.now() };
}

function ko(message: string, field?: string): AdminActionState {
  return { status: "error", message, field, at: Date.now() };
}

/** Traduit une panne d'appel en phrase affichable. Le `detail` du backend est
 * déjà rédigé pour l'utilisateur (« Impossible : c'est le dernier compte admin
 * actif ») : on le préfère systématiquement à un message générique. */
function fromError(error: unknown, fallback: string): AdminActionState {
  if (error instanceof ApiError) {
    if (error.status === 403) {
      return ko(error.detail || "Cette action est réservée aux administrateurs.");
    }
    return ko(error.detail || fallback);
  }
  return ko(fallback);
}

/** Revalide les écrans qu'une écriture rend faux.
 *
 * `params` autant que `admin` : la vue Réglages affiche la disponibilité des
 * modules du compte connecté, qui dépend de la matrice qu'on vient de modifier.
 */
function revalider(profile: string, avecReglages = false): void {
  if (!profile) return;
  revalidatePath(`/${profile}/admin`);
  if (avecReglages) revalidatePath(`/${profile}/params`);
}

function libelleRole(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

// ---------- Comptes ----------

export async function createUserAction(
  _prev: AdminActionState,
  formData: FormData
): Promise<AdminActionState> {
  const profile = String(formData.get("profile") ?? "");
  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  const fullName = String(formData.get("full_name") ?? "").trim();
  const role = String(formData.get("role") ?? "").trim();
  const password = String(formData.get("password") ?? "");

  if (!email || !email.includes("@")) {
    return ko("Saisissez une adresse e-mail valide — c'est l'identifiant de connexion.", "email");
  }
  if (!fullName) {
    return ko(
      "Le nom complet est requis : c'est lui qui s'affiche dans l'en-tête et signe les décisions journalisées.",
      "full_name"
    );
  }
  if (!role) return ko("Choisissez le rôle du compte.", "role");
  if (password.length < MDP_MIN) {
    return ko(`Mot de passe trop court — ${MDP_MIN} caractères au minimum.`, "password");
  }

  let cree: { email: string; role: string };
  try {
    cree = await apiFetch<{ email: string; role: string }>("/v1/auth/users", {
      method: "POST",
      body: JSON.stringify({ email, password, full_name: fullName, role }),
    });
  } catch (error) {
    return fromError(error, "Le compte n'a pas pu être créé. Rien n'a été enregistré.");
  }

  revalider(profile);
  return ok(
    `Compte ${cree.email} créé avec le rôle ${libelleRole(cree.role)}. ` +
      "Communiquez-lui son mot de passe par un autre canal : il n'est plus lisible nulle part."
  );
}

/** Modifie l'identité et le rôle. Le mot de passe et le statut ont leurs propres
 * actions : réunis dans un seul formulaire, un changement de nom emporterait une
 * réinitialisation de mot de passe non voulue. */
export async function updateUserAction(
  _prev: AdminActionState,
  formData: FormData
): Promise<AdminActionState> {
  const profile = String(formData.get("profile") ?? "");
  const id = String(formData.get("user_id") ?? "");
  if (!id) return ko("Compte introuvable — rechargez la page avant de réessayer.");

  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  const fullName = String(formData.get("full_name") ?? "").trim();
  const role = String(formData.get("role") ?? "").trim();

  if (!email || !email.includes("@")) {
    return ko("Saisissez une adresse e-mail valide.", "email");
  }
  if (!fullName) return ko("Le nom complet ne peut pas être vide.", "full_name");
  if (!role) return ko("Choisissez le rôle du compte.", "role");

  try {
    await apiFetch(`/v1/auth/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ email, full_name: fullName, role }),
    });
  } catch (error) {
    return fromError(error, "La modification n'a pas pu être enregistrée. Rien n'a changé.");
  }

  revalider(profile);
  return ok(
    `Compte modifié — rôle ${libelleRole(role)}. Le changement s'applique à la requête suivante : ` +
      "la session en cours de cette personne voit son périmètre changer sans se reconnecter."
  );
}

export async function toggleActiveAction(
  _prev: AdminActionState,
  formData: FormData
): Promise<AdminActionState> {
  const profile = String(formData.get("profile") ?? "");
  const id = String(formData.get("user_id") ?? "");
  const email = String(formData.get("email") ?? "");
  // `is_active` porte l'état VOULU, calculé à l'affichage : envoyer une bascule
  // (« inverse l'état ») ferait dépendre le résultat de la fraîcheur de l'écran.
  const actif = String(formData.get("is_active") ?? "") === "true";
  if (!id) return ko("Compte introuvable — rechargez la page avant de réessayer.");

  try {
    await apiFetch(`/v1/auth/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_active: actif }),
    });
  } catch (error) {
    return fromError(error, "Le statut n'a pas pu être changé. Rien n'a changé.");
  }

  revalider(profile);
  return ok(
    actif
      ? `Compte ${email} réactivé : la connexion est de nouveau possible.`
      : `Compte ${email} désactivé : la connexion est refusée dès maintenant. ` +
        "Le compte et ses traces restent en place — c'est la voie à préférer à la suppression."
  );
}

export async function resetPasswordAction(
  _prev: AdminActionState,
  formData: FormData
): Promise<AdminActionState> {
  const profile = String(formData.get("profile") ?? "");
  const id = String(formData.get("user_id") ?? "");
  const password = String(formData.get("password") ?? "");
  const confirmation = String(formData.get("password_confirm") ?? "");
  if (!id) return ko("Compte introuvable — rechargez la page avant de réessayer.");

  if (password.length < MDP_MIN) {
    return ko(`Mot de passe trop court — ${MDP_MIN} caractères au minimum.`, "password");
  }
  // Le mot de passe posé ici n'est plus relisible ensuite : une faute de frappe
  // enfermerait la personne dehors sans que personne ne sache quoi lui dire.
  if (password !== confirmation) {
    return ko("Les deux saisies diffèrent.", "password_confirm");
  }

  try {
    await apiFetch(`/v1/auth/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ password }),
    });
  } catch (error) {
    return fromError(error, "Le mot de passe n'a pas pu être réinitialisé. Rien n'a changé.");
  }

  revalider(profile);
  return ok(
    "Mot de passe réinitialisé. Transmettez-le par un autre canal : il n'est stocké nulle part en clair, " +
      "et le journal n'en garde que le fait, pas la valeur."
  );
}

export async function deleteUserAction(
  _prev: AdminActionState,
  formData: FormData
): Promise<AdminActionState> {
  const profile = String(formData.get("profile") ?? "");
  const id = String(formData.get("user_id") ?? "");
  const email = String(formData.get("email") ?? "");
  const saisie = String(formData.get("confirmation") ?? "").trim().toLowerCase();
  if (!id) return ko("Compte introuvable — rechargez la page avant de réessayer.");

  // La suppression est le seul geste irréversible de cet écran, et le seul dont
  // le résultat est indistinguable d'une désactivation à l'œil nu. Faire
  // recopier l'adresse rend l'erreur de ligne impossible.
  if (saisie !== email.toLowerCase()) {
    return ko(
      `Pour supprimer définitivement ce compte, recopiez son adresse exacte : ${email}`,
      "confirmation"
    );
  }

  try {
    await apiFetch(`/v1/auth/users/${id}`, { method: "DELETE" });
  } catch (error) {
    return fromError(error, "Le compte n'a pas pu être supprimé. Rien n'a changé.");
  }

  revalider(profile);
  return ok(
    `Compte ${email} supprimé définitivement. Ses décisions et ses réglages restent au registre, ` +
      "signés de cette adresse, et la suppression elle-même est journalisée."
  );
}

// ---------- Matrice module × rôle ----------

/** Bascule UNE cellule de la matrice.
 *
 * La cellule arrive dans un seul champ, `cell` = `"<view>|<role>|<voulu>"`, parce
 * qu'un `<button type="submit">` ne porte qu'un couple nom/valeur. C'est ce qui
 * permet aux 70 cellules de partager UN formulaire et UN `useActionState` : une
 * cellule = un bouton, au lieu de 70 formulaires et 70 états d'attente.
 *
 * `voulu` est l'état CIBLE, calculé au rendu, et non une bascule (« inverse ») :
 * sur un écran laissé ouvert pendant qu'un autre admin modifie la matrice, une
 * bascule appliquerait l'inverse de ce que la personne voit. */
export async function setPermissionAction(
  _prev: AdminActionState,
  formData: FormData
): Promise<AdminActionState> {
  const profile = String(formData.get("profile") ?? "");
  const [view = "", role = "", voulu = ""] = String(formData.get("cell") ?? "").split("|");
  const allowed = voulu === "true";
  if (!view || !role) return ko("Cellule introuvable — rechargez la page avant de réessayer.");

  try {
    await apiFetch("/v1/auth/permissions", {
      method: "PATCH",
      body: JSON.stringify({ view, role, allowed }),
    });
  } catch (error) {
    return fromError(error, "Le droit n'a pas pu être modifié. La matrice est inchangée.");
  }

  revalider(profile, true);
  return ok(
    `${libelleRole(role)} : module « ${view} » ${allowed ? "autorisé" : "retiré"}. ` +
      "Appliqué dès la requête suivante, sur les endpoints comme à l'écran."
  );
}

export async function resetPermissionsAction(
  _prev: AdminActionState,
  formData: FormData
): Promise<AdminActionState> {
  const profile = String(formData.get("profile") ?? "");
  try {
    await apiFetch("/v1/auth/permissions/reset", { method: "POST" });
  } catch (error) {
    return fromError(error, "La réinitialisation a échoué. La matrice est inchangée.");
  }

  revalider(profile, true);
  return ok(
    "Matrice réinitialisée : toutes les surcharges sont effacées, les droits reviennent aux " +
      "défauts fixés dans le code du backend."
  );
}
