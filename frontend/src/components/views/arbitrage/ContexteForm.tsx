"use client";

import { useActionState, useId } from "react";

import { addContexteAction } from "@/lib/actions/arbitrage";
import { ARBITRAGE_IDLE } from "@/lib/actions/arbitrage-state";
import { ActionMessage, SubmitBtn } from "./feedback";

/** Contribution du terrain sur un dossier.
 *
 * C'est la seule action de cet écran ouverte à un profil SANS mandat, et c'est
 * délibéré : le dossier réclame explicitement le motif du retard en désignant le
 * compte comme détenteur de l'information, alors que l'account manager n'a jamais
 * le mandat (celui-ci revient à la direction financière ou à la DG selon le
 * montant). Le profil qui détient le fait décisif n'avait donc aucun moyen de le
 * verser au dossier. Les contributions s'empilent au lieu de s'écraser : si le
 * motif change entre deux passages en comité, ce changement est lui-même une
 * information que la revue à 30 jours doit pouvoir relire. */
export function ContexteForm({
  profile,
  subjectRef,
  commercialCompte,
}: {
  profile: string;
  subjectRef: string;
  commercialCompte: string | null;
}) {
  const [state, formAction, pending] = useActionState(addContexteAction, ARBITRAGE_IDLE);
  const motifId = useId();
  const actifId = useId();

  return (
    <form action={formAction}>
      <input type="hidden" name="profile" value={profile} />
      <input type="hidden" name="subject_ref" value={subjectRef} />
      <p className="arb-hint">
        Aucun mandat requis pour contribuer ici : apporter un fait n&apos;est pas engager l&apos;entreprise.
        {commercialCompte ? ` Compte suivi par ${commercialCompte}.` : ""}
      </p>
      <div className="dform" style={{ borderTop: 0, paddingTop: 0, marginTop: 0 }}>
        <div className="dform-r">
          <label htmlFor={motifId}>Motif du retard</label>
          <textarea
            id={motifId}
            className="txa"
            name="motif_retard"
            aria-invalid={state.field === "motif_retard" || undefined}
            placeholder="Ce que le client a répondu — attente de mandatement, litige sur une prestation, changement d'interlocuteur… Le miroir Odoo ne contient rien de tout cela."
          />
        </div>
        <div className="dform-r">
          <label htmlFor={actifId}>Dossier commercial encore d&apos;actualité ?</label>
          <select id={actifId} className="sel" name="dossier_toujours_actif" defaultValue="">
            <option value="">Sans réponse</option>
            <option value="oui">Oui — le client confirme</option>
            <option value="non">Non — le client a renoncé</option>
            <option value="incertain">Incertain — pas de réponse claire</option>
          </select>
        </div>
      </div>
      <ActionMessage state={state} />
      <div className="acts">
        <SubmitBtn pending={pending} primary={false} label="Verser au dossier" pendingLabel="Versement…" />
        <span className="ro">Daté et signé à votre nom, sans écraser les contributions précédentes.</span>
      </div>
    </form>
  );
}
