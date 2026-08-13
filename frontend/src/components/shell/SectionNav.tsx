"use client";

import { useEffect, useState } from "react";
import { SectionGroup, SectionNavItem, VisionNavMode } from "@/lib/data/sections";
import { NavLink } from "./NavLink";

export type { SectionNavItem };

/** Niveau 1 d'un menu à deux niveaux : les chapitres.
 *
 * Un clic sur un chapitre mène à sa PREMIÈRE section — un chapitre n'est pas une
 * page, seulement un regroupement. `href` est donc calculé par l'appelant, qui
 * seul connaît la liste des sections.
 *
 * L'état actif se déduit du chapitre de la section courante, jamais de l'URL
 * directement : une section peut être atteinte par lien direct sans passer par son
 * chapitre, et le surlignage doit suivre quand même. */
export function GroupNav({
  groups,
  active,
  hrefOf,
  eager = true,
}: {
  groups: readonly SectionGroup[];
  active: string | undefined;
  hrefOf: (group: SectionGroup) => string;
  eager?: boolean;
}) {
  return (
    <nav className="hdr-nav" aria-label="Chapitres de la vue">
      {groups.map((g) => (
        <NavLink
          key={g.id}
          href={hrefOf(g)}
          className="hdr-nav-btn"
          title={g.title}
          eager={eager}
          aria-current={active === g.id ? "page" : undefined}
        >
          {g.label}
        </NavLink>
      ))}
    </nav>
  );
}

/** Menu de sections de l'en-tête. Deux modes (cf. lib/data/sections.ts) :
 *
 * - `"scroll"` : les sections sont toutes dans la page, le menu défile jusqu'à
 *   l'ancre et surligne celle qui est à l'écran (IntersectionObserver).
 * - `"route"` : chaque section est une page, le menu rend des <Link> et
 *   surligne d'après l'URL. Pas d'observer — il n'y a qu'une section montée. */
export function SectionNav({
  items,
  mode = "scroll",
  basePath,
  active: activeFromUrl,
  variant = "primary",
  eager = true,
}: {
  items: readonly SectionNavItem[];
  mode?: VisionNavMode;
  /** Mode `"route"` : préfixe des liens, p. ex. `/dc/vision`. */
  basePath?: string;
  /** Mode `"route"` : section active, lue depuis l'URL par l'appelant. */
  active?: string;
  /** `"sub"` : rangée de niveau 2, sous les chapitres. Même comportement, dessin
   * plus discret — deux rangées d'onglets de même poids se disputeraient la
   * lecture et on ne saurait plus laquelle commande l'autre. */
  variant?: "primary" | "sub";
  eager?: boolean;
}) {
  if (mode === "route") {
    return (
      <nav
        className={variant === "sub" ? "hdr-subnav" : "hdr-nav"}
        aria-label={variant === "sub" ? "Écrans du chapitre" : "Sections de la vue"}
      >
        {items.map((it) => (
          <NavLink
            key={it.id}
            href={`${basePath}/${it.id}`}
            className={variant === "sub" ? "hdr-subnav-btn" : "hdr-nav-btn"}
            eager={eager}
            aria-current={activeFromUrl === it.id ? "page" : undefined}
          >
            {it.label}
          </NavLink>
        ))}
      </nav>
    );
  }

  return <ScrollSpyNav items={items} />;
}

function ScrollSpyNav({ items }: { items: readonly SectionNavItem[] }) {
  const [active, setActive] = useState(items[0]?.id);

  useEffect(() => {
    const elements = items
      .map((it) => document.getElementById(it.id))
      .filter((el): el is HTMLElement => el !== null);

    if (elements.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting);
        if (visible.length === 0) return;
        const topMost = visible.reduce((a, b) =>
          a.boundingClientRect.top < b.boundingClientRect.top ? a : b
        );
        setActive(topMost.target.id);
      },
      { rootMargin: "-90px 0px -70% 0px", threshold: 0 }
    );

    elements.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [items]);

  function goTo(id: string) {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
    setActive(id);
  }

  return (
    <nav className="hdr-nav" aria-label="Sections de la vue">
      {items.map((it) => (
        <button
          key={it.id}
          type="button"
          className="hdr-nav-btn"
          aria-current={active === it.id}
          onClick={() => goTo(it.id)}
        >
          {it.label}
        </button>
      ))}
    </nav>
  );
}
