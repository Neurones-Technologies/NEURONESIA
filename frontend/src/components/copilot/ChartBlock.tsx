"use client";

/**
 * Rendu des blocs ```chart du Copilote.
 *
 * Le modèle décrit une série ({label, value}) et un type souhaité ; la FORME
 * affichée est décidée ici (cf. chooseForm dans chart-spec.ts), parce qu'un
 * camembert à deux parts ou un graphique à une barre se lisent moins bien que
 * la jauge ou le nombre qu'ils remplacent.
 *
 * PALETTE — validée, pas choisie à l'œil (méthode dataviz, six contrôles) :
 * ordre figé orange → vert → or → brique, sur surface blanche (fond `.ba`).
 * Les quatre teintes brutes de la charte échouaient : `--signal` (#1F6A55) et
 * `--watch` (#7C6224) passent sous le plancher de chroma (elles lisent gris en
 * aplat), et olive↔brique s'effondrent à ΔE 1,1 en deutéranopie — deux teintes
 * indiscernables pour un daltonien. Les pas retenus ci-dessous tiennent la même
 * famille de teintes en clarté relevée : pire paire adjacente ΔE 13,2 (protan)
 * et 21,6 (vision normale), plancher 8 et 15. La fermeture de l'anneau du donut
 * (brique↔orange, ΔE 28,4) a été validée séparément, la liste du validateur
 * étant linéaire alors qu'un anneau boucle.
 *
 * Orange (2,15:1) et or (2,65:1) passent sous 3:1 de contraste sur blanc : la
 * méthode l'autorise à condition d'une voie de secours — ici les valeurs
 * écrites en clair sur chaque marque ET le tableau de données dépliable. Ne
 * jamais retirer ces deux-là sans reprendre les teintes.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ChartForm,
  ChartSpec,
  MAX_MARKS,
  chooseForm,
  formatPercent,
  formatValue,
  parseChartSpec,
  seriesDecimals,
  unitCaption,
} from "./chart-spec";

const PALETTE = ["#F79C31", "#1F8A6C", "#C9971F", "#A4372A"];
/** Agrégat du reste : gris de mise en retrait, il ne consomme pas un créneau
 * catégoriel (la charte n'en a que quatre qui passent les contrôles).
 * Aligné sur `--line-2` des neutres froids : l'ancien gris (#D2CBBB) était
 * chaud et tirait au beige sur les surfaces bleutées de la nouvelle direction. */
const OTHER_FILL = "#C7D0DF";
const OTHER_LABEL = "Autres";

const SURFACE = "#FFFFFF"; // fond de la bulle `.ba` — la surface des anneaux/points

// ---------------------------------------------------------------------------
// Entrée
// ---------------------------------------------------------------------------

export function ChartBlock({ source, complete }: { source: string; complete: boolean }) {
  const spec = useMemo(() => (complete ? parseChartSpec(source) : null), [source, complete]);

  // Pendant le streaming, la spec est tronquée : afficher un repère discret
  // plutôt que le JSON en train de s'écrire.
  if (!complete) return <ChartPending />;

  // Bloc clos mais illisible : ne rien masquer — on replie le JSON dans un
  // dépliant au lieu de l'étaler ou de le supprimer.
  if (!spec) {
    return (
      <details className="viz-raw">
        <summary>Graphique illisible — voir la spec brute</summary>
        <pre>{source.trim()}</pre>
      </details>
    );
  }

  const form = chooseForm(spec);
  const shown = Math.min(spec.data.length, MAX_MARKS[form]);
  const caption = unitCaption(spec);

  return (
    <figure className="viz">
      {(spec.title || caption) && (
        <figcaption className="viz-head">
          {spec.title && <span className="viz-title">{spec.title}</span>}
          {caption && <span className="viz-unit">{caption}</span>}
        </figcaption>
      )}

      {form === "stat" && <StatFigure spec={spec} />}
      {form === "bars" && <BarsFigure spec={spec} count={shown} />}
      {form === "line" && <LineFigure spec={spec} count={shown} />}
      {form === "donut" && <DonutFigure spec={spec} count={shown} />}
      {form === "share" && <ShareFigure spec={spec} />}

      <Truncation spec={spec} form={form} shown={shown} />
      <DataTable spec={spec} form={form} />
    </figure>
  );
}

function ChartPending() {
  return (
    <div className="viz-pending" aria-busy="true" aria-label="Graphique en préparation">
      <span />
      <span />
      <span />
    </div>
  );
}

/** Ce qui n'est pas dessiné doit être dit — un « top 12 » silencieux se lit
 * comme un total. Le tableau, lui, porte toujours toutes les lignes. */
function Truncation({ spec, form, shown }: { spec: ChartSpec; form: ChartForm; shown: number }) {
  const hidden = spec.data.length - shown;
  if (hidden <= 0) return null;
  return (
    <p className="viz-note">
      {form === "donut"
        ? `Les ${hidden} plus petites parts sont regroupées sous « ${OTHER_LABEL} ».`
        : `${shown} premières valeurs sur ${spec.data.length} — les autres sont dans le tableau.`}
    </p>
  );
}

// ---------------------------------------------------------------------------
// Un seul point : le nombre EST le graphique
// ---------------------------------------------------------------------------

function StatFigure({ spec }: { spec: ChartSpec }) {
  const point = spec.data[0];
  return (
    <div className="viz-stat">
      <span className="viz-stat-v">{formatValue(point.value)}</span>
      {spec.unit && <span className="viz-stat-u">{spec.unit}</span>}
      <span className="viz-stat-l">{point.label}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Barres horizontales — une série, donc une seule teinte
// ---------------------------------------------------------------------------

function BarsFigure({ spec, count }: { spec: ChartSpec; count: number }) {
  const rows = spec.data.slice(0, count);
  const values = rows.map((r) => r.value);
  // Le domaine inclut toujours zéro : une barre part d'une ligne de base, sinon
  // sa longueur ne dit plus rien de la valeur.
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  const span = max - min || 1;
  const zeroPct = ((0 - min) / span) * 100;
  const hasNegative = min < 0;
  const decimals = seriesDecimals(values);

  return (
    <div className="viz-bars">
      {rows.map((row, i) => {
        const positive = row.value >= 0;
        const left = ((Math.min(row.value, 0) - min) / span) * 100;
        const width = Math.max(1.5, (Math.abs(row.value) / span) * 100);
        return (
          <div className="viz-bar-r" key={`${row.label}-${i}`} title={`${row.label} : ${formatValue(row.value, decimals)}${spec.unit ? ` ${spec.unit}` : ""}`}>
            <span className="viz-bar-n">{row.label}</span>
            <span className="viz-bar-t">
              {hasNegative && <i className="viz-bar-zero" style={{ left: `${zeroPct}%` }} />}
              <i
                className="viz-bar-f"
                style={{
                  left: `${left}%`,
                  width: `${width}%`,
                  background: PALETTE[0],
                  borderRadius: positive ? "0 4px 4px 0" : "4px 0 0 4px",
                }}
              />
            </span>
            <span className="viz-bar-v">{formatValue(row.value, decimals)}</span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Courbe — évolution dans le temps
// ---------------------------------------------------------------------------

/** Largeur réelle du conteneur : le tracé se calcule en pixels, jamais via un
 * viewBox étiré — un viewBox mis à l'échelle déforme aussi le texte des axes. */
function useWidth() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      setWidth(Math.round(w));
    });
    observer.observe(el);
    setWidth(Math.round(el.getBoundingClientRect().width));
    return () => observer.disconnect();
  }, []);

  return { ref, width };
}

/** Graduations arrondies (0 / 500 / 1 000) plutôt que les extrêmes bruts : ce
 * sont elles qui portent les valeurs qu'on ne labellise pas. */
function niceTicks(min: number, max: number, count = 3): number[] {
  if (min === max) return [min];
  const rawStep = (max - min) / (count - 1);
  const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rawStep) ?? magnitude * 10;
  const start = Math.floor(min / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + step / 2; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}

const PAD = { top: 12, right: 14, bottom: 24, left: 8 };
const PLOT_H = 150;

function LineFigure({ spec, count }: { spec: ChartSpec; count: number }) {
  const points = spec.data.slice(0, count);
  const { ref, width } = useWidth();
  const [active, setActive] = useState<number | null>(null);

  const values = points.map((p) => p.value);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const ticks = niceTicks(rawMin, rawMax);
  const yMin = Math.min(rawMin, ticks[0]);
  const yMax = Math.max(rawMax, ticks[ticks.length - 1]);
  const ySpan = yMax - yMin || 1;

  const decimals = seriesDecimals(values);
  // Les graduations gardent leur propre précision : arrondies par construction,
  // les aligner sur celle de la série afficherait « 0,00 ».
  const tickDecimals = seriesDecimals(ticks);

  // Réserve de gauche : la plus longue graduation, en approximation monospace
  // (6,5px par caractère à 10,5px) — mesurer le texte exigerait un rendu préalable.
  const tickTexts = ticks.map((t) => formatValue(t, tickDecimals));
  const left = PAD.left + Math.max(...tickTexts.map((t) => t.length)) * 6.5 + 8;
  const plotW = Math.max(0, width - left - PAD.right);
  const height = PAD.top + PLOT_H + PAD.bottom;

  // Fonctions de projection ordinaires : la mémoïsation manuelle est inutile ici
  // (le compilateur React s'en charge) et elle empêchait son optimisation.
  const x = (i: number) =>
    points.length === 1 ? left + plotW / 2 : left + (i / (points.length - 1)) * plotW;
  const y = (v: number) => PAD.top + PLOT_H - ((v - yMin) / ySpan) * PLOT_H;

  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");

  // Libellés directs choisis, jamais un nombre sur chaque point : le dernier
  // (où en est-on) et l'extrême (le point qui fait l'histoire). L'extrême est
  // abandonné s'il tombe trop près du dernier : deux nombres qui se chevauchent
  // valent moins qu'un seul lisible (on ne les décale pas, ça les détacherait
  // de leur point).
  const lastIdx = points.length - 1;
  const maxIdx = values.indexOf(rawMax);
  const labelled = Math.abs(x(maxIdx) - x(lastIdx)) < 56 ? [lastIdx] : [maxIdx, lastIdx];

  // Libellés d'axe X éclaircis quand ils ne tiennent pas (~54px chacun), en
  // remontant depuis le dernier : l'espacement reste régulier et le point
  // d'arrivée est toujours nommé.
  const xEvery = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(plotW / 54))));
  const xShown = new Set<number>();
  for (let i = lastIdx; i >= 0; i -= xEvery) xShown.add(i);

  const onMove = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!plotW) return;
    const box = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - box.left;
    const ratio = (px - left) / plotW;
    const idx = Math.round(ratio * (points.length - 1));
    setActive(Math.max(0, Math.min(points.length - 1, idx)));
  };

  return (
    <div className="viz-line" ref={ref}>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={spec.title || "Courbe"}
          onPointerMove={onMove}
          onPointerLeave={() => setActive(null)}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={left} x2={left + plotW} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth={1} />
              <text x={left - 8} y={y(t) + 3.5} textAnchor="end" className="viz-tick">
                {formatValue(t, tickDecimals)}
              </text>
            </g>
          ))}

          {points.map((p, i) =>
            xShown.has(i) ? (
              <text key={`x-${i}`} x={x(i)} y={PAD.top + PLOT_H + 16} textAnchor="middle" className="viz-tick">
                {p.label}
              </text>
            ) : null
          )}

          {active !== null && (
            <line
              x1={x(active)}
              x2={x(active)}
              y1={PAD.top}
              y2={PAD.top + PLOT_H}
              stroke="var(--line-2)"
              strokeWidth={1}
            />
          )}

          <path d={path} fill="none" stroke={PALETTE[0]} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

          {points.map((p, i) => {
            const isMarker = points.length <= 12 || i === 0 || i === lastIdx || i === active;
            if (!isMarker) return null;
            return (
              <circle
                key={`m-${i}`}
                cx={x(i)}
                cy={y(p.value)}
                r={i === active ? 5 : 4}
                fill={PALETTE[0]}
                stroke={SURFACE}
                strokeWidth={2}
              />
            );
          })}

          {labelled.map((i) => (
            <text
              key={`l-${i}`}
              x={x(i)}
              // Un point atteint en descendant porte son libellé DESSOUS : au
              //-dessus, le tracé lui passe au travers.
              y={y(points[i].value) + (i > 0 && points[i].value < points[i - 1].value ? 17 : -10)}
              textAnchor={i === lastIdx && points.length > 1 ? "end" : "middle"}
              className="viz-point-v"
            >
              {formatValue(points[i].value, decimals)}
            </text>
          ))}

          {/* Cibles de survol et de focus clavier : 24px minimum, bien plus larges
              que le point de 8px, sinon personne ne les atteint. */}
          {points.map((p, i) => (
            <rect
              key={`hit-${i}`}
              x={x(i) - 12}
              y={PAD.top}
              width={24}
              height={PLOT_H}
              fill="transparent"
              tabIndex={0}
              role="button"
              aria-label={`${p.label} : ${formatValue(p.value, decimals)}${spec.unit ? ` ${spec.unit}` : ""}`}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
            />
          ))}
        </svg>
      )}

      {active !== null && points[active] && (
        <p className="viz-readout">
          <b>
            {formatValue(points[active].value, decimals)}
            {spec.unit ? ` ${spec.unit}` : ""}
          </b>
          <span>{points[active].label}</span>
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Anneau — part à tout, 3 à 4 parts + agrégat
// ---------------------------------------------------------------------------

interface Slice {
  label: string;
  value: number;
  fill: string;
}

function buildSlices(spec: ChartSpec, count: number): Slice[] {
  const ordered = [...spec.data].sort((a, b) => b.value - a.value);
  const head = ordered.slice(0, count).map((d, i) => ({ ...d, fill: PALETTE[i % PALETTE.length] }));
  const tail = ordered.slice(count);
  if (!tail.length) return head;
  return [...head, { label: OTHER_LABEL, value: tail.reduce((s, d) => s + d.value, 0), fill: OTHER_FILL }];
}

const RING = { size: 168, stroke: 20 };

function DonutFigure({ spec, count }: { spec: ChartSpec; count: number }) {
  const slices = buildSlices(spec, count);
  const total = slices.reduce((s, d) => s + d.value, 0);
  const decimals = seriesDecimals(slices.map((s) => s.value));
  const [active, setActive] = useState<number | null>(null);

  const radius = (RING.size - RING.stroke) / 2;
  const circumference = 2 * Math.PI * radius;

  // Longueurs et décalages cumulés calculés d'un coup : un compteur incrémenté
  // dans le `map` serait une mutation pendant le rendu.
  const arcs = slices.reduce<{ slice: Slice; length: number; offset: number }[]>((acc, slice) => {
    const previous = acc[acc.length - 1];
    const offset = previous ? previous.offset + previous.length : 0;
    return [...acc, { slice, length: total ? (slice.value / total) * circumference : 0, offset }];
  }, []);

  const center = RING.size / 2;

  return (
    <div className="viz-donut">
      <svg width={RING.size} height={RING.size} role="img" aria-label={spec.title || "Répartition"}>
        <g transform={`rotate(-90 ${center} ${center})`}>
          {arcs.map(({ slice, length, offset }, i) => {
            // 2px de surface séparent deux parts : c'est le vide qui sépare, pas
            // un contour dessiné autour de chaque arc.
            const drawn = Math.max(0, length - 2);
            return (
              <circle
                key={`${slice.label}-${i}`}
                cx={center}
                cy={center}
                r={radius}
                fill="none"
                stroke={slice.fill}
                strokeWidth={RING.stroke}
                strokeDasharray={`${drawn} ${circumference - drawn}`}
                strokeDashoffset={-offset}
                // La part survolée ressort ; les autres reculent d'un cran
                // seulement. Plus bas, elles se délavent et l'anneau perd son
                // identité de couleur au lieu de la mettre en avant.
                opacity={active === null || active === i ? 1 : 0.72}
                // Les cinq cercles se superposent sur TOUT l'anneau (les
                // pointillés ne masquent que la peinture, pas la géométrie) :
                // laisser le survol dessus désignerait la mauvaise part. Les
                // secteurs invisibles ci-dessous sont la surface de survol.
                style={{ pointerEvents: "none" }}
              />
            );
          })}

          {/* Cibles de survol : un secteur par part, trou compris — bien plus
              large que l'arc peint, et sans ambiguïté sur la part visée. */}
          {arcs.map(({ slice, length, offset }, i) => {
            if (length <= 0) return null;
            const a0 = (offset / circumference) * 2 * Math.PI;
            const a1 = a0 + Math.min((length / circumference) * 2 * Math.PI, 2 * Math.PI - 0.001);
            const outer = radius + RING.stroke / 2;
            const px = (r: number, a: number) => `${(center + r * Math.cos(a)).toFixed(2)},${(center + r * Math.sin(a)).toFixed(2)}`;
            const largeArc = a1 - a0 > Math.PI ? 1 : 0;
            const wedge = `M${px(0, a0)} L${px(outer, a0)} A${outer} ${outer} 0 ${largeArc} 1 ${px(outer, a1)} Z`;
            return (
              <path
                key={`hit-${slice.label}-${i}`}
                d={wedge}
                fill="transparent"
                // `pointerEvents: all` explicite : le défaut (`visiblePainted`)
                // fait dépendre le survol d'un aplat que l'on veut invisible.
                style={{ pointerEvents: "all" }}
                onPointerEnter={() => setActive(i)}
                onPointerLeave={() => setActive(null)}
              >
                <title>{`${slice.label} : ${formatValue(slice.value, decimals)}${spec.unit ? ` ${spec.unit}` : ""} (${formatPercent(slice.value, total)})`}</title>
              </path>
            );
          })}
        </g>
      </svg>

      {/* La légende est la voie d'identité : jamais la couleur seule, et elle
          porte les valeurs que les arcs ne peuvent pas écrire lisiblement. */}
      <ul className="viz-legend">
        {slices.map((slice, i) => (
          <li
            key={`${slice.label}-${i}`}
            onPointerEnter={() => setActive(i)}
            onPointerLeave={() => setActive(null)}
            className={active === i ? "on" : undefined}
          >
            <i style={{ background: slice.fill }} />
            <span className="viz-legend-n">{slice.label}</span>
            <b>{formatValue(slice.value, decimals)}</b>
            <span className="viz-legend-p">{formatPercent(slice.value, total)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Deux parts — une jauge, pas un camembert coupé en deux
// ---------------------------------------------------------------------------

function ShareFigure({ spec }: { spec: ChartSpec }) {
  const [first, second] = spec.data;
  const total = first.value + second.value;
  const pct = total ? (first.value / total) * 100 : 0;
  const decimals = seriesDecimals([first.value, second.value]);

  return (
    <div className="viz-share">
      <div className="viz-share-t">
        <i style={{ width: `calc(${pct}% - 1px)`, background: PALETTE[0] }} />
        <i style={{ width: `calc(${100 - pct}% - 1px)`, background: PALETTE[1] }} />
      </div>
      <ul className="viz-legend">
        {[first, second].map((point, i) => (
          <li key={`${point.label}-${i}`}>
            <i style={{ background: PALETTE[i] }} />
            <span className="viz-legend-n">{point.label}</span>
            <b>{formatValue(point.value, decimals)}</b>
            <span className="viz-legend-p">{formatPercent(point.value, total)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Jumeau tabulaire — toute valeur reste atteignable sans survol ni couleur
// ---------------------------------------------------------------------------

function DataTable({ spec, form }: { spec: ChartSpec; form: ChartForm }) {
  if (form === "stat") return null;
  const partToWhole = form === "donut" || form === "share";
  const total = spec.data.reduce((s, d) => s + d.value, 0);
  const decimals = seriesDecimals(spec.data.map((d) => d.value));

  return (
    <details className="viz-data">
      <summary>Voir les données</summary>
      <div style={{ overflowX: "auto" }}>
        <table className="tb">
          <thead>
            <tr>
              <th>Libellé</th>
              <th>{spec.unit ? `Valeur (${spec.unit})` : "Valeur"}</th>
              {partToWhole && <th>Part</th>}
            </tr>
          </thead>
          <tbody>
            {spec.data.map((point, i) => (
              <tr key={`${point.label}-${i}`}>
                <td>{point.label}</td>
                <td className="mono">{formatValue(point.value, decimals)}</td>
                {partToWhole && <td className="mono">{formatPercent(point.value, total)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
