import Link from "next/link";
import { SectionVue } from "@/lib/data/sections";

/** Onglets internes d'une page — second niveau de navigation, dans la page.
 *
 * Sept pages portent les quatorze écrans du cockpit DC. Ces onglets sont ce qui
 * permet de les regrouper SANS rien retirer : chaque vue garde son contenu
 * intégral, et l'URL la désigne par `?vue=`.
 *
 * Des `<Link>` et non des boutons, pour les mêmes raisons que `PeriodeNav` : la
 * page reste un composant serveur, et une vue précise se partage par lien.
 *
 * La cadence et l'exercice sont reconduits dans chaque lien : changer d'onglet en
 * perdant le trimestre sélectionné obligerait à le repositionner à chaque fois,
 * alors que les trois vues d'« Objectifs et performance » se lisent justement à la
 * même cadence. */
export function VueNav({
  basePath,
  vues,
  vue,
  periode,
  annee,
}: {
  /** Chemin de la page, p. ex. `/dc/vision/objectifs`. */
  basePath: string;
  vues: readonly SectionVue[];
  /** Vue active. */
  vue: string;
  periode?: string;
  annee?: number;
}) {
  if (vues.length < 2) return null;

  const lien = (id: string) => {
    const q = new URLSearchParams();
    // La première vue est le défaut de la page : ne pas l'écrire dans l'URL garde
    // le lien court et fait de `/dc/vision/portefeuille` une adresse stable.
    if (id !== vues[0].id) q.set("vue", id);
    if (periode) q.set("periode", periode);
    if (annee) q.set("annee", String(annee));
    const s = q.toString();
    return s ? `${basePath}?${s}` : basePath;
  };

  return (
    <nav className="vue-nav" aria-label="Vues de la page">
      {vues.map((v) => (
        <Link key={v.id} href={lien(v.id)} aria-current={v.id === vue ? "page" : undefined}>
          {v.label}
        </Link>
      ))}
    </nav>
  );
}
