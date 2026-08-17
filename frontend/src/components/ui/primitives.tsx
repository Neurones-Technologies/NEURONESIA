import { ReactNode, Fragment } from "react";
import { Variant } from "@/lib/types";

export function ViewHeader({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow?: string;
  title: string;
  subtitle: ReactNode;
}) {
  return (
    <>
      {eyebrow && <p className="eyebrow">{eyebrow}</p>}
      <h1 className="vt">{title}</h1>
      <p className="vsub">{subtitle}</p>
    </>
  );
}

export function KpiStrip({ children }: { children: ReactNode }) {
  return <div className="kpis">{children}</div>;
}

export function Kpi({
  label,
  value,
  valueVariant,
  detail,
}: {
  label: string;
  value: string;
  valueVariant?: Variant;
  detail: ReactNode;
}) {
  const cls = valueVariant === "s" ? "up" : valueVariant === "r" ? "dn" : valueVariant === "w" ? "wa" : undefined;
  const topAccent = valueVariant === "s" || valueVariant === "r" || valueVariant === "w" ? ` kpi--${valueVariant}` : "";
  return (
    <div className={`kpi${topAccent}`}>
      <div className="kpi-l">{label}</div>
      <div className={`kpi-v${cls ? " " + cls : ""}`}>{value}</div>
      <div className="kpi-d">{detail}</div>
    </div>
  );
}

export function Mods({ children }: { children: ReactNode }) {
  return <div className="mods">{children}</div>;
}

/** Section d'une vue. Sans `title`, la section garde son ancre (pour le menu
 * de sections) mais n'affiche pas d'en-tête — utile quand le contenu porte
 * déjà son propre titre (panneau brief, par exemple). */
export function Section({
  id,
  title,
  subtitle,
  children,
}: {
  id?: string;
  title?: string;
  subtitle?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="sec" id={id}>
      {title && (
        <div className="sec-h">
          <b>{title}</b>
          {subtitle && <span>{subtitle}</span>}
        </div>
      )}
      {children}
    </section>
  );
}

export function ModuleCard({
  n,
  title,
  desc,
  engine,
  llm,
  children,
}: {
  n: string;
  title: string;
  desc: string;
  engine: string;
  llm?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="mod">
      <div className="mod-h">
        <div className="mod-n">{n}</div>
        <div className="mod-t">
          <h3>{title}</h3>
          <p>{desc}</p>
        </div>
        <div className={`eng${llm ? " eng--llm" : ""}`}>{engine}</div>
      </div>
      <div className="mod-b">{children}</div>
    </div>
  );
}

export function Tag({ variant, children }: { variant: Variant; children: ReactNode }) {
  return <span className={`tag tag--${variant}`}>{children}</span>;
}

export function Meter({ variant, width }: { variant?: "r" | "w" | "s"; width: string }) {
  return (
    <div className="meter">
      <i className={variant} style={{ width }} />
    </div>
  );
}

export function Note({
  children,
  accent,
  style,
}: {
  children: ReactNode;
  accent?: boolean;
  style?: React.CSSProperties;
}) {
  return (
    <p className="note" style={{ ...(accent ? { borderLeftColor: "var(--accent)" } : undefined), ...style }}>
      {children}
    </p>
  );
}

export function Narr({ children, style }: { children: ReactNode; style?: React.CSSProperties }) {
  return (
    <div className="narr" style={style}>
      {children}
    </div>
  );
}

/** Rendu d'un texte généré par le LLM (paragraphes séparés par une ligne
 * vide) — la forme la plus courante des endpoints `.../analysis`. */
export function AnalysisNarr({ text, style }: { text: string; style?: React.CSSProperties }) {
  const paragraphs = text.split(/\n\s*\n/).filter((p) => p.trim());
  return (
    <Narr style={style}>
      {paragraphs.map((p, i) => (
        <p key={i}>{p.trim()}</p>
      ))}
    </Narr>
  );
}

export function Mk({ variant, children }: { variant?: "r" | "s"; children: ReactNode }) {
  return <span className={`mk${variant === "r" ? " mk-r" : variant === "s" ? " mk-s" : ""}`}>{children}</span>;
}

export function Split({ children }: { children: ReactNode }) {
  return <div className="split">{children}</div>;
}

export function MiniLabel({ children, style }: { children: ReactNode; style?: React.CSSProperties }) {
  return (
    <p className="mini-l" style={style}>
      {children}
    </p>
  );
}

export function Acts({ children, style }: { children: ReactNode; style?: React.CSSProperties }) {
  return (
    <div className="acts" style={style}>
      {children}
    </div>
  );
}

export function Btn({
  primary,
  children,
  ...props
}: { primary?: boolean; children: ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button className={`btn${primary ? " btn--p" : ""}`} type="button" {...props}>
      {children}
    </button>
  );
}

export function Legend({ items }: { items: { swatch: React.CSSProperties; label: string }[] }) {
  return (
    <div className="legend">
      {items.map((it, i) => (
        <span key={i}>
          <i style={it.swatch} />
          {it.label}
        </span>
      ))}
    </div>
  );
}

export interface Tooth {
  h: string;
  v?: "a" | "s" | "r" | "w" | "void";
  w?: string;
}

export function Comb({ teeth, axis, height }: { teeth: Tooth[]; axis?: string[]; height?: number }) {
  return (
    <>
      <div className="comb" style={height ? { height } : undefined}>
        {teeth.map((t, i) => (
          <div
            key={i}
            className={`tooth${t.v ? " " + t.v : ""}`}
            style={{ height: t.h, width: t.w }}
          />
        ))}
      </div>
      {axis && (
        <div className="comb-ax">
          {axis.map((a, i) => (
            <span key={i} style={teeth[i]?.w ? { width: teeth[i].w } : undefined}>
              {a}
            </span>
          ))}
        </div>
      )}
    </>
  );
}

export function Rows({ children }: { children: ReactNode }) {
  return <div className="rows">{children}</div>;
}

export function RowText({ title, sub }: { title: ReactNode; sub?: ReactNode }) {
  return (
    <div>
      <div className="row-n">{title}</div>
      {sub && <div className="row-s">{sub}</div>}
    </div>
  );
}

export function Row({ children }: { children: ReactNode }) {
  return <div className="row">{children}</div>;
}

export function RowM({ children }: { children: ReactNode }) {
  return <div className="row-m">{children}</div>;
}

export function Wf({
  label,
  variant,
  width,
  value,
  valueVariant,
}: {
  label: string;
  variant?: "r" | "w" | "s";
  width?: string;
  value: ReactNode;
  valueVariant?: Variant;
}) {
  const cls = valueVariant === "s" ? "up" : valueVariant === "r" ? "dn" : valueVariant === "w" ? "wa" : undefined;
  return (
    <div className="wf">
      <span className="wf-k">{label}</span>
      {width ? <Meter variant={variant} width={width} /> : <div />}
      <span className={`num${cls ? " " + cls : ""}`}>{value}</span>
    </div>
  );
}

export function ScopeBar({ items }: { items: [string, string][] }) {
  return (
    <div className="scope">
      {items.map(([k, v], i) => (
        <Fragment key={i}>
          {i > 0 && <div className="scope-sep" />}
          <div>
            <div className="scope-k">{k}</div>
            <div className="scope-v">{v}</div>
          </div>
        </Fragment>
      ))}
    </div>
  );
}
