"use client";

import { ReactNode, useState } from "react";
import { Btn } from "@/components/ui/primitives";

/** Bascule de périmètre au-dessus de la file d'arbitrage.
 *
 * Le libellé dit « Mon périmètre » et non « Mes comptes » à dessein : le filtre
 * porte sur le RÔLE impliqué dans le dossier (mandat + positions citées), pas sur
 * le portefeuille de comptes de l'utilisateur — le miroir ne rattache pas les
 * dossiers d'arbitrage à un commercial nommé. Promettre « mes comptes » ferait
 * croire à tort qu'un compte absent de la liste est sans tension.
 *
 * Les lignes sont déjà rendues côté serveur avec un attribut `data-relevant`
 * (cf. `Clickable`) : cette bascule ne fait que poser `data-scope` sur son
 * conteneur, et le CSS masque les lignes hors périmètre. Aucune donnée n'est
 * recalculée ni refetchée au clic. */
export function ArbitrageScopeToggle({
  hasRelevant,
  perimeterLabel,
  children,
}: {
  /** Si aucun dossier n'est dans le périmètre du profil courant, on bascule par
   * défaut sur « Tous » plutôt que d'afficher une file vide sans explication. */
  hasRelevant: boolean;
  /** Rôle dont on montre le périmètre, ex. « Direction financière ». */
  perimeterLabel: string;
  children: ReactNode;
}) {
  const [showAll, setShowAll] = useState(!hasRelevant);

  return (
    <div data-scope={showAll ? "all" : "mine"}>
      <div className="acts" style={{ marginTop: 0, marginBottom: 6 }}>
        <Btn primary={!showAll} onClick={() => setShowAll(false)} disabled={!hasRelevant}>
          Mon périmètre
        </Btn>
        <Btn primary={showAll} onClick={() => setShowAll(true)}>
          Tous les dossiers
        </Btn>
      </div>
      <p style={{ fontSize: 11.5, color: "var(--t3)", fontStyle: "italic", margin: "0 0 14px" }}>
        {showAll
          ? "Tous les dossiers ouverts, quel que soit le profil concerné."
          : `Dossiers où ${perimeterLabel} est mandataire ou partie prenante. Filtre par rôle, pas par portefeuille de comptes : le miroir ne rattache pas un dossier d'arbitrage à un commercial nommé.`}
      </p>
      {children}
    </div>
  );
}
