"use client";

import { useActionState, useId, useRef, useState } from "react";

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
 * c'est le formulaire qui porte la sélection, comme dans ContexteForm. React ne
 * tient qu'un compteur de cases cochées — le minimum pour savoir si le mode
 * « consigne pilote » (rien de coché, consigne posée) sera actif. */
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
  const [nbCoches, setNbCoches] = useState(() => elements.filter((e) => e.actif).length);

  return (
    <>
      <form action={formAction}>
        <input type="hidden" name="profile" value={profile} />
        <input type="hidden" name="role" value={role} />
        <input type="hidden" name="consigne_max" value={consigneMax} />

        <div className="chks">
          {elements.map((e) => (
            <label className="chk" key={e.id}>
              <input
                type="checkbox"
                name="elements"
                value={e.id}
                defaultChecked={e.actif}
                onChange={(ev) => setNbCoches((n) => n + (ev.target.checked ? 1 : -1))}
              />
              <span>
                <span className="chk-n">{e.libelle}</span>
                <span className="chk-s">{e.description}</span>
              </span>
            </label>
          ))}
        </div>

        <ConsigneItems
          consigne={consigne}
          consigneMax={consigneMax}
          invalide={state.field === "consigne"}
          aucunCoche={nbCoches === 0}
        />

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

/** Consigne saisie en items : la virgule clôt l'item en cours et le transforme
 * en étiquette retirable ; Entrée fait pareil sans soumettre le formulaire ;
 * Retour arrière sur une saisie vide rouvre le dernier item au lieu de le
 * perdre.
 *
 * Le formulaire, lui, ne voit qu'une seule chaîne (input caché `consigne`,
 * items joints par « , ») : l'action serveur et l'API restent inchangés, et
 * une consigne enregistrée avant cet éditeur se relit telle quelle — ses
 * virgules redeviennent des items.
 *
 * `aucunCoche` sert au signal d'état : rien de coché + items présents = mode
 * « consigne pilote » à l'enregistrement — autant le dire ici, avant que
 * l'utilisateur ne le découvre dans son débrief du lendemain. */
function ConsigneItems({
  consigne,
  consigneMax,
  invalide,
  aucunCoche,
}: {
  consigne: string;
  consigneMax: number;
  invalide: boolean;
  aucunCoche: boolean;
}) {
  const [items, setItems] = useState(() =>
    consigne.split(",").map((t) => t.trim()).filter(Boolean)
  );
  const [saisie, setSaisie] = useState("");
  const saisieRef = useRef<HTMLInputElement>(null);
  const saisieId = useId();

  const valeur = [...items, saisie.trim()].filter(Boolean).join(", ");
  const restant = consigneMax - valeur.length;

  /** Refuse tout état qui dépasserait la limite — même comportement que le
   * `maxLength` du textarea remplacé : la frappe excédentaire est ignorée. */
  function applique(prochains: string[], prochaineSaisie: string) {
    const totale = [...prochains, prochaineSaisie.trim()].filter(Boolean).join(", ");
    if (totale.length > consigneMax) return;
    setItems(prochains);
    setSaisie(prochaineSaisie);
  }

  function onChange(ev: React.ChangeEvent<HTMLInputElement>) {
    const brut = ev.target.value;
    if (!brut.includes(",")) {
      applique(items, brut);
      return;
    }
    // Un collage peut apporter plusieurs virgules d'un coup : tous les
    // fragments clos deviennent des items, le dernier reste en cours de frappe.
    const fragments = brut.split(",");
    const enCours = fragments.pop() ?? "";
    applique([...items, ...fragments.map((f) => f.trim()).filter(Boolean)], enCours);
  }

  function onKeyDown(ev: React.KeyboardEvent<HTMLInputElement>) {
    if (ev.key === "Enter" && saisie.trim()) {
      // Entrée clôt l'item au lieu de soumettre — soumettre en pleine saisie
      // enregistrerait une composition pas encore finie d'écrire.
      ev.preventDefault();
      applique([...items, saisie.trim()], "");
    } else if (ev.key === "Backspace" && !saisie && items.length) {
      ev.preventDefault();
      applique(items.slice(0, -1), items[items.length - 1]);
    }
  }

  return (
    <div className="fld fld--stack">
      <div>
        <label className="fld-n" htmlFor={saisieId}>
          Autre — consigne de rédaction
        </label>
        <div className="fld-s">
          Avec des éléments cochés, elle oriente le ton et l&apos;angle du texte (« va droit au but »,
          « insiste sur ce qui bloque l&apos;encaissement »). Sans aucun élément coché, elle pilote
          seule le contenu : l&apos;IA choisit, parmi les données réelles du profil, ce qui répond à
          chaque consigne. Dans les deux cas, aucun chiffre n&apos;est inventé. La virgule sépare les
          consignes : chacune devient un item, retirable d&apos;un clic.
        </div>
      </div>
      <input type="hidden" name="consigne" value={valeur} />
      {/* Le clic sur la zone — étiquettes et marges comprises — rend la main à
          la saisie, comme dans un champ texte ordinaire. */}
      <div className="tagbox" onClick={() => saisieRef.current?.focus()}>
        {items.map((item, i) => (
          <span className="tag" key={`${item}-${i}`}>
            {item}
            <button
              type="button"
              className="tag-x"
              aria-label={`Retirer « ${item} »`}
              onClick={() => applique(items.filter((_, j) => j !== i), saisie)}
            >
              ×
            </button>
          </span>
        ))}
        <input
          ref={saisieRef}
          id={saisieId}
          type="text"
          value={saisie}
          aria-invalid={invalide || undefined}
          placeholder={
            items.length ? "Ajouter une consigne…" : "Laisser vide pour la rédaction par défaut."
          }
          onChange={onChange}
          onKeyDown={onKeyDown}
        />
      </div>
      <span className="ro">{restant} caractère(s) restant(s)</span>
      {aucunCoche &&
        (valeur ? (
          <span className="ro">
            Mode consigne : aucun élément coché — le débrief sera rédigé uniquement à partir de ces
            consignes, en piochant dans les données du profil.
          </span>
        ) : (
          <span className="ro">
            Aucun élément coché et aucune consigne : l&apos;enregistrement sera refusé.
          </span>
        ))}
    </div>
  );
}
