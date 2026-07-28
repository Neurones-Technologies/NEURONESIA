import { ProfileKey } from "@/lib/types";

export interface SectionNavItem {
  id: string;
  label: string;
}

/** Découpage en sections de la vue Cockpit, par profil. Les `id` doivent
 * correspondre aux `<Section id=…>` de la vue correspondante : c'est sur eux
 * que le menu fait son scroll-spy. Défini ici (et non dans la vue) pour être
 * importable depuis l'en-tête, qui est un composant client. */
export const VISION_SECTIONS: Partial<Record<ProfileKey, readonly SectionNavItem[]>> = {
  dg: [
    { id: "tableau-de-bord", label: "Tableau de bord" },
    { id: "trajectoire", label: "Trajectoire financière" },
    { id: "risques", label: "Dépendances et risques" },
    { id: "copilote", label: "Copilote" },
  ],
};
