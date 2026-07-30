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
}: {
  load: () => Promise<AnalysisLike | null>;
  empty: string;
}) {
  const result = await load();
  if (!result?.analysis) return <Note style={{ marginTop: 0 }}>{empty}</Note>;
  return <AnalysisNarr text={result.analysis} />;
}

/**
 * Narration LLM rendue HORS du chemin critique de la page.
 *
 * Les endpoints `.../analysis` appellent Claude Sonnet : 10 à 20 s au premier
 * appel (le TTL de 15 min côté backend ne couvre que les suivants, cf.
 * core/services/ttl_cache.py). Attendre ce résultat dans le `Promise.all` de la
 * vue bloquait TOUT le HTML de la page : le cockpit mettait 12 à 18 s à
 * s'afficher alors que ses données chiffrées sont prêtes en 0,3 s. Mesuré sur
 * /dg /dc /df /do /am avant correction.
 *
 * Ici l'appel vit dans sa propre frontière Suspense : la page part
 * immédiatement avec les chiffres, chaque narration se pose dès qu'elle
 * arrive. `load` est une closure exécutée côté serveur uniquement (deux Server
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
}: {
  load: () => Promise<AnalysisLike | null>;
  empty?: string;
  lines?: number;
}) {
  return (
    <Suspense fallback={<AnalysisPending lines={lines} />}>
      <AnalysisBody load={load} empty={empty} />
    </Suspense>
  );
}
