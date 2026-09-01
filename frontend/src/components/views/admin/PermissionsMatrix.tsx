"use client";

import { useActionState } from "react";

import { resetPermissionsAction, setPermissionAction } from "@/lib/actions/admin";
import { ADMIN_IDLE } from "@/lib/actions/admin-state";
import type { PermissionMatrix } from "@/lib/api/admin";
import { ROLE_LABELS } from "@/lib/auth/roles";
import { moduleLabel } from "@/lib/data/modules";
import { ActionMessage, SubmitBtn } from "@/components/views/arbitrage/feedback";

/** Matrice module × rôle, éditable cellule par cellule.
 *
 * UN formulaire pour les ~70 cellules, et non un par cellule : chaque cellule est
 * un `<button type="submit" name="cell" value="module|rôle|cible">`, et l'action
 * découpe la valeur. Soixante-dix formulaires auraient voulu dire soixante-dix
 * `useActionState`, donc autant d'états d'attente et de bandeaux de retour à
 * l'écran — pour une matrice où l'on ne clique qu'une case à la fois.
 *
 * La valeur envoyée est l'état CIBLE calculé au rendu, pas une bascule : si un
 * autre administrateur modifie la matrice pendant que l'écran est ouvert, un
 * clic applique ce que la personne voit, pas l'inverse d'un état qu'elle ignore.
 *
 * La colonne « administrateur » est rendue en lecture seule, comme le backend
 * l'impose (400 explicite) : la montrer inerte vaut mieux que la masquer, sinon
 * on croit à un oubli de la matrice.
 */
export function PermissionsMatrix({
  profile,
  permissions,
}: {
  profile: string;
  permissions: PermissionMatrix;
}) {
  const [state, formAction, pending] = useActionState(setPermissionAction, ADMIN_IDLE);
  const [resetState, resetAction, resetPending] = useActionState(
    resetPermissionsAction,
    ADMIN_IDLE
  );

  const { roles, views, matrix } = permissions;

  return (
    <>
      <form action={formAction}>
        <input type="hidden" name="profile" value={profile} />
        <div style={{ overflowX: "auto" }}>
          <table className="mtx">
            <thead>
              <tr>
                <th>Module</th>
                {roles.map((role) => (
                  <th key={role} title={ROLE_LABELS[role] ?? role}>
                    {role === "admin" ? "admin" : role.replace("dir_", "")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {views.map((view) => (
                <tr key={view}>
                  <td>{moduleLabel(view)}</td>
                  {roles.map((role) => {
                    const ouvert = role === "admin" ? true : Boolean(matrix[view]?.[role]);
                    if (role === "admin") {
                      return (
                        <td key={role}>
                          <span
                            className="cell has"
                            title="L'administrateur a toujours accès à tout — droits non modifiables."
                          >
                            <span aria-hidden="true">✓</span>
                            <span className="sr-only">
                              {moduleLabel(view)} : toujours ouvert à l&apos;administrateur, non
                              modifiable
                            </span>
                          </span>
                        </td>
                      );
                    }
                    return (
                      <td key={role}>
                        <button
                          type="submit"
                          name="cell"
                          value={`${view}|${role}|${!ouvert}`}
                          className={`cell${ouvert ? " has" : ""}`}
                          disabled={pending}
                          aria-pressed={ouvert}
                          title={`${moduleLabel(view)} — ${ROLE_LABELS[role] ?? role} : ${
                            ouvert ? "cliquer pour retirer" : "cliquer pour autoriser"
                          }`}
                        >
                          <span aria-hidden="true">{ouvert ? "✓" : "·"}</span>
                          <span className="sr-only">
                            {ouvert ? "autorisé" : "refusé"} — {moduleLabel(view)} pour{" "}
                            {ROLE_LABELS[role] ?? role}
                          </span>
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ActionMessage state={state} />
      </form>

      <form action={resetAction}>
        <input type="hidden" name="profile" value={profile} />
        <ActionMessage state={resetState} />
        <div className="acts">
          <SubmitBtn
            pending={resetPending}
            primary={false}
            label="Revenir aux droits par défaut"
            pendingLabel="Réinitialisation…"
          />
          <span className="ro">
            Efface toutes les surcharges enregistrées. Les défauts vivent dans le code du backend
            (config/permissions.py), pas dans cet écran.
          </span>
        </div>
      </form>
    </>
  );
}
