import { SourceDonnees } from "@/lib/api/commercial";
import { Note } from "@/components/ui/primitives";

/** Marquage de provenance des données, à l'écran.
 *
 * Le backend estampille chaque bloc (`source: "reel" | "statique" | "mixte"`) ;
 * ce module est le seul endroit du front qui décide comment cela se VOIT. Deux
 * règles :
 *
 * 1. Un bloc non mesuré ne s'affiche jamais nu. Le `kick` de la tuile le dit en
 *    trois mots, et une `SourceNote` sous le contenu dit POURQUOI la donnée
 *    manque — un utilisateur qui comprend la cause ne conteste pas l'écran, il
 *    va chercher la donnée.
 * 2. On ne réécrit pas la raison côté front. Elle vient du module de calcul, qui
 *    est le seul à savoir ce qu'il n'a pas pu mesurer (nombre d'opportunités
 *    concernées, dates d'import, taux de renseignement). Recopier ces chiffres
 *    ici les laisserait dériver au premier changement de données.
 */

const LIBELLES: Record<SourceDonnees, string | null> = {
  reel: null,
  statique: "données statiques",
  mixte: "objectif posé · réalisé mesuré",
};

/** Suffixe de `kick` pour une tuile. `base` reste devant quand il existe :
 * « pondéré · données statiques » se lit mieux que l'inverse. */
export function sourceKick(source: SourceDonnees | undefined, base?: string): string | undefined {
  const marque = source ? LIBELLES[source] : null;
  if (!marque) return base;
  return base ? `${base} · ${marque}` : marque;
}

export function estStatique(source: SourceDonnees | undefined): boolean {
  return source === "statique" || source === "mixte";
}

/** Avertissement de provenance. `raison` explique pourquoi la donnée réelle
 * n'existe pas ; `avertissement` est le rappel générique du backend. Les deux
 * sont facultatifs : sur un bloc `mixte`, la raison suffit souvent. */
export function SourceNote({
  source,
  raison,
  avertissement,
  style,
}: {
  source: SourceDonnees | undefined;
  raison?: string | null;
  avertissement?: string | null;
  style?: React.CSSProperties;
}) {
  if (!estStatique(source)) return null;
  const texte = [avertissement, raison].filter(Boolean).join(" ");
  if (!texte) return null;
  return (
    <Note accent style={{ marginTop: 14, ...style }}>
      {texte}
    </Note>
  );
}

/** Variante de tag pour une sévérité d'alerte. */
export const SEVERITE_TAG: Record<string, "r" | "w" | "s" | "a" | "n"> = {
  critique: "r",
  attention: "w",
  info: "n",
};

export const SEVERITE_VARIANT: Record<string, "r" | "w" | "s" | undefined> = {
  critique: "r",
  attention: "w",
  info: undefined,
};
