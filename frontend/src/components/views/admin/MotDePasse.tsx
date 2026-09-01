"use client";

import { useId, useState } from "react";

/** Champ mot de passe avec bascule d'affichage.
 *
 * Un mot de passe posé par un administrateur POUR quelqu'un d'autre doit pouvoir
 * être relu avant envoi : il n'est plus lisible nulle part ensuite, et une faute
 * de frappe non détectée enferme la personne dehors sans que personne ne sache
 * quoi lui dire. La bascule est donc utile ici alors qu'elle est discutable sur
 * un formulaire de connexion.
 *
 * Réutilise `.pwdw` / `.reveal` (globals.css), écrits pour l'écran de connexion
 * et jusqu'ici les seuls de ce gabarit.
 */
export function MotDePasse({
  label,
  name,
  invalide,
  autoComplete = "new-password",
  style,
}: {
  label: string;
  name: string;
  invalide?: boolean;
  autoComplete?: string;
  style?: React.CSSProperties;
}) {
  const [visible, setVisible] = useState(false);
  const id = useId();

  return (
    <div className="fgrp" style={style}>
      <label htmlFor={id}>{label}</label>
      <div className="pwdw">
        <input
          id={id}
          name={name}
          type={visible ? "text" : "password"}
          required
          minLength={6}
          autoComplete={autoComplete}
          aria-invalid={invalide || undefined}
        />
        <button
          type="button"
          className="reveal"
          onClick={() => setVisible((v) => !v)}
          aria-pressed={visible}
        >
          {visible ? "masquer" : "afficher"}
        </button>
      </div>
    </div>
  );
}
