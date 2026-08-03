"use client";

import { useActionState, useId, useState } from "react";

import type { DetailCard } from "@/components/ui/detail";
import { DetailButton } from "@/components/ui/detail";
import { Tag } from "@/components/ui/primitives";
import { createDecisionAction } from "@/lib/actions/arbitrage";
import { ARBITRAGE_IDLE } from "@/lib/actions/arbitrage-state";
import { ActionMessage, SubmitBtn } from "./feedback";

export interface OptionVM {
  code: string;
  titre: string;
  description: string;
  argumentaire?: string;
  repli: boolean;
  recommandee: boolean;
  /** Valeur journalisée, `A · titre` — format attendu par le registre. */
  value: string;
  consequences: { role: string; text: string; variant: string; verdict: string }[];
  detail: DetailCard;
}

type Issue = "tranchee" | "reportee" | "escaladee";

const ISSUES: { code: Issue; titre: string; desc: string }[] = [
  { code: "tranchee", titre: "Trancher", desc: "l'option retenue engage l'entreprise" },
  { code: "reportee", titre: "Reporter", desc: "ne pas trancher aujourd'hui — motif requis" },
  { code: "escaladee", titre: "Escalader", desc: "remonter au comité ou à la DG — motif requis" },
];

/** Choix de l'option ET journalisation de la décision, dans un seul geste.
 *
 * Les deux étaient séparés : on lisait des cartes d'options en haut, puis on
 * rechoisissait la même option dans une liste déroulante en bas de page, sans
 * que rien ne relie visuellement les deux. La carte EST maintenant le contrôle
 * de sélection — le formulaire n'a plus de doublon à tenir à jour.
 *
 * Le cockpit classe les options, il ne tranche pas : le mandataire retient celle
 * qu'il veut, y compris contre la recommandation. L'écart est enregistré (cf.
 * `option_recommandee`) et alimente le taux de suivi ; il n'est jamais empêché. */
export function DecisionCockpit({
  options,
  recommandee,
  hidden,
  ecartNote,
}: {
  options: OptionVM[];
  /** Valeur de l'option recommandée, présélectionnée à l'ouverture. */
  recommandee: string;
  /** Champs de contexte du dossier envoyés tels quels au registre. */
  hidden: Record<string, string>;
  ecartNote: string;
}) {
  const [state, formAction, pending] = useActionState(createDecisionAction, ARBITRAGE_IDLE);
  const [choix, setChoix] = useState(recommandee);
  const [issue, setIssue] = useState<Issue>("tranchee");
  const motifId = useId();

  const tranche = issue === "tranchee";
  const motifRequis = !tranche;
  const ecart = tranche && choix !== recommandee;

  return (
    <form action={formAction} className="arb-cockpit">
      {Object.entries(hidden).map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
      <input type="hidden" name="option_recommandee" value={recommandee} />

      <fieldset className="arb-fs">
        <legend className="mini-l">
          Options et conséquences par profil
          <span>
            {tranche
              ? "sélectionnez celle que vous retenez — la recommandée découle du comportement de paiement mesuré, pas d'une règle unique"
              : "sans objet sur un report ou une escalade : aucune option n'est retenue, rien ne serait engagé"}
          </span>
        </legend>
        <div className="opts" data-muted={tranche ? undefined : "true"}>
          {options.map((opt) => {
            const sel = tranche && choix === opt.value;
            return (
              <div key={opt.code} className={`opt${opt.recommandee ? " reco" : ""}${sel ? " is-sel" : ""}`}>
                <label className="opt-pick">
                  <input
                    type="radio"
                    className="sr-only"
                    name="option_retenue"
                    value={opt.value}
                    checked={choix === opt.value}
                    disabled={!tranche}
                    onChange={() => setChoix(opt.value)}
                  />
                  <span className="opt-h">
                    <span className="opt-n">Option {opt.code}</span>
                    {opt.recommandee && <Tag variant="a">recommandée</Tag>}
                    <span className="opt-check" aria-hidden="true">
                      {sel ? "✓ retenue" : "retenir"}
                    </span>
                  </span>
                  <b className="opt-t">{opt.titre}</b>
                  <span className="opt-d">{opt.description}</span>
                  {opt.argumentaire && (
                    <span className="opt-a">
                      À dire au client : « {opt.argumentaire} »{opt.repli && " (repli — modèle indisponible)"}
                    </span>
                  )}
                  {opt.consequences.map((c, i) => (
                    <span className={`ocons ocons--${c.variant}`} key={i}>
                      <span className="ocons-h">
                        <i>{c.role}</i>
                        <span className={`tag tag--${c.variant}`}>{c.verdict}</span>
                      </span>
                      <span className="ocons-t">{c.text}</span>
                    </span>
                  ))}
                </label>
                <div className="opt-foot">
                  <DetailButton detail={opt.detail} className="linkish">
                    Méthode et conséquences détaillées
                  </DetailButton>
                </div>
              </div>
            );
          })}
        </div>
        {ecart && <p className="arb-ecart">Vous vous écartez de la recommandation. C&apos;est permis et journalisé tel quel : {ecartNote}</p>}
      </fieldset>

      <fieldset className="arb-fs">
        <legend className="mini-l">
          Issue du passage en comité
          <span>reporter ou escalader est une décision — journalisée comme telle, avec son motif</span>
        </legend>
        <div className="arb-choice">
          {ISSUES.map((it) => (
            <label key={it.code} className={`arb-ch${issue === it.code ? " is-sel" : ""}`}>
              <input
                type="radio"
                className="sr-only"
                name="status"
                value={it.code}
                checked={issue === it.code}
                onChange={() => setIssue(it.code)}
              />
              <b>{it.titre}</b>
              <span>{it.desc}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="arb-fs">
        <label className="mini-l" htmlFor={motifId}>
          Motif {motifRequis ? <em className="arb-req">obligatoire</em> : <span>facultatif — l&apos;option retenue porte déjà son sens</span>}
        </label>
        <textarea
          id={motifId}
          className="txa"
          name="motif_decision"
          required={motifRequis}
          aria-invalid={state.field === "motif_decision" || undefined}
          placeholder={
            motifRequis
              ? "Ce qui justifie de ne pas trancher aujourd'hui — c'est ce que la revue à 30 jours relira pour juger si l'attente était fondée."
              : "Ce qui fonde ce choix, si vous voulez le fixer par écrit."
          }
        />
      </div>

      <ActionMessage state={state} />

      <div className="acts">
        <SubmitBtn pending={pending} label="Journaliser la décision" pendingLabel="Journalisation…" />
        <span className="ro">
          Journalisée à votre nom, avec une échéance de relecture à 30 jours.
        </span>
      </div>
    </form>
  );
}
