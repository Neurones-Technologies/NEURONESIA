import Link from "next/link";

/** Sélecteur d'exercice des onglets DAF.
 *
 * Même mécanique que la cadence du DC (`views/vision/dc/periode-nav.tsx`) et
 * mêmes classes CSS (`.dc-seg`) : le style du contrôle segmenté est unique dans
 * la feuille, le dupliquer sous un autre nom ferait dériver les deux au premier
 * ajustement. Seul le contenu diffère — un tableau de bord financier se lit par
 * exercice comptable, pas à une cadence libre.
 *
 * Les exercices proposés sont ceux pour lesquels le miroir porte des factures,
 * des achats ou des dossiers (`annees_disponibles`) : offrir un exercice vide
 * afficherait un écran sans chiffres sans dire pourquoi. */
export function ExerciceNav({
  basePath,
  annee,
  annees,
  nb = 5,
}: {
  /** Chemin de la section, p. ex. `/df/vision/budget`. */
  basePath: string;
  annee: number;
  annees?: number[];
  nb?: number;
}) {
  const proposes = (annees ?? []).slice(0, nb);
  if (proposes.length <= 1) return null;

  return (
    <div className="dc-seg-w">
      <span className="dc-seg-l">Exercice</span>
      <nav className="dc-seg" aria-label="Exercice">
        {proposes.map((a) => (
          <Link
            key={a}
            href={`${basePath}?annee=${a}`}
            aria-current={a === annee ? "page" : undefined}
            prefetch={false}
          >
            {a}
          </Link>
        ))}
      </nav>
    </div>
  );
}
