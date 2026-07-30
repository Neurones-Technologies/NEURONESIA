"use client";

import { ReactNode, useState } from "react";
import { DetailCard } from "./detail";

export interface ScenItem {
  label: string;
  value: string;
  detail: ReactNode;
  narrative: DetailCard;
  /** Scénario retenu par défaut — sélectionné et mis en avant au premier affichage. */
  mid?: boolean;
}

/** Trois cartes de scénario dont le détail s'affiche sous la grille (pas dans
 * le tiroir latéral global) : la sélection est locale à ce module, avec le
 * scénario `mid` ouvert par défaut. */
export function ScenPanel({ items }: { items: ScenItem[] }) {
  const defaultIndex = items.findIndex((it) => it.mid);
  const [selected, setSelected] = useState(defaultIndex >= 0 ? defaultIndex : 0);
  const active = items[selected];
  const paragraphs = active.narrative.body
    ? Array.isArray(active.narrative.body)
      ? active.narrative.body
      : [active.narrative.body]
    : [];

  return (
    <>
      <div className="scen">
        {items.map((it, i) => (
          <div
            key={i}
            className={`sc clk${i === selected ? " mid" : ""}`}
            tabIndex={0}
            role="button"
            aria-pressed={i === selected}
            onClick={() => setSelected(i)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setSelected(i);
              }
            }}
          >
            <div className="sc-l">{it.label}</div>
            <div className="sc-v">{it.value}</div>
            <div className="sc-p">{it.detail}</div>
          </div>
        ))}
      </div>
      <div className="scen-detail">
        <div className="scen-detail-h">
          <span>{active.narrative.kicker ?? "Détail"}</span>
          {active.narrative.tag && (
            <span className={`tag tag--${active.narrative.tagVariant ?? "n"}`}>{active.narrative.tag}</span>
          )}
        </div>
        <h4>{active.narrative.title}</h4>
        {paragraphs.map((p, i) => (
          <p key={i}>{p}</p>
        ))}
        {active.narrative.kv && active.narrative.kv.length > 0 && (
          <div className="kv">
            {active.narrative.kv.map((row, i) => (
              <div key={i}>
                <span>{row[0]}</span>
                <b>{row[1]}</b>
              </div>
            ))}
          </div>
        )}
        {active.narrative.note && <p className="foot-n">{active.narrative.note}</p>}
      </div>
    </>
  );
}
