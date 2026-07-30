/**
 * Lecture des blocs ```chart émis par le Copilote.
 *
 * Le system prompt (backend/modules/uc02_capital_knowledge/router.py, section
 * VISUALISATION) demande au modèle d'ajouter un bloc de code ```chart contenant
 * du JSON quand la réponse porte une série de valeurs comparables. Ce module
 * découpe le message en segments (texte / graphique) et valide la spec ; le
 * rendu vit dans ChartBlock.tsx.
 *
 * Tout est pur et sans React : le découpage et le choix de forme sont la partie
 * qu'on peut vérifier sans navigateur.
 */

export type ChartType = "bar" | "line" | "pie" | "donut";

export interface ChartPoint {
  label: string;
  value: number;
}

export interface ChartSpec {
  type: ChartType;
  title: string;
  unit: string;
  data: ChartPoint[];
}

export type MessageSegment =
  | { kind: "text"; text: string }
  | { kind: "chart"; source: string; complete: boolean };

const OPEN = "```chart";

function pushText(out: MessageSegment[], text: string) {
  if (text.trim()) out.push({ kind: "text", text });
}

/**
 * Découpe le contenu d'un message en segments texte / graphique.
 *
 * `complete: false` signale un bloc dont la clôture n'est pas encore arrivée :
 * pendant le streaming SSE, le message grandit token par token et la spec est
 * tronquée pendant une ou deux secondes. Sans ce drapeau, on afficherait le
 * JSON brut en train de s'écrire — exactement ce qu'on cherche à supprimer.
 */
export function splitMessage(content: string): MessageSegment[] {
  const out: MessageSegment[] = [];
  let cursor = 0;

  for (;;) {
    const start = content.indexOf(OPEN, cursor);
    if (start === -1) break;

    // Une clôture de bloc n'ouvre un graphique qu'en début de ligne : `\`\`\`chart`
    // cité au fil d'une phrase reste du texte.
    if (start > 0 && content[start - 1] !== "\n") {
      cursor = start + OPEN.length;
      continue;
    }

    const bodyStart = content.indexOf("\n", start);
    if (bodyStart === -1) {
      // Le modèle vient d'ouvrir le bloc, le JSON n'a pas commencé.
      pushText(out, content.slice(cursor, start));
      out.push({ kind: "chart", source: "", complete: false });
      return out;
    }

    pushText(out, content.slice(cursor, start));

    const end = content.indexOf("\n```", bodyStart);
    if (end === -1) {
      out.push({ kind: "chart", source: content.slice(bodyStart + 1), complete: false });
      return out;
    }

    out.push({ kind: "chart", source: content.slice(bodyStart + 1, end), complete: true });

    // Reprendre après la ligne de clôture.
    const afterFence = end + 4;
    const nextLine = content.indexOf("\n", afterFence);
    cursor = nextLine === -1 ? content.length : nextLine + 1;
  }

  pushText(out, content.slice(cursor));
  return out;
}

const TYPES: ChartType[] = ["bar", "line", "pie", "donut"];

/** Convertit une valeur en nombre fini, ou null. Le prompt demande des nombres
 * bruts, mais un modèle glisse parfois "1 850" ou "1,850" : on récupère ces cas
 * plutôt que de perdre le graphique entier. */
function toNumber(raw: unknown): number | null {
  if (typeof raw === "number") return Number.isFinite(raw) ? raw : null;
  if (typeof raw !== "string") return null;
  const cleaned = raw.replace(/[\s  ]/g, "").replace(/,(?=\d{3}\b)/g, "");
  const n = Number(cleaned.replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

/** Spec validée, ou null si le JSON est illisible ou vide de points exploitables. */
export function parseChartSpec(source: string): ChartSpec | null {
  let raw: unknown;
  try {
    raw = JSON.parse(source);
  } catch {
    return null;
  }
  if (!raw || typeof raw !== "object") return null;

  const obj = raw as Record<string, unknown>;
  const rawType = typeof obj.type === "string" ? obj.type.toLowerCase() : "";
  const type = (TYPES as string[]).includes(rawType) ? (rawType as ChartType) : "bar";

  if (!Array.isArray(obj.data)) return null;
  const data: ChartPoint[] = [];
  for (const item of obj.data) {
    if (!item || typeof item !== "object") continue;
    const point = item as Record<string, unknown>;
    const value = toNumber(point.value);
    if (value === null) continue;
    const label = typeof point.label === "string" ? point.label.trim() : String(point.label ?? "");
    data.push({ label: label || "—", value });
  }
  if (!data.length) return null;

  return {
    type,
    title: typeof obj.title === "string" ? obj.title.trim() : "",
    unit: typeof obj.unit === "string" ? obj.unit.trim() : "",
    data,
  };
}

/**
 * Forme de rendu retenue — décidée AVANT la couleur, sur le travail que le
 * lecteur doit faire (cf. méthode dataviz, « choosing a form ») :
 *
 * - `stat`  : un seul point. Un graphique à une barre n'apporte rien, le nombre
 *             EST le graphique.
 * - `share` : deux parts d'un tout → une jauge, pas un camembert à 2 quartiers.
 * - `donut` : part-à-tout de 3 à 6 parts.
 * - `line`  : évolution dans le temps.
 * - `bars`  : comparaison de magnitudes — aussi le repli d'un camembert dont une
 *             valeur est négative ou nulle (une part de tout n'a alors aucun sens).
 */
export type ChartForm = "stat" | "bars" | "line" | "donut" | "share";

export function chooseForm(spec: ChartSpec): ChartForm {
  if (spec.data.length === 1) return "stat";
  if (spec.type === "line") return "line";
  if (spec.type === "pie" || spec.type === "donut") {
    if (spec.data.some((d) => d.value <= 0)) return "bars";
    return spec.data.length === 2 ? "share" : "donut";
  }
  return "bars";
}

/** Nombre de marques affichées : au-delà, les libellés se chevauchent et la
 * lecture se dégrade. Le tableau de données, lui, n'est jamais tronqué. */
export const MAX_MARKS: Record<ChartForm, number> = {
  stat: 1,
  bars: 12,
  line: 24,
  donut: 4, // 4 teintes validées + un agrégat « Autres » (cf. PALETTE)
  share: 2,
};

const NF = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 });
// `style: "percent"` pour l'espace insécable avant le %, que la typographie
// française impose et qu'un simple " %" laisserait passer à la ligne seul.
// Une décimale toujours affichée : dans une colonne de parts, « 10 % » à côté de
// « 42,7 % » casse l'alignement des chiffres.
const NF_PCT = new Intl.NumberFormat("fr-FR", {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

/**
 * Nombre de décimales commun à toute la série (2 au plus).
 *
 * Une colonne de nombres alignés se lit mal en décimales mélangées — « 12,4 »
 * au-dessus de « 8,13 » donne deux échelles apparentes. On aligne donc sur la
 * valeur la plus précise de la série.
 */
export function seriesDecimals(values: number[]): number {
  let decimals = 0;
  for (const value of values) {
    const text = String(value);
    const dot = text.indexOf(".");
    if (dot >= 0) decimals = Math.max(decimals, Math.min(2, text.length - dot - 1));
    if (decimals === 2) break;
  }
  return decimals;
}

export function formatValue(value: number, decimals?: number): string {
  if (decimals === undefined) return NF.format(value);
  return value.toLocaleString("fr-FR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatPercent(part: number, total: number): string {
  if (!total) return "—";
  return NF_PCT.format(part / total);
}

/** L'unité ne s'affiche en légende que si le titre ne la porte pas déjà — le
 * modèle écrit très souvent « CA par année (M XOF) » ET `unit: "M XOF"`. */
export function unitCaption(spec: ChartSpec): string {
  if (!spec.unit) return "";
  if (spec.title.toLowerCase().includes(spec.unit.toLowerCase())) return "";
  return `en ${spec.unit}`;
}
