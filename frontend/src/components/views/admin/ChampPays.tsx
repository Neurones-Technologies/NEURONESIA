"use client";

import { useId, useState } from "react";

import { ROLE_LABELS } from "@/lib/auth/roles";
import { libellePaysCompte, PAYS_COMPTE, ROLES_TOUJOURS_GROUPE } from "@/lib/data/pays";

/** Champ « Pays » des formulaires de compte (création et modification).
 *
 * Le pays d'un compte est un périmètre IMPOSÉ : toutes ses pages sont limitées à
 * l'entité choisie, côté serveur. « Groupe » = tous pays, avec un sélecteur
 * libre. Le DG et l'admin sont toujours rattachés au groupe : le champ est alors
 * verrouillé, et le serveur refuserait de toute façon un pays sur ces comptes.
 *
 * `role` est le rôle EN COURS de saisie (pas celui enregistré) : choisir « DG »
 * dans le formulaire verrouille le champ immédiatement, avant l'envoi.
 */
export function ChampPays({
  role,
  defaut = "",
  invalide = false,
}: {
  role: string;
  defaut?: string;
  invalide?: boolean;
}) {
  const id = useId();
  const [pays, setPays] = useState((defaut ?? "").toUpperCase());
  const verrouille = ROLES_TOUJOURS_GROUPE.includes(role);
  const valeur = verrouille ? "" : pays;

  return (
    <div className="fgrp">
      <label htmlFor={id}>Pays</label>
      <select
        id={id}
        name="pays"
        value={valeur}
        disabled={verrouille}
        onChange={(e) => setPays(e.target.value)}
        aria-invalid={invalide || undefined}
      >
        {PAYS_COMPTE.map((p) => (
          <option key={p.code || "groupe"} value={p.code}>
            {p.label}
          </option>
        ))}
      </select>
      {/* Un <select> désactivé n'est pas envoyé : la valeur « groupe » l'est quand même. */}
      {verrouille && <input type="hidden" name="pays" value="" />}
      <p className="foot-n">
        {verrouille
          ? `Un compte ${ROLE_LABELS[role] ?? role} est toujours rattaché au groupe : il voit tous les pays.`
          : valeur
            ? `Toutes les pages de ce compte seront limitées à ${libellePaysCompte(valeur)}, sans possibilité d'en changer.`
            : "Groupe : le compte voit tous les pays et choisit librement son périmètre."}
      </p>
    </div>
  );
}
