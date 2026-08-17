"use client";

import { useActionState, useId, useState } from "react";

import { regenerateDebriefAction, saveDebriefAction } from "@/lib/actions/briefing";
import { BRIEFING_IDLE } from "@/lib/actions/briefing-state";
import type { DebriefElement } from "@/lib/api/briefing";
import { ActionMessage, SubmitBtn } from "@/components/views/arbitrage/feedback";

/** Composition du débrief quotidien d'un profil.
 *
 * Deux formulaires distincts et non deux boutons dans un seul : chacun porte son
 * propre `useActionState`, donc son propre état d'attente et son propre bandeau
 * de retour. Réunis, un seul des deux états serait rendu, et la régénération
 * recevrait des cases à cocher dont elle n'a que faire.
 *
 * L'état des cases vit dans le DOM (`defaultChecked`), pas dans un `useState` :
 * c'est le formulaire qui porte la sélection, comme dans ContexteForm. Le seul
 * état React ici compte les caractères restants de la consigne. */
export function DebriefForm({
  profile,
  role,
  elements,
  consigne,
  consigneMax,
  source,
  updatedBy,
}: {
  profile: string;
  role: string;
  elements: DebriefElement[];
  consigne: string;
  consigneMax: number;
  source: "defaut" | "reglee";
  updatedBy: string | null;
}) {
  const [state, formAction, pending] = useActionState(saveDebriefAction, BRIEFING_IDLE);
  const [regenState, regenAction, regenPending] = useActionState(
    regenerateDebriefAction,
    BRIEFING_IDLE
  );
  const [restant, setRestant] = useState(consigneMax - consigne.length);
  const consigneId = useId();

  return (
    <>
      <form action={formAction}>
        <input type="hidden" name="profile" value={profile} />
        <input type="hidden" name="role" value={role} />
        <input type="hidden" name="consigne_max" value={consigneMax} />

        <div className="chks">
          {elements.map((e) => (
            <label className="chk" key={e.id}>
              <input type="checkbox" name="elements" value={e.id} defaultChecked={e.actif} />
              <span>
                <span className="chk-n">{e.libelle}</span>
                <span className="chk-s">{e.description}</span>
              </span>
            </label>
          ))}
        </div>

        <div className="fld fld--stack">
          <div>
            <label className="fld-n" htmlFor={consigneId}>
              Autre — consigne de rédaction
            </label>
            <div className="fld-s">
              Oriente le ton et l&apos;angle du texte (« va droit au but », « insiste sur ce qui bloque
              l&apos;encaissement »). N&apos;ajoute aucune donnée : les chiffres restent ceux des éléments
              cochés ci-dessus.
            </div>
          </div>
          <textarea
            id={consigneId}
            className="txa"
            name="consigne"
            defaultValue={consigne}
            maxLength={consigneMax}
            aria-invalid={state.field === "consigne" || undefined}
            placeholder="Laisser vide pour la rédaction par défaut."
            onChange={(ev) => setRestant(consigneMax - ev.target.value.length)}
          />
          <span className="ro">{restant} caractère(s) restant(s)</span>
        </div>

        <ActionMessage state={state} />
        <div className="acts">
          <SubmitBtn
            pending={pending}
            label="Enregistrer la composition"
            pendingLabel="Enregistrement…"
          />
          <span className="ro">
            {source === "reglee" && updatedBy
              ? `Réglage partagé par tout le profil — dernière modification par ${updatedBy}.`
              : "Composition par défaut — ce réglage vaudra pour tous les comptes de ce profil."}
          </span>
        </div>
      </form>

      <form action={regenAction}>
        <input type="hidden" name="profile" value={profile} />
        <input type="hidden" name="role" value={role} />
        <ActionMessage state={regenState} />
        <div className="acts">
          {/* La durée est annoncée : deux appels au modèle plus les requêtes
              métier, soit une attente pendant laquelle un bouton muet
              inviterait à double-cliquer. */}
          <SubmitBtn
            pending={regenPending}
            primary={false}
            label="Régénérer le débrief"
            pendingLabel="Régénération… (10 à 30 s)"
          />
          <span className="ro">
            Recalcule les faits et refait rédiger le texte — pour ce profil uniquement.
          </span>
        </div>
      </form>
    </>
  );
}
