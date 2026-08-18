"use server";

import { revalidatePath } from "next/cache";

import type { BriefingActionState } from "@/lib/actions/briefing-state";
import { ApiError, apiFetch } from "@/lib/api/client";

/** Actions de composition du débrief quotidien.
 *
 * Même structure que `lib/actions/arbitrage.ts` : chaque chemin renvoie une
 * phrase affichable, jamais un `return` nu — sur un écran de réglages, une
 * sauvegarde qui échoue en silence laisse croire que le choix est enregistré.
 *
 * Le contrôle de périmètre reste celui du serveur (`router._require_role_scope`) :
 * ce qui est vérifié ici évite seulement d'envoyer une requête dont on sait
 * déjà qu'elle sera refusée. */

function ok(message: string): BriefingActionState {
  return { status: "ok", message, at: Date.now() };
}

function ko(message: string, field?: string): BriefingActionState {
  return { status: "error", message, field, at: Date.now() };
}

/** Le `detail` du backend est déjà rédigé pour l'utilisateur (élément inconnu,
 * sélection vide, rôle hors périmètre) : on le préfère à un message générique. */
function fromError(error: unknown, fallback: string): BriefingActionState {
  if (error instanceof ApiError) {
    if (error.status === 403) {
      return ko(error.detail || "Ce réglage relève d'un autre profil que le vôtre.");
    }
    return ko(error.detail || fallback);
  }
  return ko(fallback);
}

export async function saveDebriefAction(
  _prev: BriefingActionState,
  formData: FormData
): Promise<BriefingActionState> {
  const profile = String(formData.get("profile") ?? "");
  const role = String(formData.get("role") ?? "");
  if (!role) return ko("Profil introuvable — rechargez la page avant de réessayer.");

  // `getAll` et non `get` : c'est ce qui rend la multi-sélection possible. Toutes
  // les cases portent le même `name="elements"` et se distinguent par leur value.
  // Une case décochée est absente du FormData — d'où la liste blanche côté
  // backend, où « absent » signifie « décoché ».
  const elements = formData.getAll("elements").map(String).filter(Boolean);
  const consigne = String(formData.get("consigne") ?? "").trim();
  const consigneMax = Number(formData.get("consigne_max") ?? 400);

  // Rien de coché est accepté si une consigne est posée : mode « consigne
  // pilote », où le débrief est rédigé à partir des seules consignes. Le
  // backend refait le même contrôle sur la consigne nettoyée des balises.
  if (elements.length === 0 && !consigne) {
    return ko(
      "Cochez au moins un élément, ou rédigez une consigne : sans l'un ni l'autre, le débrief n'aurait rien à raconter.",
      "elements"
    );
  }
  if (consigne.length > consigneMax) {
    return ko(`Consigne trop longue : ${consigneMax} caractères maximum.`, "consigne");
  }

  try {
    await apiFetch("/v1/briefing/preferences", {
      method: "PUT",
      body: JSON.stringify({ role, elements, consigne }),
    });
  } catch (error) {
    return fromError(error, "La composition n'a pas pu être enregistrée. Rien n'a changé.");
  }

  if (profile) revalidatePath(`/${profile}/params`);
  // Le message dit explicitement que le débrief affiché n'a pas encore bougé :
  // sans cette phrase, on enregistre, on va voir sa Vision, on n'y trouve aucun
  // changement — et on en conclut que le réglage ne marche pas.
  return ok(
    elements.length === 0
      ? "Mode consigne enregistré : le débrief sera rédigé uniquement à partir de vos consignes, en piochant dans les données réelles du profil. « Régénérer » l'applique tout de suite."
      : "Composition enregistrée. Elle s'appliquera au prochain débrief — « Régénérer » l'applique tout de suite."
  );
}

export async function regenerateDebriefAction(
  _prev: BriefingActionState,
  formData: FormData
): Promise<BriefingActionState> {
  const profile = String(formData.get("profile") ?? "");
  const role = String(formData.get("role") ?? "");
  if (!role) return ko("Profil introuvable — rechargez la page avant de réessayer.");

  try {
    await apiFetch(`/v1/briefing/refresh?role=${encodeURIComponent(role)}`, { method: "POST" });
  } catch (error) {
    return fromError(error, "La régénération a échoué. Le débrief précédent reste affiché.");
  }

  if (profile) {
    revalidatePath(`/${profile}/params`);
    // C'est l'écran Vision qui affiche le débrief : sans cette seconde
    // revalidation, le texte régénéré resterait invisible là où on va le lire.
    revalidatePath(`/${profile}/vision`);
  }
  return ok("Débrief régénéré à partir de cette composition. Il est visible depuis l'écran Vision.");
}
