"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ProfileKey } from "@/lib/types";
import { ROLE_LABELS } from "@/lib/auth/roles";
import { defaultTarget, safeNextPath } from "@/lib/auth/redirect";

// Mot de passe des comptes démo — doit rester aligné sur DEMO_USERS_PASSWORD
// dans backend/scripts/seed_demo_users.py (défaut "neurones2026" si non surchargé).
const DEMO_PASSWORD = "neurones2026";

type DemoProfile = {
  key: ProfileKey;
  code: string;
  label: string;
  fullName: string;
  email: string;
  badge: string;
};

const PROFILES: DemoProfile[] = [
  {
    key: "dg",
    code: "DG",
    label: "Direction générale — arbitrage & atterrissage",
    fullName: "Direction Generale",
    email: "jmkouadio@neuronestech.com",
    badge: ROLE_LABELS.dg,
  },
  {
    key: "dc",
    code: "DC",
    label: "Direction commerciale — pipeline & forecast",
    fullName: "Direction Commerciale",
    email: "pbourron@neuronestech.com",
    badge: ROLE_LABELS.dir_commercial,
  },
  {
    key: "do",
    code: "DO",
    label: "Direction des opérations — backlog & visibilité",
    fullName: "Direction des Operations",
    email: "pyoro@neuronestech.com",
    badge: ROLE_LABELS.dir_operations,
  },
  {
    key: "df",
    code: "DF",
    label: "Direction financière — encaissement & marge",
    fullName: "Direction Financiere",
    email: "cdjereke@neuronestech.com",
    badge: ROLE_LABELS.dir_financier,
  },
  {
    key: "am",
    code: "AM",
    label: "Account manager — portefeuille & alertes",
    fullName: "Commercial",
    email: "sales@neuronestech.com",
    badge: ROLE_LABELS.commercial,
  },
];

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [profileKey, setProfileKey] = useState<ProfileKey>("dg");
  const [password, setPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [session12h, setSession12h] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const current = PROFILES.find((p) => p.key === profileKey) ?? PROFILES[0];

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!password.trim()) {
      setError("Le mot de passe est requis.");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: current.email, password: DEMO_PASSWORD }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || "Échec de connexion");
        return;
      }
      // `?next=` est posé par le proxy quand une page protégée a été demandée
      // sans session (cf. src/proxy.ts) : on y retourne, sinon cockpit du profil.
      // Un `next` hors domaine ou pointant sur /login est écarté par
      // safeNextPath. Si la cible appartient à un autre profil, le layout
      // [profile] ramène de lui-même l'utilisateur sur le sien.
      router.push(safeNextPath(searchParams.get("next")) ?? defaultTarget(profileKey));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth">
      <div className="auth-l">
        <p className="auth-kick">
          <span className="dot" />
          Neurones · plateforme décisionnelle
        </p>
        <div>
          <h1>
            Décider sur des <em>signaux</em>, pas sur des tableaux.
          </h1>
          <p>
            Le cockpit relit le miroir Odoo, isole ce qui a bougé et pose l&apos;arbitrage sur la table. La décision reste
            la vôtre.
          </p>
        </div>
        <div className="auth-meta">
          <div>
            <b>04:12</b>
            <span>Instantané quotidien</span>
          </div>
          <div>
            <b>147</b>
            <span>Comptes suivis</span>
          </div>
          <div>
            <b>5</b>
            <span>Profils métier</span>
          </div>
        </div>
      </div>
      <div className="auth-r">
        <div className="auth-box">
          <img src="/logo.png" alt="Neurones" className="auth-logo" />
          <h2>Connexion</h2>
          <p className="sub">Authentification unique Odoo · second facteur actif</p>

          <form onSubmit={onSubmit}>
            <div className="fgrp">
              <label htmlFor="profile">Profil d&apos;accès</label>
              <select
                id="profile"
                value={profileKey}
                onChange={(e) => setProfileKey(e.target.value as ProfileKey)}
              >
                {PROFILES.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="auth-persona">
              <span className="psel-av">{current.code}</span>
              <span className="psel-txt">
                <b>{current.fullName}</b>
                <span>{current.email}</span>
              </span>
              <span className="tag tag--a">{current.badge}</span>
            </div>

            <div className="fgrp">
              <label htmlFor="password">Mot de passe</label>
              <div className="pwdw">
                <input
                  id="password"
                  type={showPwd ? "text" : "password"}
                  required
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                />
                <button
                  className="reveal"
                  type="button"
                  aria-pressed={showPwd}
                  onClick={() => setShowPwd((v) => !v)}
                >
                  {showPwd ? "Masquer" : "Afficher"}
                </button>
              </div>
            </div>

            <div className="frow">
              <label className="chk">
                <input type="checkbox" checked={session12h} onChange={(e) => setSession12h(e.target.checked)} />
                Session de 12 h
              </label>
              <a href="#" onClick={(e) => e.preventDefault()}>
                Mot de passe oublié
              </a>
            </div>

            {error && (
              <p className="note" style={{ borderLeftColor: "var(--alert)", color: "var(--alert)", marginBottom: 18 }}>
                {error}
              </p>
            )}

            <button className="bmain" type="submit" disabled={loading}>
              {loading ? "Connexion…" : "Se connecter"}
            </button>
            <p className="auth-foot">
              Maquette de démonstration — aucune donnée réelle.
              <br />
              Neurones Côte d&apos;Ivoire · exercice 2026
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}

// useSearchParams() suspend au pré-rendu : sans cette frontière, `next build`
// échoue sur /login (missing-suspense-with-csr-bailout).
export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
