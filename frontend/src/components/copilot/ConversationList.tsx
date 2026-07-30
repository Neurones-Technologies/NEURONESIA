"use client";

import { useState } from "react";

export interface SessionSummary {
  session_id: string;
  title: string;
  started_at: string | null;
  last_at: string | null;
  turn_count: number;
}

/** « il y a 3 h », « hier », « 12 mars » — repère suffisant pour retrouver une
 * conversation dans une liste, sans imposer une date complète sur chaque ligne. */
function relativeDate(iso: string | null): string {
  if (!iso) return "";
  // Les dates backend sont en UTC naïf (datetime.utcnow, sans suffixe Z) :
  // sans le marquer, le navigateur les lirait en heure locale et afficherait
  // « dans 1 h » pour une conversation qui vient de se terminer.
  const stamp = /[Zz]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`;
  const date = new Date(stamp);
  if (Number.isNaN(date.getTime())) return "";

  const minutes = Math.round((Date.now() - date.getTime()) / 60000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `il y a ${hours} h`;
  const days = Math.round(hours / 24);
  if (days === 1) return "hier";
  if (days < 7) return `il y a ${days} j`;
  return date.toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
}

export function ConversationList({
  sessions,
  activeId,
  onSelect,
  onDelete,
  onNew,
}: {
  sessions: SessionSummary[];
  activeId: string;
  onSelect: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
  onNew: () => void;
}) {
  // Suppression définitive (le backend fait un DELETE, pas d'archive) : on
  // demande une confirmation dans la ligne elle-même plutôt qu'une modale.
  const [pendingId, setPendingId] = useState<string>("");

  return (
    <aside className="cop-side" aria-label="Historique des conversations">
      <div className="cop-side-h">
        <span>Historique</span>
        <button className="cop-new" type="button" onClick={onNew}>
          + Nouvelle
        </button>
      </div>

      {sessions.length === 0 && (
        <p className="cop-side-empty">
          Aucune conversation enregistrée pour ce profil. Vos échanges apparaîtront ici.
        </p>
      )}

      <div className="conv-list">
        {sessions.map((s) =>
          s.session_id === pendingId ? (
            <div key={s.session_id} className="conv conv--del">
              <span>Supprimer définitivement ?</span>
              <button
                className="conv-yes"
                type="button"
                onClick={() => {
                  setPendingId("");
                  onDelete(s.session_id);
                }}
              >
                Supprimer
              </button>
              <button className="conv-no" type="button" onClick={() => setPendingId("")}>
                Annuler
              </button>
            </div>
          ) : (
            <div
              key={s.session_id}
              className="conv"
              aria-current={s.session_id === activeId ? "true" : undefined}
            >
              <button
                className="conv-b"
                type="button"
                onClick={() => onSelect(s.session_id)}
                title={s.title}
              >
                <b>{s.title || "Conversation"}</b>
                <span>
                  {relativeDate(s.last_at)}
                  {s.turn_count
                    ? ` · ${Math.ceil(s.turn_count / 2)} échange${s.turn_count > 2 ? "s" : ""}`
                    : ""}
                </span>
              </button>
              <button
                className="conv-x"
                type="button"
                aria-label={`Supprimer la conversation « ${s.title || "Conversation"} »`}
                title="Supprimer"
                onClick={() => setPendingId(s.session_id)}
              >
                ×
              </button>
            </div>
          )
        )}
      </div>
    </aside>
  );
}
