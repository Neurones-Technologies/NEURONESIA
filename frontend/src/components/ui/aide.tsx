"use client";

import { ReactNode } from "react";

/** Infobulle « ? » accolée au titre d'un bloc : ce que le bloc dit, en langage
 * d'usage.
 *
 * Elle répond à « c'est quoi, ce bloc ? » — PAS à « d'où sort ce chiffre ? »,
 * qui est le rôle du tiroir de détail (cf. ui/detail.tsx). Les deux niveaux se
 * complètent et ne se recouvrent pas :
 *
 * - le « ? » survolé donne une phrase de sens, lisible par quelqu'un qui ouvre
 *   le cockpit pour la première fois ;
 * - la tuile cliquée donne les chiffres corroborants et leur provenance.
 *
 * Écrire le texte : une à deux phrases, sujet + verbe, au présent. Ce que le
 * lecteur y gagne, pas la mécanique de calcul — « ce qui a été commandé depuis
 * le 1er janvier » et non « somme des sale.order en état sale/done ». Pas de
 * nom de table, pas de nom d'endpoint, pas de sigle non développé.
 *
 * L'AFFICHAGE ne coûte pas de JavaScript : montrer/masquer est fait en CSS
 * (`:hover`/`:focus-visible`), sans état ni bibliothèque, donc l'aide est
 * consultable avant toute hydratation. C'est aussi ce qui la rend atteignable au
 * clavier — un `title=""` natif ne l'est pas, et c'était la raison de ne pas
 * s'en contenter.
 *
 * Le composant est néanmoins client, pour une seule raison : une StatTile
 * pourvue d'un `detail` est enveloppée dans `Clickable`, dont le `onClick` est
 * posé sur le conteneur (cf. ui/detail.tsx). Sans `stopPropagation`, cliquer le
 * « ? » ouvrirait le tiroir — soit exactement la confusion entre les deux
 * niveaux que ce composant existe pour éviter.
 *
 * Le bouton porte `aria-label` (« Aide : … ») plutôt que le seul « ? », qui ne
 * dit rien hors contexte au lecteur d'écran. Le texte lui-même est dans un
 * `role="tooltip"` lié par `aria-describedby`. */
export function Aide({ children, id }: { children: ReactNode; id: string }) {
  const tid = `aide-${id}`;
  return (
    <span className="aide">
      <button
        type="button"
        className="aide-b"
        aria-describedby={tid}
        aria-label="Aide : à quoi sert ce bloc"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
        onKeyDown={(e) => {
          // `Clickable` ouvre le tiroir sur Entrée/Espace : sans cette bride, la
          // touche traverserait le « ? » focalisé et ouvrirait la fiche.
          if (e.key === "Enter" || e.key === " ") e.stopPropagation();
        }}
      >
        ?
      </button>
      <span className="aide-t" role="tooltip" id={tid}>
        {children}
      </span>
    </span>
  );
}
