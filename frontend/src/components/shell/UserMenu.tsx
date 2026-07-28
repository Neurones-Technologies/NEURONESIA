"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { META } from "@/lib/data/profiles";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";

export function UserMenu({
  profile,
  code,
  fullName,
  roleLabel,
  isAdmin,
}: {
  profile: ProfileKey;
  code: string;
  fullName: string;
  roleLabel: string;
  isAdmin: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function logout() {
    setLoggingOut(true);
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  return (
    <div className="psel" ref={ref}>
      <button
        className="psel-btn"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      >
        <span className="psel-av">{code}</span>
        <span className="psel-txt">
          <b>{fullName}</b>
          <span>{roleLabel}</span>
        </span>
        <span className="psel-ch" aria-hidden="true">
          &#9662;
        </span>
      </button>
      <div className={`psel-menu${open ? " open" : ""}`} role="menu">
        {isAdmin && (
          <>
            <div className="ph">Aperçu profil (admin)</div>
            {PROFILE_KEYS.map((key) => {
              const m = META[key];
              return (
                <Link
                  key={key}
                  className="psel-item"
                  role="menuitem"
                  aria-current={key === profile}
                  href={`/${key}/vision`}
                  style={{ textDecoration: "none" }}
                  onClick={() => setOpen(false)}
                >
                  <span className="pi">{m.code}</span>
                  <span>
                    <b>{m.name}</b>
                    <span>{m.menuLabel}</span>
                  </span>
                </Link>
              );
            })}
            <div style={{ height: 1, background: "var(--line)", margin: "6px 0" }} />
          </>
        )}
        <button className="psel-item" role="menuitem" onClick={logout} disabled={loggingOut}>
          <span className="pi">&#9099;</span>
          <span>
            <b>Se déconnecter</b>
            <span>{fullName} · {roleLabel}</span>
          </span>
        </button>
      </div>
    </div>
  );
}
