import { ReactNode } from "react";
import { Variant } from "@/lib/types";
import { Clickable, DetailCard } from "./detail";

type Span = 3 | 4 | 5 | 6 | 7 | 8 | 12;

export function Bento({ children }: { children: ReactNode }) {
  return <div className="bento">{children}</div>;
}

export function Tile({
  span = 12,
  title,
  kick,
  quiet,
  children,
}: {
  span?: Span;
  title?: string;
  kick?: string;
  quiet?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={`tile t${span}${quiet ? " tile--q" : ""}`}>
      {(title || kick) && (
        <div className="tile-h">
          {title && <h3>{title}</h3>}
          {kick && <span className="tile-k">{kick}</span>}
        </div>
      )}
      {children}
    </div>
  );
}

/** Panneau sombre d'ouverture de vue — le « brief » de la maquette. Le texte
 * vient du narratif réel (briefing/analyse), jamais d'un gabarit figé.
 *
 * `lines` sert au résumé en 5 lignes (une idée par ligne, rendu serré) ;
 * `paragraphs` sert à la prose longue. Les deux sont acceptés pour permettre
 * un repli sur l'analyse quand le résumé n'est pas encore généré. */
export function Brief({
  kicker,
  headline,
  lines,
  paragraphs,
  pills,
}: {
  kicker: string;
  headline: string;
  lines?: string[];
  paragraphs?: string[];
  pills?: { label: string; hot?: boolean }[];
}) {
  return (
    <div className="brief">
      <p className="brief-k">
        <span className="dot" />
        {kicker}
      </p>
      <h2>{headline}</h2>
      {lines && lines.length > 0 && (
        <ul className="brief-l">
          {lines.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
      {(paragraphs ?? []).map((p, i) => (
        <p key={i}>{p}</p>
      ))}
      {pills && pills.length > 0 && (
        <div className="brief-r">
          {pills.map((p, i) => (
            <span key={i} className={`bpill${p.hot ? " bpill--hot" : ""}`}>
              {p.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/** Tuile d'indicateur : grand chiffre + lecture + histogramme de tendance. */
export function StatTile({
  span = 4,
  label,
  value,
  unit,
  reading,
  readingVariant,
  spark,
  sparkAxis,
  detail,
}: {
  span?: Span;
  label: string;
  value: string;
  unit?: string;
  reading?: string;
  readingVariant?: "pos" | "neg" | "wat";
  spark?: number[];
  sparkAxis?: string[];
  detail?: DetailCard;
}) {
  const body = (
    <>
      <div className="tile-h">
        <h3>{label}</h3>
      </div>
      <div>
        <span className="stat-v num">{value}</span>
        {unit && <span className="stat-u">{unit}</span>}
      </div>
      {reading && <div className={`stat-d${readingVariant ? " " + readingVariant : ""}`}>{reading}</div>}
      {spark && spark.length > 0 && (
        <div className="spark" aria-hidden="true">
          {spark.map((h, i) => (
            <i key={i} className={i >= spark.length - 3 ? "on" : ""} style={{ height: `${Math.max(4, h)}%` }} />
          ))}
        </div>
      )}
      {sparkAxis && sparkAxis.length > 0 && (
        <div className="comb-ax">
          {sparkAxis.map((a, i) => (
            <span key={i} style={{ flex: 1, textAlign: "center", width: "auto" }}>
              {a}
            </span>
          ))}
        </div>
      )}
    </>
  );
  if (!detail) return <div className={`tile t${span}`}>{body}</div>;
  return (
    <Clickable className={`tile t${span}`} detail={detail}>
      {body}
    </Clickable>
  );
}

export interface BarRow {
  name: string;
  sub?: string;
  value: string;
  pct: number;
  variant?: "r" | "w" | "s";
  detail?: DetailCard;
}

export function Bars({ rows }: { rows: BarRow[] }) {
  return (
    <div className="bars">
      {rows.map((r, i) => {
        const inner = (
          <>
            <div className="bar-n">
              {r.name}
              {r.sub && <span>{r.sub}</span>}
              <div className="bar-t">
                <i className={r.variant} style={{ width: `${Math.max(2, Math.min(100, r.pct))}%` }} />
              </div>
            </div>
            <div className="bar-v">{r.value}</div>
          </>
        );
        return r.detail ? (
          <Clickable key={i} className="bar-r" detail={r.detail}>
            {inner}
          </Clickable>
        ) : (
          <div key={i} className="bar-r">
            {inner}
          </div>
        );
      })}
    </div>
  );
}

export interface LstItem {
  title: string;
  sub?: string;
  tag: string;
  tagVariant: Variant;
  detail?: DetailCard;
}

export function Lst({ items }: { items: LstItem[] }) {
  return (
    <div className="lst">
      {items.map((it, i) => {
        const inner = (
          <>
            <b>{String(i + 1).padStart(2, "0")}</b>
            <span className="lst-t">
              <b>{it.title}</b>
              {it.sub && <span>{it.sub}</span>}
            </span>
            <span className={`tag tag--${it.tagVariant}`}>{it.tag}</span>
          </>
        );
        return it.detail ? (
          <Clickable key={i} className="lst-i" detail={it.detail}>
            {inner}
          </Clickable>
        ) : (
          <div key={i} className="lst-i">
            {inner}
          </div>
        );
      })}
    </div>
  );
}

export function FootNote({ children }: { children: ReactNode }) {
  return <p className="foot-n">{children}</p>;
}

export function HintLine({ children }: { children: ReactNode }) {
  return (
    <p className="hintline">
      <i />
      {children}
    </p>
  );
}
