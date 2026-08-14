import { Suspense } from "react";
import { AnalysisNarr, Narr, Note } from "@/components/ui/primitives";
import { Skel } from "@/components/ui/skeleton";

/** Forme commune des endpoints `.../analysis` du backend. */
interface AnalysisLike {
  analysis: string;
}

/** Squelette de narration — reprend la boîte `.narr` pour que l'arrivée du
 * texte ne décale pas la mise en page. */
function AnalysisPending({ lines = 3 }: { lines?: number }) {
  return (
    <Narr>
      <div style={{ display: "grid", gap: 10 }} aria-busy="true" aria-label="Analyse en cours de rédaction">
        {Array.from({ length: lines }).map((_, i) => (
          <Skel key={i} width={`${96 - i * 11}%`} height={13} />
        ))}
      </div>
    </Narr>
  );
}

async function AnalysisBody({
  load,
  empty,
  pliable,
  titrePli,
}: {
  load: () => Promise<AnalysisLike | null>;
  empty: string;
  pliable?: boolean;
  titrePli?: string;
}) {
  const result = await load();
  if (!result?.analysis) return <Note style={{ marginTop: 0 }}>{empty}</Note>;
  const narration = <AnalysisNarr text={result.analysis} />;
  if (!pliable) return narration;
  // `<details>` natif, comme `ScreenNotes` : le repli tient sans JavaScript, donc
  // l'écran reste un Server Component et le panneau fonctionne avant hydratation.
  // Replié par défaut — la narration fait ici trois longs paragraphes, qui
  // repoussaient les blocs chiffrés sous la ligne de flottaison.
  return (
    <details className="scr-n scr-n--narr">
      <summary>
        <span className="scr-n-t">{titrePli ?? "Lire l'analyse"}</span>
      </summary>
      <div className="scr-n-b">{narration}</div>
    </details>
  );
}

/**
 * Narration LLM rendue HORS du chemin critique de la page.
 *
 * En régime normal, ces endpoints ne coûtent plus qu'une lecture SQLite : la
 * narration est écrite une fois par jour à 6h00 par
 * `jobs/scheduler.py::_daily_analyses_job` et figée en base (table
 * `daily_analyses`, cf. modules/uc_daily_analysis) — le squelette ci-dessous
 * n'apparaît donc plus à l'usage.
 *
 * La frontière Suspense reste néanmoins nécessaire, pour le seul cas où la
 * narration du jour manque (tout premier démarrage, job du matin en échec,
 * variante de période inédite) : le backend la calcule alors en secours, ce qui
 * reprend 10 à 20 s de Claude Sonnet. Sans cette frontière, ces secondes
 * bloqueraient TOUT le HTML de la page comme avant : le cockpit mettait 12 à
 * 18 s à s'afficher alors que ses données chiffrées sont prêtes en 0,3 s
 * (mesuré sur /dg /dc /df /do /am). Ne PAS remettre ces appels dans le
 * `Promise.all` des vues sous prétexte qu'ils sont devenus rapides.
 *
 * `load` est une closure exécutée côté serveur uniquement (deux Server
 * Components de part et d'autre : aucune sérialisation en jeu).
 *
 * ATTENTION : le streaming n'atteint le navigateur que si le proxy ne
 * tamponne pas la réponse — `proxy_buffering off` sur `location /`
 * (nginx.neurones-ia.conf), sinon nginx réassemble le HTML et on retombe sur
 * le comportement bloquant.
 */
export function AnalysisSlot({
  load,
  empty = "Analyse non disponible pour ce profil.",
  lines,
  pliable,
  titrePli,
}: {
  load: () => Promise<AnalysisLike | null>;
  empty?: string;
  lines?: number;
  /** Replie la narration derrière un titre cliquable. Option et non défaut : les
   *  sept autres appels affichent la leur en clair, et la replier d'office
   *  cacherait une analyse que l'écran présente comme son contenu principal. */
  pliable?: boolean;
  /** Libellé du titre replié. */
  titrePli?: string;
}) {
  return (
    <Suspense fallback={<AnalysisPending lines={lines} />}>
      <AnalysisBody load={load} empty={empty} pliable={pliable} titrePli={titrePli} />
    </Suspense>
  );
}
