import { CSSProperties } from "react";

/** Bloc scintillant — seule brique de chargement qui subsiste.
 *
 * Les squelettes de page (`PageSkeleton`, `SectionSkeleton`, `ShellSkeleton` et
 * leurs tuiles) ont été supprimés avec les `loading.tsx` qui les portaient :
 * chronométrés au navigateur, ils n'amortissaient aucune attente. Le
 * `ShellSkeleton` du chargement complet apparaissait entre 220 et 840 ms — donc
 * à la toute fin du chargement, quand le contenu était déjà prêt — et repartait
 * après 1 à 95 ms. Il ne masquait rien : il ajoutait un clignotement.
 *
 * `Skel` reste parce que deux frontières Suspense, elles, couvrent une vraie
 * attente : `ui/analysis-slot.tsx` (10 à 20 s si la narration du jour n'a pas été
 * générée) et `views/arbitrage/DossierPending.tsx` (rejouée à chaque changement
 * de dossier). */
export function Skel({
  width = "100%",
  height = 14,
  radius = 6,
  style,
}: {
  width?: number | string;
  height?: number | string;
  radius?: number;
  style?: CSSProperties;
}) {
  return (
    <span
      className="skel"
      style={{ width, height, borderRadius: radius, ...style }}
      aria-hidden="true"
    />
  );
}
