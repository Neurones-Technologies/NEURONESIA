"use client";

import { useActionState, useId, useMemo, useState } from "react";

import type { ArbitrageConditionsReglage } from "@/lib/api/arbitrage";
import { saveConditionsAction } from "@/lib/actions/arbitrage";
import { ARBITRAGE_IDLE } from "@/lib/actions/arbitrage-state";
import { ROLE_LABELS } from "@/lib/auth/roles";
import { ActionMessage, SubmitBtn } from "@/components/views/arbitrage/feedback";

/** Conditions d'entrée en arbitrage — activation par profil.
 *
 * Le catalogue est FIGÉ dans le backend (`uc_arbitrage/conditions.py`) : cet
 * écran ne rédige rien, il coche. C'est délibéré — une condition d'entrée décide
 * de ce qui est soumis à décision, elle doit rester relisible dans le code et
 * couverte par des tests, pas saisie en texte libre puis réinterprétée à chaque
 * calcul sur un écran dont toute la valeur tient à ce qu'il peut dire POURQUOI
 * un dossier est là.
 *
 * Deux choses rendent ce réglage utilisable, et sans elles il ne le serait pas :
 *
 *   - le COMPTEUR VIVANT. Les conditions se combinent en ET : chaque case
 *     resserre la file, et deux cases parfaitement raisonnables peuvent la vider.
 *     Le nombre de dossiers restants est donc recalculé à chaque clic, avant
 *     enregistrement, par intersection des références renvoyées par le serveur
 *     (`mesure.refs_par_condition`) — aucun aller-retour réseau.
 *   - la MENTION DE PORTÉE. Le réglage appartient au profil, pas à la personne :
 *     cocher ici change la file de tous les collègues qui portent le même rôle.
 *     Le taire ferait modifier l'écran d'un autre sans le savoir. */
export function ConditionsArbitrage({
  profile,
  reglage,
  isAdmin,
}: {
  /** Profil cockpit de l'URL (dg, dc, df…) — sert à revalider les bonnes pages. */
  profile: string;
  reglage: ArbitrageConditionsReglage;
  isAdmin: boolean;
}) {
  const [state, formAction, pending] = useActionState(saveConditionsAction, ARBITRAGE_IDLE);
  const selectId = useId();

  const parametrables = reglage.profils_parametrables;
  const profilInitial = parametrables.includes(reglage.profil) ? reglage.profil : (parametrables[0] ?? "");
  const [profil, setProfil] = useState(profilInitial);
  const [selection, setSelection] = useState<string[]>(reglage.par_profil[profilInitial] ?? []);

  const total = reglage.mesure.refs_total.length;

  /** Nombre de dossiers que retiendrait une combinaison donnée. Aucune condition
   * cochée ne restreint rien : le résultat est la file du socle. */
  const compte = useMemo(() => {
    const refsParCondition = reglage.mesure.refs_par_condition;
    const tous = reglage.mesure.refs_total;
    return (codes: string[]) => {
      if (codes.length === 0) return tous.length;
      const ensembles = codes.map((code) => new Set(refsParCondition[code] ?? []));
      return tous.filter((ref) => ensembles.every((e) => e.has(ref))).length;
    };
  }, [reglage.mesure]);

  const retenus = compte(selection);
  const enregistre = reglage.par_profil[profil] ?? [];
  const modifie =
    enregistre.length !== selection.length || enregistre.some((code) => !selection.includes(code));

  function changerProfil(nouveau: string) {
    setProfil(nouveau);
    setSelection(reglage.par_profil[nouveau] ?? []);
  }

  function basculer(code: string, actif: boolean) {
    setSelection((courant) =>
      actif ? [...courant, code] : courant.filter((c) => c !== code)
    );
  }

  const libelleProfil = ROLE_LABELS[profil] ?? profil;

  return (
    <form action={formAction}>
      <input type="hidden" name="profile" value={profile} />
      <input type="hidden" name="profil" value={profil} />

      {isAdmin && parametrables.length > 0 && (
        <div className="fld">
          <div>
            <div className="fld-n">Profil réglé</div>
            <div className="fld-s">
              Vous êtes administrateur : vous réglez la file des profils métier. Votre propre file
              n&apos;est jamais filtrée.
            </div>
          </div>
          <select
            id={selectId}
            className="sel"
            value={profil}
            onChange={(e) => changerProfil(e.target.value)}
          >
            {parametrables.map((p) => (
              <option key={p} value={p}>
                {ROLE_LABELS[p] ?? p}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* même gabarit que « Personnaliser mon débrief » : la case précède son
          libellé, et toute la ligne est l'étiquette cliquable. La case porte
          donc son nom accessible par le texte qu'elle contient — plus besoin
          d'annoncer « active / inactive » en mots. */}
      <div className="chks">
        {reglage.catalogue.map((condition) => {
          const coche = selection.includes(condition.code);
          const seule = compte([condition.code]);
          const avec = compte(coche ? selection : [...selection, condition.code]);
          return (
            <label className="chk" key={condition.code}>
              <input
                type="checkbox"
                name="codes"
                value={condition.code}
                checked={coche}
                onChange={(e) => basculer(condition.code, e.target.checked)}
              />
              <span>
                <span className="chk-n">
                  {condition.libelle}
                  {condition.seuil ? ` — ${condition.seuil}` : ""}
                </span>
                <span className="chk-s">
                  {condition.explication}
                  <br />
                  Retient {seule} dossier(s) sur {total} prise seule
                  {coche ? "" : `, ${avec} en la cochant avec vos autres cases`}.
                  {condition.recommandee_pour.length > 0 && (
                    <>
                      {" "}
                      Conseillée pour&nbsp;:{" "}
                      {condition.recommandee_pour.map((r) => ROLE_LABELS[r] ?? r).join(", ")}.
                    </>
                  )}
                </span>
              </span>
            </label>
          );
        })}
      </div>

      <div className="fld">
        <div>
          <div className="fld-n">
            {selection.length === 0
              ? `Aucune condition active — la file garde ses ${total} dossier(s).`
              : `${retenus} dossier(s) sur ${total} resteraient dans la file de ce profil.`}
          </div>
          <div className="fld-s">
            {retenus === 0 && selection.length > 0 ? (
              <>
                Ces conditions se combinent en ET et ne laissent plus aucun dossier : la file de{" "}
                {libelleProfil} serait vide. Décochez-en une.
              </>
            ) : (
              <>
                Les indicateurs de l&apos;écran Arbitrages restent calculés sur la file entière —
                seule la liste est restreinte, et ce qui en sort y est annoncé.
              </>
            )}
          </div>
        </div>
        <span className="ro">{modifie ? "non enregistré" : "enregistré"}</span>
      </div>

      <ActionMessage state={state} />
      <div className="acts">
        <SubmitBtn
          pending={pending}
          primary={false}
          label="Enregistrer pour ce profil"
          pendingLabel="Enregistrement…"
        />
        <span className="ro">
          Ce réglage s&apos;applique à tous les utilisateurs du profil {libelleProfil}, pas à votre
          seul compte.
        </span>
      </div>
    </form>
  );
}
