"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [session12h, setSession12h] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [unsupported, setUnsupported] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setUnsupported(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || "Échec de connexion");
        return;
      }
      if (data.profile) {
        router.push(`/${data.profile}/vision`);
        return;
      }
      if (data.role === "admin") {
        router.push("/dg/vision");
        return;
      }
      setUnsupported(
        `Ce compte (${data.role}) n'est pas encore rattaché à un profil du cockpit. Déconnectez-vous et utilisez un compte DG, DC, DO, DF ou Account Manager.`
      );
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
            <b>5</b>
            <span>profils métier</span>
          </div>
          <div>
            <b>0</b>
            <span>donnée fictive</span>
          </div>
          <div>
            <b>Odoo</b>
            <span>miroir synchronisé</span>
          </div>
        </div>
      </div>
      <div className="auth-r">
        <div className="auth-box">
          <span className="auth-wm">
            Neurones Intelligence
            <span>Cockpit décisionnel · miroir Odoo</span>
          </span>
          <h2>Connexion</h2>
          <p className="sub">Authentifiez-vous avec votre compte Neurones.</p>

          {unsupported ? (
            <div>
              <p className="note" style={{ margin: "0 0 16px" }}>
                {unsupported}
              </p>
              <button
                className="bmain"
                type="button"
                onClick={async () => {
                  await fetch("/api/auth/logout", { method: "POST" });
                  setUnsupported(null);
                }}
              >
                Se déconnecter
              </button>
            </div>
          ) : (
            <form onSubmit={onSubmit}>
              <div className="fgrp">
                <label htmlFor="email">Email</label>
                <input
                  id="email"
                  type="email"
                  required
                  autoComplete="username"
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

              <div className="frow">
                <label className="chk">
                  <input type="checkbox" checked={session12h} onChange={(e) => setSession12h(e.target.checked)} />
                  Session de 12 h
                </label>
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
                Neurones Côte d&apos;Ivoire · exercice 2026
                <br />
                Accès réservé aux comptes Neurones habilités.
              </p>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
