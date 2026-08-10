"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { SectionNavItem, VisionNavMode } from "@/lib/data/sections";

export type { SectionNavItem };

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
}: {
  items: readonly SectionNavItem[];
  mode?: VisionNavMode;
  /** Mode `"route"` : préfixe des liens, p. ex. `/dc/vision`. */
  basePath?: string;
  /** Mode `"route"` : section active, lue depuis l'URL par l'appelant. */
  active?: string;
}) {
  if (mode === "route") {
    return (
      <nav className="hdr-nav" aria-label="Sections de la vue">
        {items.map((it) => (
          <Link
            key={it.id}
            href={`${basePath}/${it.id}`}
            className="hdr-nav-btn"
            aria-current={activeFromUrl === it.id ? "page" : undefined}
          >
            {it.label}
          </Link>
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
