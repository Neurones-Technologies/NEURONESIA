import Link from "next/link";
import { Pays, PAYS, PAYS_AVEC_DONNEES, paysLabel } from "@/lib/data/pays";
import { Bento, Tile } from "@/components/ui/bento";
import { Note } from "@/components/ui/primitives";

/** Sélecteur de pays — en tête de chaque page d'un cockpit.
 *
 * Monté aujourd'hui sur le seul cockpit DG ; il vit au niveau partagé parce que
 * le périmètre géographique n'est pas propre à un profil et sera étendu aux
 * autres cockpits quand leurs données le permettront.
 *
 * Des `<Link>` et non un `<select>`, pour les mêmes raisons que `PeriodeNav` : la
 * page reste un composant serveur, et un périmètre précis se partage par lien.
 *
 * La vue, la cadence et l'exercice sont reconduits dans chaque lien quand la page
 * en porte : changer de pays ne doit pas ramener sur l'onglet et le trimestre par
 * défaut. Le pays par défaut (Côte d'Ivoire) n'est pas écrit dans l'URL, qui reste
 * donc identique à celle d'avant l'existence du sélecteur. */
export function PaysNav({
  basePath,
  pays,
  vue,
  periode,
  annee,
}: {
  /** Chemin de la page, p. ex. `/dg/vision/tableau-de-bord`. */
  basePath: string;
  /** Pays actif. */
  pays: Pays;
  /** Vue interne à reconduire, quand elle n'est pas la première de la page. */
  vue?: string;
  periode?: string;
  annee?: number;
}) {
  const lien = (p: Pays) => {
    const q = new URLSearchParams();
    if (vue) q.set("vue", vue);
    if (p !== PAYS_AVEC_DONNEES) q.set("pays", p);
    if (periode) q.set("periode", periode);
    if (annee) q.set("annee", String(annee));
    const s = q.toString();
    return s ? `${basePath}?${s}` : basePath;
  };

  return (
    <div className="dc-seg-w">
      <span className="dc-seg-l">Pays</span>
      <nav className="dc-seg" aria-label="Pays">
        {PAYS.map((p) => (
          <Link
            key={p.id}
            href={lien(p.id)}
            aria-current={p.id === pays ? "page" : undefined}
            prefetch={false}
          >
            {p.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}

/** Écran de repli quand le pays sélectionné n'est pas encore raccordé au miroir
 * de données. Affiché À LA PLACE de la vue, pas en plus : des tuiles ivoiriennes
 * sous un sélecteur « Burkina Faso » se liraient comme des chiffres burkinabés. */
export function PaysIndisponible({ pays }: { pays: Pays }) {
  return (
    <Bento>
      <Tile span={12} title="Donnée non disponible">
        <Note style={{ marginTop: 0 }}>
          Les données de {paysLabel(pays)} ne sont pas encore raccordées au
          cockpit. Seule la Côte d&apos;Ivoire est disponible pour le moment.
        </Note>
      </Tile>
    </Bento>
  );
}
