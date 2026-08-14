"use client";

import { useId, useState, ReactNode } from "react";

/** Repli d'une liste longue : les `visibles` premières lignes, puis une bascule
 * « Voir les N autres » / « Voir moins ».
 *
 * Les vues sont des Server Components et ne peuvent pas porter d'état ; ce
 * wrapper client reçoit les lignes DÉJÀ RENDUES (`ReactNode[]`) et se contente
 * de masquer la queue. Le rendu du contenu reste donc côté serveur — seule la
 * décision d'afficher ou non passe au client.
 *
 * Pourquoi masquer plutôt que ne pas rendre : les lignes repliées existent dans
 * le document dès le premier rendu. Le déplié est instantané, et `hidden` les
 * retire de l'arbre d'accessibilité tant qu'elles sont repliées — le lecteur
 * d'écran annonce donc le même nombre de lignes que ce que l'œil voit.
 *
 * Le conteneur de la queue est en `display:contents` : `.lst` est une grille et
 * ses lignes doivent en rester les enfants directs. Un `<div>` ordinaire aurait
 * empilé toute la queue dans une seule cellule, désalignant les colonnes
 * (numéro, libellé, étiquette) des lignes dépliées. */
export function LstRepli({
  lignes,
  visibles,
  /** Nom des lignes au pluriel, pour le libellé : « Voir les 8 autres affaires ». */
  nom = "lignes",
}: {
  lignes: ReactNode[];
  visibles: number;
  nom?: string;
}) {
  const [ouvert, setOuvert] = useState(false);
  const idQueue = useId();

  const tete = lignes.slice(0, visibles);
  const queue = lignes.slice(visibles);

  // Liste plus courte que le seuil : pas de bascule à proposer.
  if (queue.length === 0) return <>{lignes}</>;

  return (
    <>
      {tete}
      {/* La queue reste montée : cf. commentaire du composant. */}
      <div id={idQueue} hidden={!ouvert} className="lst-queue">
        {queue}
      </div>
      <button
        type="button"
        className="lst-plus"
        onClick={() => setOuvert((o) => !o)}
        aria-expanded={ouvert}
        aria-controls={idQueue}
      >
        {ouvert ? "Voir moins" : `Voir les ${queue.length} autres ${nom}`}
      </button>
    </>
  );
}
