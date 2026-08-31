/** État de retour des actions d'administration, consommé par `useActionState`.
 *
 * Fichier séparé, SANS la directive `"use server"` — pour la même raison que
 * `arbitrage-state.ts` : un module serveur ne peut exporter que des fonctions
 * asynchrones, et une constante qui y serait déclarée traverserait la frontière
 * sous forme de référence opaque (`ADMIN_IDLE.status` valant `undefined` côté
 * client, donc un bandeau de retour vide sous chaque formulaire). */
export interface AdminActionState {
  status: "idle" | "ok" | "error";
  message: string;
  /** Champ en cause, pour poser l'erreur au bon endroit du formulaire. */
  field?: string;
  /** Horodatage : deux échecs identiques restent deux évènements distincts,
   * sinon `aria-live` ne réannonce pas le second. */
  at?: number;
}

export const ADMIN_IDLE: AdminActionState = { status: "idle", message: "" };
