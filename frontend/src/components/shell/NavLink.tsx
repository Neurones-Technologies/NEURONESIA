"use client";

import Link, { useLinkStatus } from "next/link";
import type { ComponentProps } from "react";

type NavLinkProps = Omit<ComponentProps<typeof Link>, "prefetch">;

/** Barre d'attente du lien cliqué. `useLinkStatus` n'est lisible que dans un
 * descendant du `<Link>` — d'où ce composant plutôt qu'un état porté par
 * `NavLink` lui-même.
 *
 * Le retard d'apparition est dans la CSS (`.nav-busy`, globals.css) et non ici :
 * monter puis démonter l'élément en 60 ms ne coûte rien, alors qu'un `setTimeout`
 * de garde en JS rajouterait un rendu et un nettoyage à chaque clic. */
function NavPending() {
  const { pending } = useLinkStatus();
  return pending ? <span className="nav-busy" aria-hidden="true" /> : null;
}

/** Lien de navigation du cockpit — route complète préchargée, sans attendre
 * d'intention.
 *
 * `prefetch={true}` est nécessaire ici : nos routes sont toutes dynamiques, et
 * pour celles-là le prefetch par défaut est « ignoré, ou partiel si un
 * `loading.tsx` est présent » (doc Next, linking-and-navigating). Comme les
 * `loading.tsx` de route ont été retirés, le défaut ne prépare plus rien du tout.
 *
 * Une première version n'armait ce prefetch qu'au survol, pour épargner au
 * backend des rendus spéculatifs. Mesuré au navigateur, c'était le mauvais
 * arbitrage : un clic sans survol préalable — tactile, pointeur rapide, premier
 * clic sur une page fraîche — restait 363 ms sans aucun retour visuel, contre
 * 56 ms avec le prefetch abouti et 32 ms sur un onglet déjà visité. Sans
 * `loading.tsx` pour occuper l'attente, ces 363 ms se lisent comme une
 * application qui ne répond pas.
 *
 * Le coût côté serveur est assumé : le jeu de liens est fixe et petit (4 onglets
 * de section, 5 entrées de rail), chaque rendu vaut 14 à 270 ms de lectures SQL
 * bon marché, et `staleTimes.static` les garde réutilisables 5 min
 * (next.config.ts). Si un jour un menu devient une longue liste, c'est là qu'il
 * faudra revenir à un armement au survol — pas pour une barre de navigation.
 *
 * Le prefetch ne couvre pas tout : premier clic sur une page fraîche, préchargement
 * encore en vol, cache routeur expiré, réseau du VPS. Dans ces cas le clic reste
 * sans réponse le temps du rendu serveur — et il n'y a plus de `loading.tsx` pour
 * l'occuper. `NavPending` marque alors l'onglet cliqué. */
export function NavLink({ children, ...props }: NavLinkProps) {
  return (
    <Link {...props} prefetch>
      {children}
      <NavPending />
    </Link>
  );
}
