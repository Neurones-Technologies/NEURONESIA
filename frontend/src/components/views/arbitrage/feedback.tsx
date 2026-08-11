"use client";

import type { ArbitrageActionState } from "@/lib/actions/arbitrage-state";

/** Retour d'une action, à l'endroit exact où elle a été déclenchée.
 *
 * Sans lui, les formulaires de cet écran échouaient sans rien dire : le serveur
 * renvoyait un 403 de mandat ou un 422 de motif manquant, l'action l'avalait, la
 * page se rechargeait à l'identique. Le bandeau est en `aria-live` pour que le
 * lecteur d'écran l'annonce aussi. */
export function ActionMessage({ state }: { state: ArbitrageActionState }) {
  return (
    <p
      className={`arb-msg${state.status === "ok" ? " arb-msg--ok" : state.status === "error" ? " arb-msg--err" : ""}`}
      role="status"
      aria-live="polite"
      hidden={state.status === "idle"}
    >
      {state.message}
    </p>
  );
}

/** Bouton d'envoi qui dit ce qu'il fait pendant qu'il le fait. Les actions de cet
 * écran passent par le backend puis par une revalidation : une à trois secondes
 * pendant lesquelles un bouton inerte invite à double-cliquer. */
export function SubmitBtn({
  pending,
  label,
  pendingLabel,
  primary = true,
}: {
  pending: boolean;
  label: string;
  pendingLabel: string;
  primary?: boolean;
}) {
  return (
    <button type="submit" className={`btn${primary ? " btn--p" : ""}`} disabled={pending} aria-busy={pending}>
      {pending ? pendingLabel : label}
    </button>
  );
}
