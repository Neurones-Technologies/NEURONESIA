import { Skel } from "@/components/ui/skeleton";

/** Panneau de dossier en cours d'instruction.
 *
 * Reprend la forme exacte de `.dec` — en-tête, bandeau de faits, options — pour
 * que l'arrivée du contenu ne décale pas la page déjà peinte. Vit dans son
 * propre fichier parce qu'il sert à deux endroits qui ne doivent rien partager
 * d'autre : la frontière Suspense de la vue, et `loading.tsx` (qui n'a aucune
 * raison de tirer avec lui le module de dossier et ses appels réseau). */
export function DossierPending() {
  return (
    <div className="dec" aria-busy="true" aria-label="Dossier en cours d'instruction">
      <div className="dec-h">
        <h3>
          <Skel width={280} height={19} />
        </h3>
        <div className="arb-facts">
          {[0, 1, 2, 3].map((i) => (
            <div className="arb-fact" key={i}>
              <Skel width={90} height={9} />
              <Skel width={70} height={20} style={{ margin: "8px 0 6px" }} />
              <Skel width="80%" height={10} />
            </div>
          ))}
        </div>
        <p style={{ display: "grid", gap: 9, marginTop: 12 }}>
          {[94, 76].map((w, i) => (
            <Skel key={i} width={`${w}%`} height={12} />
          ))}
        </p>
      </div>
      <div className="dec-b">
        <div style={{ display: "grid", gap: 12, marginBottom: 20 }}>
          <Skel width="100%" height={78} radius={12} />
          <Skel width="100%" height={56} radius={10} />
          <Skel width="100%" height={56} radius={10} />
        </div>
        <div className="opts">
          {[0, 1, 2].map((i) => (
            <Skel key={i} width="100%" height={168} radius={12} />
          ))}
        </div>
      </div>
    </div>
  );
}
