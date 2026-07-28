"use client";

import { useEffect, useState } from "react";
import { SectionNavItem } from "@/lib/data/sections";

export type { SectionNavItem };

export function SectionNav({ items }: { items: readonly SectionNavItem[] }) {
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
