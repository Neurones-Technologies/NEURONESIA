import type { ArbitrageActionState } from "@/lib/actions/arbitrage-state";

/** État de retour des actions du débrief, consommé par `useActionState`.
 *
 * Ce fichier n'a PAS la directive `"use server"`, et c'est la raison de son
 * existence : un module `"use server"` ne peut exporter que des fonctions
 * asynchrones, et une constante qui y serait déclarée traverserait la frontière
 * en référence opaque — `.status` vaudrait `undefined` et le bandeau de retour
 * s'afficherait vide. Bug réel rencontré sur les formulaires d'arbitrage, dont
 * ce module reprend la structure.
 *
 * Le contrat est identique à celui d'arbitrage : un alias plutôt qu'une copie,
 * ce qui permet aussi de réutiliser `ActionMessage` et `SubmitBtn` sans les
 * dupliquer. */
export type BriefingActionState = ArbitrageActionState;

export const BRIEFING_IDLE: BriefingActionState = { status: "idle", message: "" };
