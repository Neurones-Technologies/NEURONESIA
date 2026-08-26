"use client";

import { useActionState, useId, useState } from "react";

import { createUserAction } from "@/lib/actions/admin";
import { ADMIN_IDLE } from "@/lib/actions/admin-state";
import { ROLE_LABELS, roleToProfile } from "@/lib/auth/roles";
import { ActionMessage, SubmitBtn } from "@/components/views/arbitrage/feedback";
import { MotDePasse } from "@/components/views/admin/MotDePasse";

/** Création d'un compte, dans une modale (cf. `Modale`).
 *
 * Champs empilés et non sur une rangée : dans une modale, quatre champs côte à
 * côte se réduisent à des colonnes trop étroites pour une adresse e-mail.
 *
 * Le rôle est un choix EXPLICITE, sans valeur par défaut pré-sélectionnée : le
 * défaut du backend est `user`, un rôle sans cockpit dont le titulaire se
 * connecte pour n'arriver sur rien. Un formulaire qui le pré-remplirait
 * fabriquerait ce compte-là par simple inattention. L'écran annonce d'ailleurs
 * la conséquence dès que le rôle choisi n'a pas de cockpit.
 */
export function UserCreateForm({ profile, roles }: { profile: string; roles: string[] }) {
  const [state, formAction, pending] = useActionState(createUserAction, ADMIN_IDLE);
  const [role, setRole] = useState("");
  const emailId = useId();
  const nomId = useId();
  const roleId = useId();

  // `roles` vient du backend (`PERSONA_ROLES`) et porte les rôles à cockpit.
  // Les rôles hérités (`user`, `viewer`, `presale`) restent créables côté API,
  // mais cet écran ne les propose pas : ils n'ouvrent aucun écran du cockpit.
  const sansCockpit = Boolean(role) && role !== "admin" && !roleToProfile(role);

  return (
    <form action={formAction}>
      <input type="hidden" name="profile" value={profile} />

      <div>
        <div className="fgrp">
          <label htmlFor={emailId}>Adresse e-mail</label>
          <input
            id={emailId}
            name="email"
            type="email"
            required
            autoComplete="off"
            placeholder="prenom.nom@neuronestech.com"
            aria-invalid={state.field === "email" || undefined}
          />
        </div>

        <div className="fgrp">
          <label htmlFor={nomId}>Nom complet</label>
          <input
            id={nomId}
            name="full_name"
            type="text"
            required
            autoComplete="off"
            placeholder="Prénom Nom"
            aria-invalid={state.field === "full_name" || undefined}
          />
        </div>

        <div className="fgrp">
          <label htmlFor={roleId}>Rôle</label>
          <select
            id={roleId}
            name="role"
            required
            value={role}
            onChange={(e) => setRole(e.target.value)}
            aria-invalid={state.field === "role" || undefined}
          >
            <option value="">Choisir un rôle…</option>
            {roles.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r] ?? r}
              </option>
            ))}
          </select>
        </div>

        <MotDePasse
          label="Mot de passe initial"
          name="password"
          invalide={state.field === "password"}
        />
      </div>

      {sansCockpit && (
        <p className="foot-n">
          {ROLE_LABELS[role] ?? role} n&apos;a pas de cockpit : la connexion sera refusée faute
          d&apos;écran d&apos;accueil.
        </p>
      )}

      <ActionMessage state={state} />
      <div className="acts">
        <SubmitBtn
          pending={pending}
          label="Créer le compte"
          pendingLabel="Création…"
        />
      </div>
    </form>
  );
}
