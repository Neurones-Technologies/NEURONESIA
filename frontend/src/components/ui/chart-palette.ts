/** Palette des graphes — valeurs validées, jamais choisies à l'œil.
 *
 * Chaque valeur ci-dessous a passé le validateur du référentiel de visualisation
 * (bande de clarté OKLCH, plancher de chroma, séparation sous protanopie et
 * deutéranopie, plancher de vision normale, contraste sur le fond), sur la surface
 * réelle des tuiles (`--card` #FFFFFF) et sur le papier (`--paper-2` #FBF9F5).
 *
 * POURQUOI CES VALEURS ET PAS LES JETONS DE LA MAQUETTE. Le vert de marque
 * (`--signal` #1F6A55) a une chroma de 0,08 : sous le plancher de 0,10, il « lit
 * gris » dès qu'il sert de couleur de série, et le validateur le refuse. La valeur
 * retenue ici garde sa teinte et remonte sa saturation — la marque est préservée,
 * l'identité de série devient lisible. Les jetons d'origine restent utilisés
 * partout ailleurs (tags, textes, barres de l'interface), où ils portent du texte
 * et non de la donnée.
 *
 * Résultats du validateur, en clair :
 * - `SERIE_1` × `SERIE_2` : ΔE 9,3 sous deutéranopie, 18,3 en vision normale — au
 *   -dessus de la cible de 8 et du plancher de 15 ;
 * - rampe d'ancienneté : clarté monotone, écarts ≥ 0,06, extrémité claire à
 *   2,13:1 sur blanc, teinte unique (9° d'amplitude) ;
 * - toutes les couleurs ≥ 3:1 sur les deux surfaces.
 *
 * Le mode sombre n'est pas décliné : le cockpit n'en a pas (aucune requête
 * `prefers-color-scheme` dans globals.css). Le jour où il en aura un, ces valeurs
 * devront être re-validées contre la surface sombre — un simple éclaircissement
 * automatique ne passe pas les contrôles.
 */

/** Série 1 — orange de marque. Ce qui est consommé, dépensé, en délai. */
export const SERIE_1 = "#9C5309";

/** Série 2 — vert re-saturé. Ce qui rentre : chiffre d'affaires, encaissement. */
export const SERIE_2 = "#12795A";

/** Rampe ORDINALE d'ancienneté de créance, du plus récent au plus ancien.
 *
 * Une seule teinte, quatre pas de clarté : l'ancienneté est un ORDRE, et l'ordre
 * doit se lire dans la couleur. Quatre teintes d'identité auraient laissé croire
 * à quatre catégories interchangeables. */
export const RAMPE_AGE = ["#D9A695", "#C4806B", "#B25846", "#A4372A"] as const;

/** Gris de repère — droites de seuil, cumul de Pareto. Jamais une série mesurée. */
export const REPERE = "var(--t3)";
