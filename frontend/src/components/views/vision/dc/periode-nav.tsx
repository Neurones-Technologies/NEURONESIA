import Link from "next/link";
import { Periode, PERIODES } from "@/lib/api/commercial";

/** Cadence de lecture — §1 du compte-rendu DC : « un point de pilotage mensuel,
 * trimestriel et annuel sur ces indicateurs ».
 *
 * La cadence vit dans l'URL (`?periode=…`) et non dans un état client. Trois
 * conséquences voulues :
 *
 * - l'onglet reste un composant SERVEUR : aucun JS embarqué pour un contrôle qui
 *   ne fait que recharger des chiffres ;
 * - une lecture est partageable par lien, ce qui compte pour un indicateur qu'on
 *   commente en revue ;
 * - l'année suit le même chemin, donc « T3 2025 » se rouvre à l'identique.
 *
 * L'année n'est proposée que sur les exercices pour lesquels le miroir porte des
 * commandes (`annees_disponibles`) : offrir 2018 sur un miroir qui commence en
 * 2019 afficherait un écran vide sans dire pourquoi.
 */
export function PeriodeNav({
  basePath,
  periode,
  annee,
  annees,
}: {
  /** Chemin de la section, p. ex. `/dc/vision/objectifs`. */
  basePath: string;
  periode: Periode;
  annee?: number;
  annees?: number[];
}) {
  const lien = (p: Periode, a?: number) => {
    const q = new URLSearchParams({ periode: p });
    if (a) q.set("annee", String(a));
    return `${basePath}?${q}`;
  };

  return (
    <div className="dc-seg-w">
      <span className="dc-seg-l">Cadence</span>
      <nav className="dc-seg" aria-label="Cadence de lecture">
        {PERIODES.map((p) => (
          <Link
            key={p.id}
            href={lien(p.id, annee)}
            aria-current={p.id === periode ? "page" : undefined}
            prefetch={false}
          >
            {p.label}
          </Link>
        ))}
      </nav>
      {annees && annees.length > 1 && (
        <>
          <span className="dc-seg-l" style={{ marginLeft: 14 }}>
            Exercice
          </span>
          <nav className="dc-seg" aria-label="Exercice">
            {annees.slice(0, 4).map((a) => (
              <Link
                key={a}
                href={lien(periode, a)}
                aria-current={a === annee ? "page" : undefined}
                prefetch={false}
              >
                {a}
              </Link>
            ))}
          </nav>
        </>
      )}
    </div>
  );
}
