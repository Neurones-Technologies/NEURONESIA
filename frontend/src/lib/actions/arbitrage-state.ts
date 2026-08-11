/** État de retour des actions d'arbitrage, consommé par `useActionState`.
 *
 * Ce fichier n'a PAS la directive `"use server"`, et c'est la raison de son
 * existence : un module `"use server"` ne peut exporter que des fonctions
 * asynchrones. Une constante qui y était déclarée traversait la frontière sous
 * forme de référence serveur opaque — `ARBITRAGE_IDLE.status` valait alors
 * `undefined` côté client, l'état n'était jamais « idle », et le bandeau de
 * retour s'affichait vide sous chaque formulaire. Bug réel rencontré. */
export interface ArbitrageActionState {
  status: "idle" | "ok" | "error";
  message: string;
  /** Champ en cause, pour poser l'erreur au bon endroit du formulaire. */
  field?: string;
  /** Horodatage : deux échecs identiques restent deux évènements distincts,
   * sinon `aria-live` ne réannonce pas le second. */
  at?: number;
}

export const ARBITRAGE_IDLE: ArbitrageActionState = { status: "idle", message: "" };
