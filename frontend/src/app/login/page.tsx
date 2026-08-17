"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { defaultTarget, safeNextPath } from "@/lib/auth/redirect";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!email.trim() || !password) {
      setError("Email et mot de passe sont requis.");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || "Échec de connexion");
        return;
      }
      // `?next=` est posé par le proxy quand une page protégée a été demandée
      // sans session (cf. src/proxy.ts) : on y retourne, sinon le cockpit du
      // profil renvoyé PAR LE BACKEND — jamais un profil choisi côté client.
      // Un `next` hors domaine ou pointant sur /login est écarté par
      // safeNextPath. Si la cible appartient à un autre profil, le layout
      // [profile] ramène de lui-même l'utilisateur sur le sien.
      // `profile` est null pour un admin (accès à tous les cockpits) → repli
      // sur « dg », comme la page racine.
      router.push(
        safeNextPath(searchParams.get("next")) ?? defaultTarget(data.profile ?? "dg")
      );
    } catch {
      setError("Service indisponible — réessayez dans un instant.");
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
          <p className="sub">Accès réservé aux comptes Neurones</p>

          <form onSubmit={onSubmit}>
            <div className="fgrp">
              <label htmlFor="email">Adresse email</label>
              <input
                id="email"
                type="email"
                required
                autoComplete="username"
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="prenom.nom@neuronestech.com"
              />
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

            <p className="frow" style={{ display: "block", fontSize: 13, color: "var(--t2)" }}>
              Session de 12 h. Mot de passe oublié : contactez un administrateur.
            </p>

            {error && (
              <p className="note" style={{ borderLeftColor: "var(--alert)", color: "var(--alert)", marginBottom: 18 }}>
                {error}
              </p>
            )}

            <button className="bmain" type="submit" disabled={loading}>
              {loading ? "Connexion…" : "Se connecter"}
            </button>
            <p className="auth-foot">
              Accès restreint aux personnes autorisées.
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
