import { ReactNode } from "react";

/** Primitives de graphe du cockpit — SVG rendu côté SERVEUR, sans dépendance.
 *
 * Trois raisons de ne pas embarquer une bibliothèque de graphes :
 *
 * 1. les écrans qui les utilisent sont des composants serveur (cf. views/vision) ;
 *    une bibliothèque de rendu client les ferait basculer en client, avec le JS et
 *    la latence d'hydratation que cela suppose, pour dessiner des lignes ;
 * 2. le système de dessin de la maquette (traits fins, gris récessifs, papier)
 *    demanderait autant de configuration à neutraliser les styles par défaut d'une
 *    bibliothèque qu'à tracer les chemins ;
 * 3. ces graphes lisent des séries de 6 à 30 points. Le calcul d'échelle tient en
 *    quinze lignes.
 *
 * SPÉCIFICATIONS DE TRACÉ, tenues ici et nulle part ailleurs :
 * - lignes 2 px, jointures et extrémités arrondies ;
 * - marqueurs ≥ 8 px de diamètre, cerclés de 2 px dans la couleur du fond pour
 *   rester lisibles quand ils se croisent ;
 * - colonnes ≤ 24 px, sommet arrondi 4 px, base carrée sur la ligne de référence ;
 * - aires empilées séparées par un filet de 2 px dans la couleur du fond — c'est
 *   le blanc qui sépare, jamais une bordure autour de la forme ;
 * - grille et axes en filet plein d'un pas au-dessus du fond, jamais en pointillé
 *   (le pointillé signifie « seuil » ou « projection », il ne doit pas signifier
 *   « grille ») ;
 * - étiquettes en encre de texte, jamais dans la couleur de la série : une teinte
 *   claire est illisible en texte, et l'identité vient de la pastille à côté.
 *
 * ACCESSIBILITÉ. Chaque point porte un `<title>` — l'infobulle native du
 * navigateur, qui ne coûte pas un octet de JS. Et chaque graphe est doublé d'une
 * VUE TABLEAU : les écrans passent la série au tiroir de détail, où elle est lue
 * ligne à ligne. Aucune valeur n'est accessible seulement au survol.
 *
 * COULEURS. Elles arrivent en paramètre, jamais choisies ici. Les valeurs
 * autorisées sont dans `chart-palette.ts`, validées par le script du référentiel
 * de visualisation (bande de clarté, plancher de chroma, séparation daltonienne,
 * contraste sur le fond). */

export const CHART = {
  /** Repère de dessin. Le viewBox est fixe et le SVG s'étire : les proportions
   * restent tenues quelle que soit la largeur de la tuile. */
  w: 720,
  h: 240,
  padL: 52,
  padR: 46,
  padT: 14,
  padB: 30,
} as const;

const AXE = "var(--line-2)";
const GRILLE = "var(--hair)";
const ENCRE_2 = "var(--t2)";
const ENCRE_3 = "var(--t3)";
const FOND = "var(--card)";

export interface PointSerie {
  /** Libellé d'abscisse (mois court, exercice…). */
  x: string;
  y: number | null;
  /** Faux quand la donnée du point est incomplète : tracé en pointillé et exclu
   * des étiquettes. Sert au cas des règlements non encore synchronisés. */
  fiable?: boolean;
  /** Texte de l'infobulle native. */
  info?: string;
}

export interface SerieLigne {
  cle: string;
  libelle: string;
  couleur: string;
  points: PointSerie[];
  /** Trait discontinu de bout en bout — réservé aux repères (droite de rythme,
   * cible), jamais à une série mesurée. */
  repere?: boolean;
  /** Remplit sous la courbe (lavis à 10 %). Réservé à une série unique. */
  aire?: boolean;
  /** Étiquette la dernière valeur au bout du tracé. */
  etiquetteFin?: string;
}

function echelle(series: SerieLigne[], zeroBase: boolean) {
  const valeurs = series.flatMap((s) => s.points.map((p) => p.y).filter((v): v is number => v !== null));
  if (valeurs.length === 0) return { min: 0, max: 1 };
  const brutMax = Math.max(...valeurs);
  const brutMin = Math.min(...valeurs);
  const max = brutMax === brutMin ? brutMax * 1.1 || 1 : brutMax;
  const min = zeroBase ? Math.min(0, brutMin) : brutMin - (max - brutMin) * 0.12;
  return { min, max: max + (max - min) * 0.08 };
}

/** Ticks « propres » : 4 graduations rondes plutôt que des bornes exactes. */
function graduations(min: number, max: number, n = 4): number[] {
  const brut = (max - min) / n;
  const magnitude = Math.pow(10, Math.floor(Math.log10(Math.abs(brut) || 1)));
  const pas = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((p) => p >= brut) ?? magnitude * 10;
  const debut = Math.ceil(min / pas) * pas;
  const out: number[] = [];
  for (let v = debut; v <= max; v += pas) out.push(Number(v.toFixed(6)));
  return out;
}

/** Prolongement calculé d'une série mesurée.
 *
 * `points` sont les abscisses PROJETÉES, dans le prolongement de la série. Le
 * tracé part du dernier point mesuré : la projection est raccordée, jamais
 * flottante.
 *
 * `bas`/`haut`, si fournis, dessinent le CÔNE d'incertitude — l'enveloppe des
 * valeurs possibles, qui s'ouvre avec l'horizon. Les trois tableaux doivent
 * avoir la même longueur. */
export interface Projection {
  points: number[];
  bas?: number[];
  haut?: number[];
  /** Libellés d'abscisse des points projetés, pour l'axe horizontal. */
  abscisses?: string[];
  /** Nom du tracé en légende. */
  libelle?: string;
}

/** Graphe de lignes — tendance dans le temps.
 *
 * `reference` trace un seuil (cible de DSO, budget) : discontinu, en gris, sans
 * marqueur — il ne doit jamais se confondre avec une mesure.
 *
 * `projection` prolonge la PREMIÈRE série au-delà du mesuré. Le calculé s'y
 * distingue par TROIS marques simultanées — teinte cyan (`--volt-strong`, la
 * couleur de ce que la machine déduit), trait pointillé, et un cône
 * d'incertitude qui s'ouvre. Trois et non une seule : la couleur seule tombe
 * sous daltonisme et en niveaux de gris, et le pointillé seul se confondrait
 * avec le trait de `reference`. Confondre mesuré et projeté est le défaut le
 * plus coûteux d'un graphe de cockpit — il fait prendre une extrapolation pour
 * un relevé. */
export function LineChart({
  series,
  formatY,
  reference,
  projection,
  zeroBase = true,
  hauteur,
  legende = true,
}: {
  series: SerieLigne[];
  formatY: (v: number) => string;
  reference?: { valeur: number; libelle: string };
  projection?: Projection;
  zeroBase?: boolean;
  hauteur?: number;
  legende?: boolean;
}) {
  const h = hauteur ?? CHART.h;
  // L'échelle doit englober le seuil ET la projection (cône compris) : sinon la
  // courbe projetée sort du cadre, ou le cône est rogné par le haut.
  const bornes: SerieLigne[] = [...series];
  if (reference) {
    bornes.push({ cle: "_ref", libelle: "", couleur: "", points: [{ x: "", y: reference.valeur }] });
  }
  if (projection) {
    const extremes = [...projection.points, ...(projection.bas ?? []), ...(projection.haut ?? [])];
    bornes.push({
      cle: "_prj",
      libelle: "",
      couleur: "",
      points: extremes.map((y) => ({ x: "", y })),
    });
  }
  const { min, max } = echelle(bornes, zeroBase);
  // Les abscisses projetées prolongent l'axe : la largeur du tracé se partage
  // entre le mesuré et le projeté, ce qui garde un pas régulier entre tous les
  // points. `nMes` reste l'index du dernier point mesuré — le raccord.
  const nMes = Math.max(...series.map((s) => s.points.length), 1);
  const nPrj = projection?.points.length ?? 0;
  const n = nMes + nPrj;
  const plotW = CHART.w - CHART.padL - CHART.padR;
  const plotH = h - CHART.padT - CHART.padB;
  const px = (i: number) => CHART.padL + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const py = (v: number) => CHART.padT + plotH - ((v - min) / (max - min || 1)) * plotH;

  const ticks = graduations(min, max);
  const abscisses = series[0]?.points ?? [];
  // Une graduation d'abscisse sur k, pour que les libellés ne se chevauchent pas.
  const pasX = Math.max(1, Math.ceil(n / 8));
  // Le dernier point n'est étiqueté que s'il ne colle pas au précédent : sur une
  // série de 30 mois, « juil. 2026 » et « août 2026 » se chevauchaient et se
  // lisaient comme un seul libellé illisible.
  const montreDernier = (n - 1) % pasX >= Math.ceil(pasX / 2);

  return (
    <div className="cht">
      <svg viewBox={`0 0 ${CHART.w} ${h}`} className="cht-svg" role="img" preserveAspectRatio="none">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={CHART.padL} x2={CHART.w - CHART.padR} y1={py(t)} y2={py(t)} stroke={GRILLE} strokeWidth={1} />
            <text x={CHART.padL - 8} y={py(t) + 3.5} textAnchor="end" className="cht-tick">
              {formatY(t)}
            </text>
          </g>
        ))}
        <line
          x1={CHART.padL}
          x2={CHART.w - CHART.padR}
          y1={py(Math.max(min, 0))}
          y2={py(Math.max(min, 0))}
          stroke={AXE}
          strokeWidth={1}
        />

        {reference && (
          <>
            <line
              x1={CHART.padL}
              x2={CHART.w - CHART.padR}
              y1={py(reference.valeur)}
              y2={py(reference.valeur)}
              stroke={ENCRE_3}
              strokeWidth={1.5}
              strokeDasharray="5 4"
            />
            <text
              x={CHART.w - CHART.padR + 6}
              y={py(reference.valeur) + 3}
              textAnchor="start"
              className="cht-ref"
            >
              {reference.libelle}
            </text>
          </>
        )}

        {/* Cône d'incertitude — dessiné AVANT les séries pour rester en fond :
            c'est une enveloppe, elle ne doit jamais couvrir un tracé. Le cône
            part du dernier point mesuré (largeur nulle) et s'ouvre avec
            l'horizon. */}
        {projection?.bas && projection.haut && (() => {
          const ancre = series[0]?.points ?? [];
          const dernierMesure = [...ancre].reverse().find((p) => p.y !== null);
          if (!dernierMesure || dernierMesure.y === null) return null;
          const x0 = px(nMes - 1);
          const y0 = py(dernierMesure.y);
          const haut = projection.haut.map((v, i) => `L ${px(nMes + i)} ${py(v)}`).join(" ");
          const bas = projection.bas
            .map((v, i) => ({ v, i }))
            .reverse()
            .map(({ v, i }) => `L ${px(nMes + i)} ${py(v)}`)
            .join(" ");
          return <path className="cht-cone" d={`M ${x0} ${y0} ${haut} ${bas} Z`} />;
        })()}

        {/* Tracé projeté : cyan, pointillé, raccordé au dernier point mesuré. */}
        {projection && (() => {
          const ancre = series[0]?.points ?? [];
          const dernierMesure = [...ancre].reverse().find((p) => p.y !== null);
          if (!dernierMesure || dernierMesure.y === null) return null;
          const d = [
            `M ${px(nMes - 1)} ${py(dernierMesure.y)}`,
            ...projection.points.map((v, i) => `L ${px(nMes + i)} ${py(v)}`),
          ].join(" ");
          return (
            <g>
              <path className="cht-prj" d={d} />
              {projection.points.map((v, i) => (
                <circle key={i} className="cht-dot-p" cx={px(nMes + i)} cy={py(v)} r={3.5}>
                  <title>{`${projection.abscisses?.[i] ?? `+${i + 1}`} · ${formatY(v)} (projeté)`}</title>
                </circle>
              ))}
            </g>
          );
        })()}

        {series.map((s) => {
          const pts = s.points.map((p, i) => ({ ...p, cx: px(i), cy: p.y === null ? null : py(p.y) }));
          const segments: { d: string; fiable: boolean }[] = [];
          let courant: string[] = [];
          let fiableCourant = true;
          pts.forEach((p, i) => {
            if (p.cy === null) {
              if (courant.length > 1) segments.push({ d: courant.join(" "), fiable: fiableCourant });
              courant = [];
              return;
            }
            const fiable = p.fiable !== false;
            if (courant.length && fiable !== fiableCourant) {
              // Le segment suivant reprend au point de bascule : la ligne ne se
              // coupe pas, elle change de style.
              courant.push(`L ${p.cx} ${p.cy}`);
              segments.push({ d: courant.join(" "), fiable: fiableCourant });
              courant = [`M ${p.cx} ${p.cy}`];
              fiableCourant = fiable;
              return;
            }
            fiableCourant = fiable;
            courant.push(`${i === 0 || courant.length === 0 ? "M" : "L"} ${p.cx} ${p.cy}`);
          });
          if (courant.length > 1) segments.push({ d: courant.join(" "), fiable: fiableCourant });

          const visibles = pts.filter((p): p is typeof p & { cy: number } => p.cy !== null);
          const dernier = visibles[visibles.length - 1];

          return (
            <g key={s.cle}>
              {s.aire && visibles.length > 1 && (
                <path
                  d={`M ${visibles[0].cx} ${py(Math.max(min, 0))} ${visibles
                    .map((p) => `L ${p.cx} ${p.cy}`)
                    .join(" ")} L ${dernier.cx} ${py(Math.max(min, 0))} Z`}
                  fill={s.couleur}
                  opacity={0.1}
                />
              )}
              {segments.map((seg, i) => (
                <path
                  key={i}
                  d={seg.d}
                  fill="none"
                  stroke={s.couleur}
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeDasharray={s.repere ? "6 4" : seg.fiable ? undefined : "4 4"}
                  opacity={s.repere ? 0.65 : seg.fiable ? 1 : 0.55}
                />
              ))}
              {!s.repere &&
                visibles.map((p, i) => (
                  <circle
                    key={i}
                    cx={p.cx}
                    cy={p.cy}
                    r={p === dernier ? 4.5 : 3}
                    fill={s.couleur}
                    stroke={FOND}
                    strokeWidth={2}
                    opacity={p.fiable === false ? 0.5 : 1}
                  >
                    <title>{p.info ?? `${p.x} · ${formatY(p.y as number)}`}</title>
                  </circle>
                ))}
              {s.etiquetteFin && dernier && (
                <text x={dernier.cx - 8} y={dernier.cy - 12} textAnchor="end" className="cht-end">
                  {s.etiquetteFin}
                </text>
              )}
            </g>
          );
        })}

        {abscisses.map((p, i) =>
          i % pasX === 0 || (i === nMes - 1 && montreDernier) ? (
            <text key={p.x + i} x={px(i)} y={h - 10} textAnchor="middle" className="cht-tick">
              {p.x}
            </text>
          ) : null,
        )}
        {/* Abscisses projetées : le dernier libellé est toujours écrit — c'est
            l'horizon de la projection, l'information que le lecteur cherche. */}
        {projection?.abscisses?.map((x, i) =>
          (nMes + i) % pasX === 0 || i === nPrj - 1 ? (
            <text key={`p${x}${i}`} x={px(nMes + i)} y={h - 10} textAnchor="middle" className="cht-tick">
              {x}
            </text>
          ) : null,
        )}
      </svg>
      {(projection || (legende && series.length > 1)) && (
        <ChartLegend series={series} projection={projection} legende={legende} />
      )}
    </div>
  );
}

export interface SerieEmpilee {
  cle: string;
  libelle: string;
  couleur: string;
  /** Une valeur par abscisse, dans le même ordre que `abscisses`. */
  valeurs: number[];
}

/** Aires empilées — composition d'un total dans le temps.
 *
 * Les segments sont séparés par un filet de 2 px dans la couleur du fond : c'est
 * le vide qui sépare, pas un contour. La rampe de couleurs attendue est ORDINALE
 * (une seule teinte, du clair au foncé) quand les tranches sont ordonnées — une
 * ancienneté de créance se lit dans l'ordre, et la couleur doit le dire. */
export function StackedAreaChart({
  abscisses,
  series,
  formatY,
  hauteur,
  infos,
}: {
  abscisses: string[];
  series: SerieEmpilee[];
  formatY: (v: number) => string;
  hauteur?: number;
  /** Infobulle par abscisse (le total et sa composition). */
  infos?: string[];
}) {
  const h = hauteur ?? CHART.h;
  const totaux = abscisses.map((_, i) => series.reduce((s, serie) => s + (serie.valeurs[i] ?? 0), 0));
  const max = Math.max(...totaux, 1) * 1.08;
  const n = abscisses.length;
  const plotW = CHART.w - CHART.padL - CHART.padR;
  const plotH = h - CHART.padT - CHART.padB;
  const px = (i: number) => CHART.padL + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const py = (v: number) => CHART.padT + plotH - (v / max) * plotH;
  const ticks = graduations(0, max);
  const pasX = Math.max(1, Math.ceil(n / 8));
  const montreDernier = (n - 1) % pasX >= Math.ceil(pasX / 2);

  // Empilement du bas vers le haut : la première série de la liste est au sol.
  const bas: number[][] = [];
  const haut: number[][] = [];
  series.forEach((s, k) => {
    const precedent = k === 0 ? abscisses.map(() => 0) : haut[k - 1];
    bas.push(precedent);
    haut.push(precedent.map((v, i) => v + (s.valeurs[i] ?? 0)));
  });

  return (
    <div className="cht">
      <svg viewBox={`0 0 ${CHART.w} ${h}`} className="cht-svg" role="img" preserveAspectRatio="none">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={CHART.padL} x2={CHART.w - CHART.padR} y1={py(t)} y2={py(t)} stroke={GRILLE} strokeWidth={1} />
            <text x={CHART.padL - 8} y={py(t) + 3.5} textAnchor="end" className="cht-tick">
              {formatY(t)}
            </text>
          </g>
        ))}

        {series.map((s, k) => (
          <path
            key={s.cle}
            d={
              `M ${px(0)} ${py(bas[k][0])} ` +
              haut[k].map((v, i) => `L ${px(i)} ${py(v)}`).join(" ") +
              " " +
              bas[k]
                .map((v, i) => `L ${px(n - 1 - i)} ${py(bas[k][n - 1 - i])}`)
                .join(" ") +
              " Z"
            }
            fill={s.couleur}
            stroke={FOND}
            strokeWidth={2}
            strokeLinejoin="round"
          />
        ))}

        <line
          x1={CHART.padL}
          x2={CHART.w - CHART.padR}
          y1={py(0)}
          y2={py(0)}
          stroke={AXE}
          strokeWidth={1}
        />

        {/* Cibles de survol : une bande invisible par abscisse, bien plus large
            que le trait, pour que l'infobulle native soit atteignable. */}
        {abscisses.map((x, i) => (
          <rect
            key={x + i}
            x={px(i) - plotW / n / 2}
            y={CHART.padT}
            width={plotW / n}
            height={plotH}
            fill="transparent"
          >
            <title>{infos?.[i] ?? `${x} · ${formatY(totaux[i])}`}</title>
          </rect>
        ))}

        {abscisses.map((x, i) =>
          i % pasX === 0 || (i === n - 1 && montreDernier) ? (
            <text key={x + i} x={px(i)} y={h - 10} textAnchor="middle" className="cht-tick">
              {x}
            </text>
          ) : null,
        )}
      </svg>
      <ChartLegend
        series={series.map((s) => ({ cle: s.cle, libelle: s.libelle, couleur: s.couleur }))}
        inverse
      />
    </div>
  );
}

export interface Colonne {
  x: string;
  y: number;
  /** Colonne atténuée : donnée présente mais non comparable aux autres. */
  attenue?: boolean;
  etiquette?: string;
  info?: string;
}

/** Colonnes — magnitude sur peu de catégories, plus une ligne facultative.
 *
 * `cumul` trace une seconde série en ligne, obligatoirement dans la MÊME unité que
 * les colonnes. C'est ce qui permet de la tracer sans second axe : deux échelles
 * superposées sur un même graphe inventent une corrélation qui n'est pas dans les
 * données. Deux usages en place — la part cumulée d'un Pareto (top des charges,
 * budget DAF) et l'objectif posé face au réalisé (écart vendu/objectif, DC).
 * `libelleCumul` nomme la série dans la légende ET dans l'infobulle des points :
 * une ligne d'objectif étiquetée « cumul » se lirait comme un total. */
export function ColumnChart({
  colonnes,
  formatY,
  couleur,
  cumul,
  couleurCumul,
  reference,
  hauteur,
  libelleCumul,
  libelleColonnes,
}: {
  colonnes: Colonne[];
  formatY: (v: number) => string;
  couleur: string;
  cumul?: number[];
  couleurCumul?: string;
  reference?: { valeur: number; libelle: string };
  hauteur?: number;
  libelleCumul?: string;
  libelleColonnes?: string;
}) {
  const h = hauteur ?? CHART.h;
  const valeurs = colonnes.map((c) => c.y).concat(cumul ?? []).concat(reference ? [reference.valeur] : []);
  const max = Math.max(...valeurs, 1) * 1.12;
  const min = Math.min(0, ...valeurs);
  const n = colonnes.length;
  const plotW = CHART.w - CHART.padL - CHART.padR;
  const plotH = h - CHART.padT - CHART.padB;
  const bande = plotW / n;
  const largeur = Math.min(24, bande * 0.55);
  const cx = (i: number) => CHART.padL + bande * i + bande / 2;
  const py = (v: number) => CHART.padT + plotH - ((v - min) / (max - min || 1)) * plotH;
  const ticks = graduations(min, max);
  const y0 = py(0);

  return (
    <div className="cht">
      <svg viewBox={`0 0 ${CHART.w} ${h}`} className="cht-svg" role="img" preserveAspectRatio="none">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={CHART.padL} x2={CHART.w - CHART.padR} y1={py(t)} y2={py(t)} stroke={GRILLE} strokeWidth={1} />
            <text x={CHART.padL - 8} y={py(t) + 3.5} textAnchor="end" className="cht-tick">
              {formatY(t)}
            </text>
          </g>
        ))}

        {reference && (
          <>
            <line
              x1={CHART.padL}
              x2={CHART.w - CHART.padR}
              y1={py(reference.valeur)}
              y2={py(reference.valeur)}
              stroke={ENCRE_3}
              strokeWidth={1.5}
              strokeDasharray="5 4"
            />
            <text
              x={CHART.w - CHART.padR + 6}
              y={py(reference.valeur) + 3}
              textAnchor="start"
              className="cht-ref"
            >
              {reference.libelle}
            </text>
          </>
        )}

        {colonnes.map((c, i) => {
          // Plancher de 2 px sur une valeur non nulle : à l'échelle du graphe, une
          // petite valeur (13 M face à 4 650 M) tombait sous le pixel et sa colonne
          // disparaissait — l'écran se lisait « aucune donnée » là où la donnée
          // existe. Une valeur RÉELLEMENT nulle garde une colonne nulle.
          const haut = c.y === 0 ? y0 : Math.min(py(c.y), y0 - 2);
          const hauteurBarre = y0 - haut;
          // Le rayon du sommet ne peut pas dépasser la demi-hauteur, sinon les deux
          // courbes de Bézier se croisent et le chemin se replie.
          const r = Math.min(4, hauteurBarre / 2, largeur / 2);
          return (
            <g key={c.x + i}>
              {/* Sommet arrondi, base carrée : le rayon n'est appliqué qu'en haut
                  via un chemin, un rect arrondi arrondirait aussi la base. */}
              <path
                d={`M ${cx(i) - largeur / 2} ${y0}
                    L ${cx(i) - largeur / 2} ${haut + r}
                    Q ${cx(i) - largeur / 2} ${haut} ${cx(i) - largeur / 2 + r} ${haut}
                    L ${cx(i) + largeur / 2 - r} ${haut}
                    Q ${cx(i) + largeur / 2} ${haut} ${cx(i) + largeur / 2} ${haut + r}
                    L ${cx(i) + largeur / 2} ${y0} Z`}
                fill={couleur}
                opacity={c.attenue ? 0.28 : 1}
              >
                <title>{c.info ?? `${c.x} · ${formatY(c.y)}`}</title>
              </path>
              {c.etiquette && hauteurBarre > 14 && (
                <text x={cx(i)} y={haut - 7} textAnchor="middle" className="cht-val">
                  {c.etiquette}
                </text>
              )}
            </g>
          );
        })}

        {cumul && cumul.length > 0 && (
          <>
            <path
              d={cumul.map((v, i) => `${i === 0 ? "M" : "L"} ${cx(i)} ${py(v)}`).join(" ")}
              fill="none"
              stroke={couleurCumul ?? ENCRE_2}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            {cumul.map((v, i) => (
              <circle key={i} cx={cx(i)} cy={py(v)} r={3} fill={couleurCumul ?? ENCRE_2} stroke={FOND} strokeWidth={2}>
                {/* Le libellé suit celui de la légende : la ligne ne porte pas
                    toujours un cumul de Pareto (elle sert aussi d'objectif posé,
                    dans la même unité), et « cumul » serait alors faux. */}
                <title>{`${colonnes[i]?.x} · ${libelleCumul ?? "cumul"} ${formatY(v)}`}</title>
              </circle>
            ))}
          </>
        )}

        <line x1={CHART.padL} x2={CHART.w - CHART.padR} y1={y0} y2={y0} stroke={AXE} strokeWidth={1} />

        {colonnes.map((c, i) => (
          <text key={c.x + i} x={cx(i)} y={h - 10} textAnchor="middle" className="cht-tick">
            {c.x}
          </text>
        ))}
      </svg>
      {cumul && libelleCumul && libelleColonnes && (
        <ChartLegend
          series={[
            { cle: "col", libelle: libelleColonnes, couleur },
            { cle: "cum", libelle: libelleCumul, couleur: couleurCumul ?? ENCRE_2 },
          ]}
        />
      )}
    </div>
  );
}

/** Légende — présente dès deux séries, jamais pour une seule (le titre de la
 * tuile nomme déjà ce qui est tracé). `inverse` remet l'ordre visuel de haut en
 * bas pour une pile, où la dernière série dessinée est celle du haut. */
export function ChartLegend({
  series,
  inverse,
  projection,
  legende = true,
}: {
  series: { cle: string; libelle: string; couleur: string }[];
  inverse?: boolean;
  /** Ajoute les entrées « projeté » et « marge d'incertitude ». La pastille y
   *  reprend la MARQUE du tracé (tiret pointillé, aplat translucide) et non un
   *  carré plein : une légende doit porter le même signe que ce qu'elle nomme. */
  projection?: Projection;
  /** Passé à `false`, masque les séries mesurées et ne garde que la projection —
   *  cas d'une série unique, où nommer « la » courbe n'apprend rien. */
  legende?: boolean;
}) {
  const base = inverse ? [...series].reverse() : series;
  const items = legende && series.length > 1 ? base : [];
  return (
    <ul className="cht-lg">
      {items.map((s) => (
        <li key={s.cle}>
          <i style={{ background: s.couleur }} aria-hidden="true" />
          {s.libelle}
        </li>
      ))}
      {projection && (
        <li>
          <i className="prj" aria-hidden="true" />
          {projection.libelle ?? "Projeté"}
        </li>
      )}
      {projection?.bas && projection.haut && (
        <li>
          <i className="cone" aria-hidden="true" />
          Marge d&apos;incertitude
        </li>
      )}
    </ul>
  );
}

/** Note posée sous un graphe — limite de lecture, provenance, méthode. */
export function ChartNote({ children }: { children: ReactNode }) {
  return <p className="cht-nt">{children}</p>;
}
