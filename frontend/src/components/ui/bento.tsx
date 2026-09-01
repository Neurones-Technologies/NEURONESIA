import { ReactNode } from "react";
import { Variant } from "@/lib/types";
import { Aide } from "./aide";
import { Clickable, DetailCard } from "./detail";
import { LstRepli } from "./lst-repli";

type Span = 3 | 4 | 5 | 6 | 7 | 8 | 12;

/** Identifiant d'infobulle dérivé du titre, pour lier le `?` à son texte par
 * `aria-describedby`.
 *
 * Dérivé du titre plutôt que tiré d'un compteur : `useId` imposerait un
 * composant client, et un compteur de module donnerait des identifiants
 * différents entre le rendu serveur et l'hydratation. Les titres portent des
 * dates et des accents (« CA commandé 2026 au 17/08/2026 ») — d'où la
 * normalisation. */
function slugAide(titre: string): string {
  return titre
    .normalize("NFD")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 48);
}

export function Bento({ children }: { children: ReactNode }) {
  return <div className="bento">{children}</div>;
}

export function Tile({
  span = 12,
  title,
  kick,
  aide,
  quiet,
  rows,
  fill,
  children,
}: {
  span?: Span;
  title?: string;
  kick?: string;
  /** Ce que le bloc dit, en langage d'usage — rendu en infobulle « ? » après le
   *  titre (cf. ui/aide.tsx). Sans titre, il n'y a rien à annoter : l'aide est
   *  alors ignorée. */
  aide?: string;
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
      className={`tile t${span}${quiet ? " tile--q" : ""}${rows === 2 ? " tile--tall" : ""}${fill ? " tile--fill" : ""}`}
    >
      {(title || kick) && (
        <div className="tile-h">
          {title && (
            <h3>
              {title}
              {aide && <Aide id={slugAide(title)}>{aide}</Aide>}
            </h3>
          )}
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

/** Tuile d'indicateur : grand chiffre + lecture + histogramme de tendance. */
export function StatTile({
  span = 4,
  label,
  value,
  unit,
  aide,
  reading,
  readingVariant,
  spark,
  sparkAxis,
  sparkLabels,
  detail,
  rang = "secondaire",
  signeNeutre,
  fill,
}: {
  span?: Span;
  label: string;
  value: string;
  unit?: string;
  /** Ce que l'indicateur mesure, en langage d'usage — infobulle « ? » après le
   *  libellé (cf. ui/aide.tsx). Complète le tiroir `detail`, qui porte les
   *  chiffres corroborants : ici le sens, là la provenance. */
  aide?: string;
  reading?: string;
  readingVariant?: "pos" | "neg" | "wat";
  spark?: number[];
  sparkAxis?: string[];
  /** Libellé au survol de chaque barre (« Juil : 12 FCFA ») — même ordre que
   *  `spark`. Les hauteurs sont des indices relatifs au meilleur point : sans
   *  cette lecture, la valeur d'une barre est indevinable. */
  sparkLabels?: string[];
  detail?: DetailCard;
  rang?: RangStat;
  /** Coupe la coloration automatique du négatif. À poser quand un montant
   *  négatif est le régime normal de l'indicateur (une variation de trésorerie
   *  n'est pas une alerte), sans quoi l'écran crie en permanence. */
  signeNeutre?: boolean;
  /** Étire la tuile à la hauteur de sa rangée (cf. `Tile.fill`) : trois
   *  indicateurs côte à côte dont un seul porte une sparkline gardent ainsi le
   *  même cadre, au lieu de trois hauteurs différentes. */
  fill?: boolean;
}) {
  // Un montant négatif se lit d'abord au signe, pas à la ligne de lecture
  // dessous : « -1712 FCFA » en encre neutre se lisait comme un montant
  // ordinaire. La règle ne vaut que pour le vrai signe moins d'un nombre.
  const negatif = !signeNeutre && /^-\s*\d/.test(value.trim());
  // Une valeur TEXTUELLE (nom d'axe, libellé) n'est pas un montant : au corps
  // des chiffres elle déborde du cadre. Détection par le contenu — un montant
  // formaté ne porte que chiffres, espaces (y compris insécables d'Intl),
  // séparateurs et signes.
  const valeurTexte = !/^[\d\s  .,%+±/\-–—]*$/.test(value.trim());
  const body = (
    <>
      <div className="tile-h">
        <h3>
          {label}
          {aide && <Aide id={slugAide(label)}>{aide}</Aide>}
        </h3>
      </div>
      <div className="stat-l">
        <span className={`stat-v num${negatif ? " neg" : ""}${valeurTexte ? " stat-v--txt" : ""}`}>
          {value}
        </span>
        {unit && <span className="stat-u">{unit}</span>}
      </div>
      {reading && <div className={`stat-d${readingVariant ? " " + readingVariant : ""}`}>{reading}</div>}
      {spark && spark.length > 0 && (
        <div className="spark" aria-hidden="true">
          {/* L'infobulle vit sur la COLONNE (pleine hauteur), pas sur la barre :
              un mois à 4 % de hauteur serait impossible à survoler. Toutes les
              barres portent la teinte accent : la hauteur suffit à hiérarchiser,
              un surlignage partiel se lisait comme un signal à décoder. */}
          {spark.map((h, i) => (
            <span key={i} className="spark-c" title={sparkLabels?.[i]}>
              <i className="on" style={{ height: `${Math.max(4, h)}%` }} />
            </span>
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
  const cls = `tile t${span}${rang !== "secondaire" ? ` stat--${rang === "principal" ? "p" : "c"}` : ""}${fill ? " tile--fill" : ""}`;
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
