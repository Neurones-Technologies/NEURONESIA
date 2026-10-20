"use client";

import { useRouter } from "next/navigation";
import { useId, useTransition } from "react";

import { choisirPaysAction } from "@/lib/actions/pays";
import { libellePaysCompte, PAYS_COMPTE, ROLES_TOUJOURS_GROUPE } from "@/lib/data/pays";

/** Périmètre pays de la session, dans l'en-tête de TOUS les cockpits.
 *
 * - Compte rattaché à un pays : badge non modifiable — le pays est imposé par
 *   l'administrateur et appliqué côté serveur à toutes les pages.
 * - Compte groupe : sélecteur Groupe / CI / BF / GN, mémorisé (cookie) et
 *   transmis à chaque appel.
 * - DG et admin : rien ici — toujours groupe (le cockpit DG garde son propre
 *   sélecteur, qui ne ventile que son briefing).
 */
export function PerimetreBar({
  role,
  perimetre,
  verrouille,
}: {
  role: string;
  /** Pays appliqué à la requête (CI / BF / GN), `null` = groupe. */
  perimetre: string | null;
  verrouille: boolean;
}) {
  const router = useRouter();
  const id = useId();
  const [pending, startTransition] = useTransition();

  if (ROLES_TOUJOURS_GROUPE.includes(role)) return null;

  if (verrouille) {
    return (
      <span className="chip" title="Périmètre défini par l'administrateur pour ce compte">
        Pays : {libellePaysCompte(perimetre)} · verrouillé
      </span>
    );
  }

  return (
    <label htmlFor={id} className="chip" style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
      Pays
      <select
        id={id}
        value={perimetre ?? ""}
        disabled={pending}
        onChange={(e) => {
          const valeur = e.target.value;
          startTransition(async () => {
            await choisirPaysAction(valeur);
            router.refresh();
          });
        }}
      >
        {PAYS_COMPTE.map((p) => (
          <option key={p.code || "groupe"} value={p.code}>
            {p.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Rappel affiché sous l'en-tête dès qu'un pays est appliqué. Il dit exactement
 * ce que le serveur fait : les données rattachées à un pays sont filtrées ; les
 * indicateurs qui dépendraient de données SANS pays ne sont pas calculés pour
 * le pays (DPO, variations « vs hier », éléments retirés du briefing). */
export function PerimetreRappel({ perimetre }: { perimetre: string | null }) {
  if (!perimetre) return null;
  return (
    <p className="note" style={{ margin: "8px 24px 0" }}>
      Périmètre <strong>{libellePaysCompte(perimetre)}</strong> : commandes, factures, créances,
      dossiers, achats et opportunités sont limités à ce pays. Les indicateurs qui reposent sur des
      données sans pays — factures fournisseurs (DPO), historique des indicateurs (variations « vs
      hier ») — ne sont pas calculés pour le pays ; le briefing nomme ceux qu&apos;il retire. Les
      objets non rattachés à un pays n&apos;apparaissent dans aucun périmètre pays.
    </p>
  );
}
