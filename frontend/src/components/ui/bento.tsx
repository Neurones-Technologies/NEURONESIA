import { ReactNode } from "react";
import { Variant } from "@/lib/types";
import { Clickable, DetailCard } from "./detail";
import { LstRepli } from "./lst-repli";

type Span = 3 | 4 | 5 | 6 | 7 | 8 | 12;

export function Bento({ children }: { children: ReactNode }) {
  return <div className="bento">{children}</div>;
}

export function Tile({
  span = 12,
  col,
  title,
  kick,
  quiet,
  rows,
  fill,
  children,
}: {
  span?: Span;
  /** Colonne de départ (1 à 12), quand la tuile doit se placer sous une voisine
   *  précise plutôt que combler le premier trou de la grille.
   *
   *  La grille remplit de gauche à droite : une tuile de 5 colonnes placée après
   *  une tuile de 7 remonte automatiquement dans la gouttière de gauche laissée
   *  libre, ce qui la met sous la MAUVAISE voisine. `col={8}` la cale sous une
   *  tuile de droite (7 + 1). À n'utiliser que là où la colonne porte du sens ;
   *  sans cette prop, le comportement de remplissage est inchangé. */
  col?: number;
  title?: string;
  kick?: string;
  quiet?: boolean;
  /** `2` : la tuile tient la hauteur de deux rangées, pour faire face à une
   *  colonne de deux tuiles empilées. Sans valeur, comportement d'avant. */
  rows?: 2;
  /** Étire la tuile à la hauteur de sa rangée, pour qu'elle ait le même cadre que
   *  sa voisine malgré un contenu plus court. */
  fill?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      className={`tile t${span}${quiet ? " tile--q" : ""}${rows === 2 ? " tile--tall" : ""}${fill ? " tile--fill" : ""}${col ? " tile--col" : ""}`}
      // `gridColumn` en style inline plutôt qu'une classe : la colonne de départ
      // est une décision de MISE EN PAGE d'un écran précis, pas un jeton du
      // système — douze classes `.c1`…`.c12` pour deux appels seraient du poids
      // mort dans la feuille de styles.
      //
      // La classe `tile--col` l'accompagne pour que les points de rupture
      // puissent ANNULER ce calage (cf. globals.css) : un style inline l'emporte
      // sur les règles de `@media`, et la tuile resterait sinon coincée en
      // colonne 8 sur un écran qui n'a plus qu'une colonne.
      style={col ? { gridColumn: `${col} / span ${span}` } : undefined}
    >
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
      {/* Marque « texte généré par l'IA », en haut à droite du panneau.
          Le tracé est celui de l'icône Copilote du rail (cf. shell/Rail.tsx) :
          l'étincelle désigne déjà l'IA ailleurs dans l'interface, un second
          dessin pour la même idée ferait deux vocabulaires.
          `title` plutôt que `aria-hidden` : l'origine du texte est une
          information, pas une décoration — elle doit être lisible au lecteur
          d'écran comme au survol. */}
      <svg className="brief-ia" viewBox="0 0 24 24" role="img" aria-label="Généré par l'IA">
        <title>Généré par l&apos;IA</title>
        <path d="M12 3l1.9 4.9L19 9.8l-5.1 1.9L12 17l-1.9-5.3L5 9.8l5.1-1.9zM18 15.5l.9 2.3 2.1.8-2.1.8-.9 2.1-.9-2.1-2.1-.8 2.1-.8z" />
      </svg>
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

/** Rang de lecture d'un indicateur dans un bandeau.
 *
 * Quatre indicateurs de taille rigoureusement identique ne désignent aucun
 * premier : le lecteur doit lire les quatre libellés pour trouver celui qui
 * compte. Le rang porte cette hiérarchie sans rien retirer de l'écran — un
 * indicateur de couverture ou de fiabilité passe en `contexte`, il n'est pas
 * supprimé.
 *
 * `secondaire` est le défaut et reproduit exactement le rendu antérieur : un
 * écran qui n'a pas encore été hiérarchisé ne change pas d'apparence. */
export type RangStat = "principal" | "secondaire" | "contexte";

/** Cadran de mesure d'une tuile d'indicateur.
 *
 * `pct` est la course de l'arc, de 0 à 100. Le cadran ne doit être posé que
 * lorsqu'une PROPORTION a du sens — une part, un taux, une couverture : un
 * montant absolu n'a pas de borne, et son arc ne voudrait rien dire.
 *
 * `ton` colore l'arc. Sans valeur, c'est l'orange de marque ; `volt` désigne
 * une valeur CALCULÉE (indice, score, projection), les autres reprennent les
 * verdicts habituels de l'interface. */
export interface CadranStat {
  pct: number;
  ton?: "s" | "r" | "w" | "v";
}

/** Arc gradué d'une tuile d'indicateur — SVG serveur, sans dépendance.
 *
 * Le cercle de valeur est tracé par `stroke-dasharray` sur une circonférence
 * connue : pas de calcul de chemin, pas de JS. La rotation de -90° (portée par
 * le CSS) fait partir l'arc du haut du cadran plutôt que de sa droite. */
function Cadran({ pct, ton }: CadranStat) {
  const R = 40;
  const C = 2 * Math.PI * R; // ≈ 251,3
  const borne = Math.max(0, Math.min(100, pct));
  const course = (borne / 100) * C;
  // À ZÉRO, l'arc ne doit rien peindre. Le trait est en `stroke-linecap:round`
  // (une valeur faible reste visible plutôt que de disparaître) : à 0, ce même
  // arrondi laissait un point orange en haut du cadran, qui se lit comme une
  // valeur minuscule alors que la mesure est nulle. Constaté sur l'écran DC
  // « Marché » : « 0 signal sur 0 collecté » affichait une amorce d'arc.
  const vide = borne === 0;
  // Douze crans, un par heure de cadran : posés sur le cercle par rotation,
  // ce qui évite d'écrire douze paires de coordonnées à la main.
  const crans = Array.from({ length: 12 }, (_, i) => i * 30);
  return (
    <div className={`dialg${ton ? ` dialg--${ton}` : ""}`} aria-hidden="true">
      <svg viewBox="0 0 100 100">
        <circle className="dialg-t" cx="50" cy="50" r={R} />
        {!vide && (
          <circle
            className="dialg-v"
            cx="50"
            cy="50"
            r={R}
            strokeDasharray={`${course.toFixed(1)} ${(C - course).toFixed(1)}`}
          />
        )}
        <g className="dialg-c">
          {crans.map((a) => (
            <line key={a} x1="50" y1="4" x2="50" y2="9" transform={`rotate(${a} 50 50)`} />
          ))}
        </g>
      </svg>
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
  rang = "secondaire",
  signeNeutre,
  cadran,
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
  rang?: RangStat;
  /** Coupe la coloration automatique du négatif. À poser quand un montant
   *  négatif est le régime normal de l'indicateur (une variation de trésorerie
   *  n'est pas une alerte), sans quoi l'écran crie en permanence. */
  signeNeutre?: boolean;
  /** Arc gradué à gauche du chiffre. Omis : la tuile garde sa mise en page
   *  d'origine — le cadran ne s'allume que là où une proportion a du sens. */
  cadran?: CadranStat;
}) {
  // Un montant négatif se lit d'abord au signe, pas à la ligne de lecture
  // dessous : « -1712 M FCFA » en encre neutre se lisait comme un montant
  // ordinaire. La règle ne vaut que pour le vrai signe moins d'un nombre.
  const negatif = !signeNeutre && /^-\s*\d/.test(value.trim());
  // Le cadran se pose À GAUCHE du bloc chiffré, jamais autour de lui : le
  // libellé, le chiffre et la lecture gardent leur ordre et leur taille, et
  // une tuile sans cadran rend exactement l'arbre d'avant (pas de `.stat-w`).
  const chiffre = (
    <>
      <div className="tile-h">
        <h3>{label}</h3>
      </div>
      <div className="stat-l">
        <span className={`stat-v num${negatif ? " neg" : ""}`}>{value}</span>
        {unit && <span className="stat-u">{unit}</span>}
      </div>
      {reading && <div className={`stat-d${readingVariant ? " " + readingVariant : ""}`}>{reading}</div>}
    </>
  );
  const body = (
    <>
      {cadran ? (
        <div className="stat-w">
          <Cadran pct={cadran.pct} ton={cadran.ton} />
          <div>{chiffre}</div>
        </div>
      ) : (
        chiffre
      )}
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
  const cls = `tile t${span}${rang !== "secondaire" ? ` stat--${rang === "principal" ? "p" : "c"}` : ""}`;
  if (!detail) return <div className={cls}>{body}</div>;
  return (
    <Clickable className={cls} detail={detail}>
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

/** Barres classées d'un écran.
 *
 * `replierApres` replie la queue derrière une bascule « Voir les N autres », même
 * mécanique que `Lst` (cf. ui/lst-repli.tsx). Option et non défaut : les autres
 * appels affichent des listes déjà coupées à la source. */
export function Bars({
  rows,
  replierApres,
  nom,
}: {
  rows: BarRow[];
  /** Nombre de barres visibles avant repli. Omis : toutes, comme avant. */
  replierApres?: number;
  /** Nom des lignes au pluriel, pour le libellé de la bascule. */
  nom?: string;
}) {
  const lignes = rows.map((r, i) => {
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
  });

  return (
    <div className="bars">
      {replierApres !== undefined ? (
        <LstRepli lignes={lignes} visibles={replierApres} nom={nom} />
      ) : (
        lignes
      )}
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

/** Liste numérotée d'un écran.
 *
 * `replierApres` replie la queue derrière une bascule « Voir les N autres »
 * (cf. ui/lst-repli.tsx). Option et non comportement par défaut : la trentaine
 * d'appels existants affichent des listes déjà coupées à la source par un
 * `.slice()`, et les replier d'office cacherait des lignes que l'écran annonce
 * comme affichées. Sans cette prop, le rendu est celui d'avant — entièrement
 * serveur, sans JavaScript. */
export function Lst({
  items,
  replierApres,
  nom,
}: {
  items: LstItem[];
  /** Nombre de lignes visibles avant repli. Omis : liste entière, comme avant. */
  replierApres?: number;
  /** Nom des lignes au pluriel, pour le libellé de la bascule. */
  nom?: string;
}) {
  const lignes = items.map((it, i) => {
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
  });

  return (
    <div className="lst">
      {replierApres !== undefined ? (
        <LstRepli lignes={lignes} visibles={replierApres} nom={nom} />
      ) : (
        lignes
      )}
    </div>
  );
}

export interface OrbitPart {
  /** Nom de la part, tel qu'il s'affiche en légende. */
  name: string;
  /** Valeur formatée (montant, effectif) — la légende l'affiche telle quelle. */
  value: string;
  /** Course de l'arc, de 0 à 100. Sert AUSSI de chiffre en légende, sauf si
   *  `pctLabel` est fourni. */
  pct: number;
  /** Chiffre à écrire en légende, quand il diffère de la course de l'arc.
   *
   *  Sert aux répartitions PEU CONCENTRÉES : sur 650 comptes, les premiers
   *  pèsent 11 %, 5 %, 5 % — des arcs tracés sur une course de 100 % y sont
   *  illisibles. On rapporte alors les arcs au premier rang (`pct`) pour que la
   *  comparaison se voie, tout en écrivant la part réelle du total
   *  (`pctLabel`). L'arc donne le rapport, le chiffre donne la mesure. */
  pctLabel?: number;
  /** Teinte de la pastille et de l'arc. Doit venir de `chart-palette.ts`. */
  couleur: string;
  detail?: DetailCard;
}

/** Répartition d'un total en anneaux concentriques.
 *
 * Les TROIS PREMIÈRES parts sont tracées, une par anneau : le rayon code le
 * rang, l'arc code la part. La légende, elle, porte toutes les parts — rien
 * n'est retiré de la lecture, seul le dessin est borné (cf. `.orbit` dans
 * globals.css pour le pourquoi de cette limite).
 *
 * Attend une liste DÉJÀ TRIÉE, du plus grand au plus petit : l'anneau extérieur
 * doit être la part dominante, sans quoi le rang cesse de vouloir dire quelque
 * chose. */
export function Orbit({ parts }: { parts: OrbitPart[] }) {
  // Trois rayons décroissants, épaisseur de trait 11 : l'écart de 13 laisse
  // 2 px de respiration entre deux anneaux voisins.
  const RAYONS = [44, 31, 18];
  const traces = parts.slice(0, RAYONS.length);
  return (
    <div className="orbit">
      <div className="orbit-g" aria-hidden="true">
        <svg viewBox="0 0 100 100">
          {traces.map((p, i) => {
            const r = RAYONS[i];
            const c = 2 * Math.PI * r;
            const course = (Math.max(0, Math.min(100, p.pct)) / 100) * c;
            return (
              <g key={p.name}>
                <circle className="orbit-t" cx="50" cy="50" r={r} />
                {course > 0 && (
                  <circle
                    className="orbit-a"
                    cx="50"
                    cy="50"
                    r={r}
                    stroke={p.couleur}
                    strokeDasharray={`${course.toFixed(1)} ${(c - course).toFixed(1)}`}
                  />
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <ul className="orbit-lg">
        {parts.map((p) => {
          const ligne = (
            <>
              <i style={{ background: p.couleur }} aria-hidden="true" />
              <span className="orbit-n">{p.name}</span>
              <b>{p.value}</b>
              <span className="orbit-p">{(p.pctLabel ?? p.pct).toFixed(0)} %</span>
            </>
          );
          return p.detail ? (
            <Clickable key={p.name} as="li" className="clk" detail={p.detail}>
              {ligne}
            </Clickable>
          ) : (
            <li key={p.name}>{ligne}</li>
          );
        })}
      </ul>
    </div>
  );
}

export function FootNote({ children }: { children: ReactNode }) {
  return <p className="foot-n">{children}</p>;
}

/** Pied de liste tronquée : dit combien de lignes ne sont pas affichées.
 *
 * Les listes des écrans sont coupées à 5, 6, 8 ou 10 lignes par un `.slice()`.
 * Sans mention, l'écran se lit comme exhaustif : sur les comptes du portefeuille,
 * « 650 comptes classés » côtoyait une liste de 8 lignes sans que rien ne dise où
 * étaient passés les 642 autres. Le total est déjà connu du composant appelant —
 * il ne coûte qu'une ligne de le publier.
 *
 * Ne rend rien quand la liste est complète : pas de « et 0 autres ». */
export function Reste({
  affiches,
  total,
  nom = "lignes",
  /** Où retrouver le reste, quand une autre vue le porte. */
  ou,
}: {
  affiches: number;
  total: number;
  nom?: string;
  ou?: string;
}) {
  const reste = total - affiches;
  if (reste <= 0) return null;
  // Formulation sans accord : `nom` est fourni par l'appelant et peut être des
  // deux genres (« comptes », « créances »).
  return (
    <p className="reste">
      {affiches} {nom} sur {total} · reste {reste}
      {ou ? ` · ${ou}` : ""}
    </p>
  );
}

export function HintLine({ children }: { children: ReactNode }) {
  return (
    <p className="hintline">
      <i />
      {children}
    </p>
  );
}
