import { ReactNode } from "react";
import { Pays, paysDe } from "@/lib/data/pays";
import { PaysNav, PerimetreGroupe } from "../pays-nav";
import { DgTableauDeBord } from "./DgTableauDeBord";
import { DgTrajectoire } from "./DgTrajectoire";
import { DgPilotage } from "./DgPilotage";
import { DgFactures } from "./DgFactures";
import type { DcSectionParams } from "../dc";

/** Habille chaque onglet DG du sélecteur de pays (à l'extrémité droite de la
 * ligne d'en-tête). Le pays vit dans l'URL (`?pays=`, cf. lib/data/pays.ts)
 * comme les autres filtres du produit : les onglets restent des composants
 * serveur.
 *
 * Le pays ne ventile que le BRIEFING (onglet Tableau de bord). Les onglets sans
 * briefing sont entièrement au niveau groupe : le bandeau `PerimetreGroupe`
 * l'annonce en tête, quel que soit le pays choisi. */
function page(section: string, rendre: (pays: Pays) => ReactNode, avecBriefing = false) {
  return function rendu(params: DcSectionParams): ReactNode {
    const pays = paysDe(params.pays);
    return (
      <>
        <div className="dc-nav-row">
          <PaysNav basePath={`/dg/vision/${section}`} pays={pays} />
        </div>
        {avecBriefing ? null : <PerimetreGroupe pays={pays} />}
        {rendre(pays)}
      </>
    );
  };
}

/** Registre des onglets du cockpit DG : chaque clé est un segment d'URL
 * (`/dg/vision/<clé>`) et doit avoir son entrée dans `VISION_SECTIONS.dg`
 * (cf. lib/data/sections.ts) — sinon le menu affiche un onglet sans page, ou
 * l'inverse. La route valide le segment avant d'appeler ce registre.
 *
 * Issu du découpage de l'ancienne page unique DgVision (mode scroll) : chaque
 * onglet ne paie plus que ses propres appels API au lieu de tous les payer au
 * chargement. « Tableau de bord » reste la première section déclarée : c'est
 * elle qui porte le briefing du jour (cf. defaultVisionSection).
 *
 * Seul paramètre d'URL lu par les onglets DG : le pays (`?pays=`), via le
 * wrapper `page`. Seul le Tableau de bord le consomme (briefing par entité) ;
 * il pose lui-même le bandeau groupe sous le briefing, au-dessus des tuiles. */
export const DG_SECTIONS: Record<string, (params: DcSectionParams) => ReactNode> = {
  "tableau-de-bord": page("tableau-de-bord", (pays) => <DgTableauDeBord pays={pays} />, true),
  trajectoire: page("trajectoire", () => <DgTrajectoire />),
  pilotage: page("pilotage", () => <DgPilotage />),
  factures: page("factures", () => <DgFactures />),
};
