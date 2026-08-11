import { Skel } from "@/components/ui/skeleton";

/** Panneau de dossier en cours d'instruction.
 *
 * Reprend la forme exacte de `.dec` — en-tête, bandeau de faits, options — pour
 * que l'arrivée du contenu ne décale pas la page déjà peinte.
 *
 * Sert la frontière Suspense de `ArbitrageView`, qui est `key={selectedRef}` :
 * elle se redéclenche donc à chaque changement de dossier dans la file, et pas
 * seulement à l'ouverture de l'écran. C'est ce qui la distingue des `loading.tsx`
 * de route, retirés depuis (cf. app/loading.tsx) : sans elle, un clic dans la
 * file figerait la page entière au lieu du seul panneau de droite. */
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
