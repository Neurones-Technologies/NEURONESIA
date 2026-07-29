import { CSSProperties } from "react";

type Span = 3 | 4 | 5 | 6 | 7 | 8 | 12;

/** Bloc scintillant de base — brique de tous les squelettes de chargement. */
export function Skel({
  width = "100%",
  height = 14,
  radius = 6,
  dark,
  style,
}: {
  width?: number | string;
  height?: number | string;
  radius?: number;
  dark?: boolean;
  style?: CSSProperties;
}) {
  return (
    <span
      className={`skel${dark ? " skel--dark" : ""}`}
      style={{ width, height, borderRadius: radius, ...style }}
      aria-hidden="true"
    />
  );
}

/** Reprend la forme du panneau `Brief` (bandeau sombre d'ouverture de vue). */
export function SkeletonBrief() {
  return (
    <div className="brief">
      <p className="brief-k">
        <Skel dark width={130} height={9} radius={3} />
      </p>
      <div style={{ display: "grid", gap: 10, marginBottom: 12 }}>
        <Skel dark width="72%" height={26} />
        <Skel dark width="46%" height={26} />
      </div>
      <ul className="brief-l">
        {[96, 90, 84, 74].map((w, i) => (
          <li key={i}>
            <Skel dark width={`${w}%`} height={13} />
          </li>
        ))}
      </ul>
      <div className="brief-r">
        {[110, 130, 150, 120].map((w, i) => (
          <Skel key={i} dark width={w} height={26} radius={999} />
        ))}
      </div>
    </div>
  );
}

/** Reprend la forme d'un `StatTile` (grand chiffre + lecture + sparkline). */
export function SkeletonStat({ span = 4 }: { span?: Span }) {
  return (
    <div className={`tile t${span}`}>
      <div className="tile-h">
        <Skel width={130} height={11} />
      </div>
      <Skel width={100} height={40} style={{ marginBottom: 12 }} />
      <Skel width={150} height={12} />
    </div>
  );
}

/** Reprend la forme d'une `Tile` générique (titre + lignes de contenu). */
export function SkeletonTile({ span = 12, lines = 4 }: { span?: Span; lines?: number }) {
  return (
    <div className={`tile t${span}`}>
      <div className="tile-h">
        <Skel width={170} height={13} />
      </div>
      <div style={{ display: "grid", gap: 11 }}>
        {Array.from({ length: lines }).map((_, i) => (
          <Skel key={i} width={`${94 - i * 9}%`} height={13} />
        ))}
      </div>
    </div>
  );
}

/** Squelette générique d'une page du cockpit : brief + grille bento. Sert de
 * repli le temps que la page (Server Component async) charge ses données. */
export function PageSkeleton() {
  return (
    <>
      <SkeletonBrief />
      <div className="bento">
        <SkeletonStat span={4} />
        <SkeletonStat span={4} />
        <SkeletonStat span={4} />
        <SkeletonTile span={12} lines={3} />
        <SkeletonTile span={7} lines={5} />
        <SkeletonTile span={5} lines={5} />
      </div>
    </>
  );
}

/** Squelette de toute la coque (rail + en-tête + contenu) — utilisé au tout
 * premier chargement, le temps que `[profile]/layout.tsx` résolve la session. */
export function ShellSkeleton() {
  return (
    <div className="app live">
      <nav className="rail" aria-hidden="true">
        <span className="rail-mk" />
        {Array.from({ length: 5 }).map((_, i) => (
          <span key={i} className="rl-skel" />
        ))}
        <div className="rail-sp" />
        <span className="skel" style={{ width: 38, height: 38, borderRadius: 12, background: "rgba(255,255,255,.08)" }} />
      </nav>
      <div className="stage">
        <header className="hdr">
          <Skel width={220} height={16} />
          <span style={{ marginLeft: "auto" }}>
            <Skel width={190} height={40} radius={999} />
          </span>
        </header>
        <main className="canvas">
          <PageSkeleton />
        </main>
      </div>
    </div>
  );
}
