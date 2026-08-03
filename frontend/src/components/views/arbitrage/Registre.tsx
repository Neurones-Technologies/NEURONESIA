"use client";

import { useActionState, useMemo, useState } from "react";

import type { DetailCard } from "@/components/ui/detail";
import { DetailButton } from "@/components/ui/detail";
import { Tag } from "@/components/ui/primitives";
import { markReviewedAction } from "@/lib/actions/arbitrage";
import { ARBITRAGE_IDLE } from "@/lib/actions/arbitrage-state";
import { formatNumber } from "@/lib/format";
import { Variant } from "@/lib/types";
import { ActionMessage, SubmitBtn } from "./feedback";

export interface RegistreRow {
  id: number;
  titre: string;
  sujet: string;
  statutLabel: string;
  statutVariant: Variant;
  mandatLabel: string;
  enjeuLabel: string;
  creeLe: string;
  optionRetenue: string;
  suiviLabel: string;
  suiviVariant: Variant;
  revueLabel: string;
  revueVariant: Variant;
  /** Échéance de relecture dépassée sans verdict — la seule catégorie qui
   * demande une action de la part de quelqu'un. */
  enRetard: boolean;
  relueDeja: boolean;
  /** Le profil courant a-t-il le mandat pour clore la revue de cette ligne ? */
  peutRelire: boolean;
  detail: DetailCard;
}

const VERDICTS = [
  { code: "confirme", label: "Confirmée", desc: "l'issue constatée valide ce qui avait été recommandé" },
  { code: "infirme", label: "Infirmée", desc: "l'issue montre que la recommandation était à côté" },
  { code: "partiel", label: "Partiellement", desc: "juste sur le fond, fausse sur une partie" },
];

/** Registre des décisions — module 28, jusqu'ici absent de l'écran.
 *
 * L'indicateur « Revues en retard » du bandeau annonçait un encours puis
 * concluait que cet écran ne permettait pas de le traiter : le seul chemin pour
 * clore une revue n'existait nulle part dans l'application, alors que l'action
 * serveur, elle, existait déjà. Le registre est donc rendu ici, et la revue s'y
 * fait en place — c'est elle qui rend l'outil vérifiable après coup, en
 * comparant l'issue constatée à ce qui avait été recommandé. */
export function Registre({ rows, profile }: { rows: RegistreRow[]; profile: string }) {
  const nbARelire = useMemo(() => rows.filter((r) => !r.relueDeja).length, [rows]);
  const [seulementARelire, setSeulementARelire] = useState(nbARelire > 0);
  const [ouvert, setOuvert] = useState<number | null>(null);

  const visible = seulementARelire ? rows.filter((r) => !r.relueDeja) : rows;

  if (rows.length === 0) {
    return (
      <p className="arb-empty">
        Le registre est vide : aucune décision n&apos;a encore été journalisée depuis cet écran.
      </p>
    );
  }

  return (
    <>
      <div className="arb-seg arb-seg--c" role="group" aria-label="Filtre du registre">
        <button type="button" aria-pressed={seulementARelire} onClick={() => setSeulementARelire(true)} disabled={nbARelire === 0}>
          À relire <i>{formatNumber(nbARelire)}</i>
        </button>
        <button type="button" aria-pressed={!seulementARelire} onClick={() => setSeulementARelire(false)}>
          Toutes <i>{formatNumber(rows.length)}</i>
        </button>
      </div>

      <div style={{ overflowX: "auto" }}>
        <table className="tb">
          <thead>
            <tr>
              <th>Décision</th>
              <th>État</th>
              <th className="r">Enjeu</th>
              <th>Recommandation</th>
              <th>Mandat</th>
              <th>Revue</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <RegistreLigne
                key={r.id}
                row={r}
                profile={profile}
                ouvert={ouvert === r.id}
                onToggle={() => setOuvert(ouvert === r.id ? null : r.id)}
              />
            ))}
            {visible.length === 0 && (
              <tr>
                <td colSpan={6} style={{ color: "var(--t2)" }}>
                  Aucune décision en attente de revue.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

function RegistreLigne({
  row,
  profile,
  ouvert,
  onToggle,
}: {
  row: RegistreRow;
  profile: string;
  ouvert: boolean;
  onToggle: () => void;
}) {
  const [state, formAction, pending] = useActionState(markReviewedAction, ARBITRAGE_IDLE);

  return (
    <>
      <tr className={row.enRetard ? "arb-late" : undefined}>
        <td>
          <DetailButton detail={row.detail} className="linkish arb-cellbtn">
            {row.sujet || row.titre}
          </DetailButton>
          <div className="ro">{row.creeLe}</div>
        </td>
        <td>
          <Tag variant={row.statutVariant}>{row.statutLabel}</Tag>
        </td>
        <td className="r mono">{row.enjeuLabel}</td>
        <td style={{ fontSize: 12 }}>
          <Tag variant={row.suiviVariant}>{row.suiviLabel}</Tag>
          <div className="ro" style={{ marginTop: 3 }}>
            {row.optionRetenue || "aucune option retenue"}
          </div>
        </td>
        <td style={{ fontSize: 12.5, color: "var(--t2)" }}>{row.mandatLabel}</td>
        <td>
          {row.relueDeja ? (
            <Tag variant={row.revueVariant}>{row.revueLabel}</Tag>
          ) : row.peutRelire ? (
            <button type="button" className="btn arb-btn-s" aria-expanded={ouvert} onClick={onToggle}>
              {ouvert ? "Fermer" : "Relire"}
            </button>
          ) : (
            <Tag variant={row.revueVariant}>{row.revueLabel}</Tag>
          )}
          {!row.relueDeja && row.peutRelire && <div className="ro" style={{ marginTop: 3 }}>{row.revueLabel}</div>}
        </td>
      </tr>
      {ouvert && (
        <tr>
          <td colSpan={6} className="arb-revcell">
            <form action={formAction} className="arb-rev">
              <input type="hidden" name="profile" value={profile} />
              <input type="hidden" name="decision_id" value={row.id} />
              <p className="arb-hint">
                La revue compare l&apos;issue réellement constatée à ce qui avait été recommandé. Son verdict est
                choisi par le mandataire, jamais imposé par l&apos;outil — c&apos;est ce qui rend le taux de
                confirmation interprétable.
              </p>
              <div className="arb-choice">
                {VERDICTS.map((v, i) => (
                  <label key={v.code} className="arb-ch">
                    <input type="radio" className="sr-only" name="review_verdict" value={v.code} defaultChecked={i === 0} />
                    <b>{v.label}</b>
                    <span>{v.desc}</span>
                  </label>
                ))}
              </div>
              <textarea
                className="txa"
                name="review_comment"
                placeholder="Ce qui s'est réellement passé depuis — encaissement obtenu, commande perdue, litige ouvert. C'est cette phrase qui donnera un sens au verdict à la relecture suivante."
              />
              <ActionMessage state={state} />
              <div className="acts">
                <SubmitBtn pending={pending} label="Enregistrer la revue" pendingLabel="Enregistrement…" />
                <button type="button" className="btn" onClick={onToggle}>
                  Annuler
                </button>
              </div>
            </form>
          </td>
        </tr>
      )}
    </>
  );
}
