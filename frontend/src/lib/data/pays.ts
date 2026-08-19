/** Périmètre géographique du cockpit DC.
 *
 * Le groupe opère sur trois pays, mais le miroir de données ne porte aujourd'hui
 * que la Côte d'Ivoire. Le sélecteur existe quand même dès maintenant : il rend le
 * périmètre de lecture EXPLICITE (un chiffre du cockpit est un chiffre ivoirien,
 * pas un chiffre groupe), et les autres pays affichent « Donnée non disponible »
 * plutôt que d'être absents du choix — l'écart entre l'ambition et le disponible
 * reste visible.
 *
 * Le pays vit dans l'URL (`?pays=…`) comme la cadence et l'exercice : pages en
 * composants serveur, lecture partageable par lien. */

export type Pays = "ci" | "bf" | "gn";

export const PAYS: { id: Pays; label: string }[] = [
  { id: "ci", label: "Côte d'Ivoire" },
  { id: "bf", label: "Burkina Faso" },
  { id: "gn", label: "Guinée" },
];

/** Seul pays dont le miroir porte des données aujourd'hui. */
export const PAYS_AVEC_DONNEES: Pays = "ci";

export function estPays(valeur: string | undefined): valeur is Pays {
  return PAYS.some((p) => p.id === valeur);
}

/** Un `?pays=` absent ou absurde retombe sur la Côte d'Ivoire : un lien mal
 * recopié ouvre le cockpit habituel, pas un écran « non disponible » injustifié. */
export function paysDe(valeur: string | undefined): Pays {
  return estPays(valeur) ? valeur : PAYS_AVEC_DONNEES;
}

export function paysLabel(pays: Pays): string {
  return PAYS.find((p) => p.id === pays)?.label ?? pays;
}
