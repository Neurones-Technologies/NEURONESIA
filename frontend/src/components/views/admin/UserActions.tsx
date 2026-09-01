"use client";

import { useActionState, useId, useState } from "react";

import {
  deleteUserAction,
  resetPasswordAction,
  toggleActiveAction,
  updateUserAction,
} from "@/lib/actions/admin";
import { ADMIN_IDLE } from "@/lib/actions/admin-state";
import type { UserDetail } from "@/lib/api/admin";
import { ROLE_LABELS } from "@/lib/auth/roles";
import { ActionMessage, SubmitBtn } from "@/components/views/arbitrage/feedback";
import { MotDePasse } from "@/components/views/admin/MotDePasse";

/** Les quatre gestes possibles sur un compte, en quatre formulaires distincts.
 *
 * Distincts et non réunis sous un bouton unique : chacun porte son propre
 * `useActionState`, donc son propre état d'attente et son propre message de
 * retour, posé sous le geste qui l'a produit. Réunis, changer un nom aurait
 * emporté une réinitialisation de mot de passe — et un seul bandeau aurait dû
 * parler pour quatre actions aux conséquences très inégales.
 *
 * Les garde-fous restent ceux du serveur (dernier administrateur actif,
 * auto-suppression). Ils sont ANNONCÉS ici avant le clic, ce qui est autre chose
 * que les appliquer : proposer un bouton dont on sait qu'il sera refusé n'aide
 * personne, et le message du refus reste celui du backend s'il survient quand
 * même (deux onglets, deux administrateurs).
 *
 * Ces avertissements sont le SEUL texte conservé, et ils sont conditionnels :
 * ils portent une conséquence qu'aucun champ ne dit, et n'apparaissent qu'au
 * moment où elle devient vraie. Les commentaires permanents qui décrivaient les
 * gestes ont été retirés — dans une modale, ils repoussent hors de vue les
 * champs qu'on est venu remplir.
 */
export function UserActions({
  profile,
  compte,
  roles,
  adminsActifs,
  perimetreAdmin,
}: {
  profile: string;
  compte: UserDetail["compte"];
  /** Rôles proposables, tels que le backend les déclare (`PERSONA_ROLES`). */
  roles: string[];
  adminsActifs: number;
  perimetreAdmin: boolean;
}) {
  const [identite, identiteAction, identitePending] = useActionState(updateUserAction, ADMIN_IDLE);
  const [statut, statutAction, statutPending] = useActionState(toggleActiveAction, ADMIN_IDLE);
  const [motDePasse, motDePasseAction, motDePassePending] = useActionState(
    resetPasswordAction,
    ADMIN_IDLE
  );
  const [suppression, suppressionAction, suppressionPending] = useActionState(
    deleteUserAction,
    ADMIN_IDLE
  );

  const emailId = useId();
  const nomId = useId();
  const roleId = useId();
  const confirmId = useId();
  const [role, setRole] = useState(compte.role);
  const [confirmation, setConfirmation] = useState("");

  // Le dernier administrateur actif ne peut être ni rétrogradé ni désactivé : le
  // serveur refuse (409), sinon plus personne ne pourrait administrer.
  const dernierAdmin = compte.role === "admin" && compte.is_active && adminsActifs <= 1;
  const perdSonAdmin = dernierAdmin && role !== "admin";

  return (
    <>
      {/* ── Identité et rôle ── */}
      <form action={identiteAction}>
        <input type="hidden" name="profile" value={profile} />
        <input type="hidden" name="user_id" value={compte.id} />

        <p className="mini-l">Identité et rôle</p>
        <div className="fgrp">
          <label htmlFor={emailId}>Adresse e-mail</label>
          <input
            id={emailId}
            name="email"
            type="email"
            required
            defaultValue={compte.email}
            aria-invalid={identite.field === "email" || undefined}
          />
        </div>
        <div className="fgrp">
          <label htmlFor={nomId}>Nom complet</label>
          <input
            id={nomId}
            name="full_name"
            type="text"
            required
            defaultValue={compte.full_name}
            aria-invalid={identite.field === "full_name" || undefined}
          />
        </div>
        <div className="fgrp">
          <label htmlFor={roleId}>Rôle</label>
          <select
            id={roleId}
            name="role"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            aria-invalid={identite.field === "role" || undefined}
          >
            {/* Le rôle actuel figure toujours dans la liste, même hérité
                (`user`, `viewer`, `presale`) : sans lui, un simple
                enregistrement de nom l'aurait changé. */}
            {(roles.includes(compte.role) ? roles : [compte.role, ...roles]).map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r] ?? r}
              </option>
            ))}
          </select>
        </div>

        {compte.est_moi && role !== compte.role && (
          <p className="foot-n">
            C&apos;est votre compte : en changeant votre rôle, vous perdez l&apos;accès à cet écran
            dès la requête suivante.
          </p>
        )}
        {perdSonAdmin && (
          <p className="foot-n">
            C&apos;est le dernier administrateur actif : le serveur refusera de le rétrograder.
            Créez ou réactivez un autre administrateur d&apos;abord.
          </p>
        )}

        <ActionMessage state={identite} />
        <div className="acts">
          <SubmitBtn
            pending={identitePending}
            label="Enregistrer"
            pendingLabel="Enregistrement…"
          />
        </div>
      </form>

      {/* ── Statut ── */}
      <form action={statutAction}>
        <input type="hidden" name="profile" value={profile} />
        <input type="hidden" name="user_id" value={compte.id} />
        <input type="hidden" name="email" value={compte.email} />
        <input type="hidden" name="is_active" value={String(!compte.is_active)} />

        <p className="mini-l">Accès</p>
        <div className="fld">
          <div>
            <div className="fld-n">
              {compte.is_active ? "Retirer l'accès" : "Rendre l'accès"}
            </div>
            <div className="fld-s">
              {compte.is_active
                ? "Traces conservées, connexion refusée."
                : "Mot de passe actuel inchangé."}
            </div>
          </div>
          <SubmitBtn
            pending={statutPending}
            primary={false}
            label={compte.is_active ? "Désactiver" : "Réactiver"}
            pendingLabel="…"
          />
        </div>
        {dernierAdmin && (
          <p className="foot-n">
            Dernier administrateur actif : le serveur refusera la désactivation.
          </p>
        )}
        <ActionMessage state={statut} />
      </form>

      {/* ── Mot de passe ── */}
      <form action={motDePasseAction}>
        <input type="hidden" name="profile" value={profile} />
        <input type="hidden" name="user_id" value={compte.id} />

        <p className="mini-l">Mot de passe</p>
        <MotDePasse
          label="Nouveau mot de passe"
          name="password"
          invalide={motDePasse.field === "password"}
        />
        <MotDePasse
          label="Confirmer"
          name="password_confirm"
          invalide={motDePasse.field === "password_confirm"}
        />
        <ActionMessage state={motDePasse} />
        <div className="acts">
          <SubmitBtn
            pending={motDePassePending}
            primary={false}
            label="Réinitialiser le mot de passe"
            pendingLabel="Réinitialisation…"
          />
        </div>
      </form>

      {/* ── Suppression ── */}
      {compte.est_moi ? (
        <p className="foot-n">
          Vous ne pouvez pas supprimer votre propre compte — le serveur le refuse.
        </p>
      ) : (
        <form action={suppressionAction}>
          <input type="hidden" name="profile" value={profile} />
          <input type="hidden" name="user_id" value={compte.id} />
          <input type="hidden" name="email" value={compte.email} />

          <p className="mini-l">Suppression</p>
          <p className="foot-n" style={{ margin: "0 0 14px" }}>
            Irréversible. Préférez la désactivation si l&apos;accès doit seulement cesser.
          </p>
          <div className="fgrp">
            <label htmlFor={confirmId}>Recopier {compte.email}</label>
            <input
              id={confirmId}
              name="confirmation"
              type="text"
              autoComplete="off"
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
              aria-invalid={suppression.field === "confirmation" || undefined}
            />
          </div>
          {perimetreAdmin && (
            <p className="foot-n">Ce compte est administrateur.</p>
          )}
          <ActionMessage state={suppression} />
          <div className="acts">
            <button
              type="submit"
              className="btn"
              disabled={
                suppressionPending ||
                confirmation.trim().toLowerCase() !== compte.email.toLowerCase()
              }
              aria-busy={suppressionPending}
            >
              {suppressionPending ? "Suppression…" : "Supprimer définitivement"}
            </button>
          </div>
        </form>
      )}
    </>
  );
}
