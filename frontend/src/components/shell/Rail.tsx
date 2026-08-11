"use client";

import { useRouter, usePathname } from "next/navigation";
import { useState } from "react";
import { ProfileKey, SectionKey } from "@/lib/types";
import { visionEntryPath } from "@/lib/data/sections";
import { NavLink } from "./NavLink";

const RAIL_ITEMS: { key: SectionKey; label: string; href: (p: ProfileKey) => string; icon: React.ReactNode; adminOnly?: boolean }[] = [
  {
    key: "vision",
    label: "Cockpit",
    href: (p) => `/${p}/vision`,
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 4h7v6H4zM13 4h7v10h-7zM4 12h7v8H4zM13 16h7v4h-7z" />
      </svg>
    ),
  },
  {
    key: "copilot",
    label: "Copilote",
    href: (p) => `/${p}/copilot`,
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 3l1.9 4.9L19 9.8l-5.1 1.9L12 17l-1.9-5.3L5 9.8l5.1-1.9zM18 15.5l.9 2.3 2.1.8-2.1.8-.9 2.1-.9-2.1-2.1-.8 2.1-.8z" />
      </svg>
    ),
  },
  {
    key: "arbitrage",
    label: "Arbitrages",
    href: (p) => `/${p}/arbitrage`,
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 4v16M6 8h12M6 8l-3 6h6zM18 8l3 6h-6zM8 20h8" />
      </svg>
    ),
  },
  {
    key: "referentiel",
    label: "Données",
    href: (p) => `/${p}/referentiel`,
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <ellipse cx="12" cy="6" rx="7.5" ry="3" />
        <path d="M4.5 6v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6M4.5 12v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6" />
      </svg>
    ),
    // Effectif et fraîcheur bruts du miroir (`/v1/stats/mirror`) : une lecture
    // d'infrastructure, pas un module métier — réservée à l'administrateur.
    adminOnly: true,
  },
  {
    key: "params",
    label: "Réglages",
    href: (p) => `/${p}/params`,
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 7h10M18 7h2M4 12h4M12 12h8M4 17h9M17 17h3" />
        <circle cx="16" cy="7" r="2" />
        <circle cx="10" cy="12" r="2" />
        <circle cx="15" cy="17" r="2" />
      </svg>
    ),
  },
];

export function Rail({ profile, code, isAdmin }: { profile: ProfileKey; code: string; isAdmin: boolean }) {
  const pathname = usePathname();
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);
  const items = RAIL_ITEMS.filter((item) => !item.adminOnly || isAdmin);

  async function logout() {
    setLoggingOut(true);
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  return (
    <nav className="rail" aria-label="Navigation principale">
      <svg className="rail-mk" viewBox="0 0 40 40" aria-hidden="true">
        <circle cx="8.5" cy="20" r="3.3" fill="var(--accent-strong)" />
        <path d="M16.5 11.4a12.4 12.4 0 0 1 0 17.2" stroke="var(--accent-strong)" strokeWidth="2.3" fill="none" strokeLinecap="round" />
        <path d="M23.5 7a18.9 18.9 0 0 1 0 26" stroke="var(--accent-strong)" strokeWidth="2.3" fill="none" strokeLinecap="round" opacity=".7" />
        <path d="M30.5 2.8a25.4 25.4 0 0 1 0 34.4" stroke="var(--accent-strong)" strokeWidth="2.3" fill="none" strokeLinecap="round" opacity=".42" />
      </svg>
      {items.map((item) => {
        // `base` sert au surlignage, `href` à la navigation : pour un profil en
        // mode "route", le Cockpit pointe directement sur sa première section
        // (cf. visionEntryPath) alors que l'entrée doit rester allumée sur
        // TOUTES ses sections. Confondre les deux éteignait le rail dès qu'on
        // changeait d'onglet.
        const base = item.href(profile);
        const href = item.key === "vision" ? visionEntryPath(profile) : base;
        const current = pathname === base || pathname.startsWith(`${base}/`);
        return (
          <NavLink key={item.key} className="rl" aria-current={current} title={item.label} href={href}>
            {item.icon}
            {item.label}
          </NavLink>
        );
      })}
      <div className="rail-sp" />
      <button className="rail-av" title="Se déconnecter" onClick={logout} disabled={loggingOut}>
        {code}
      </button>
    </nav>
  );
}
