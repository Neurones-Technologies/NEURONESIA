import { View } from "@/components/shell/AppShell";
import { Skel } from "@/components/ui/skeleton";
import { DossierPending } from "@/components/views/arbitrage/DossierPending";

/** Squelette propre à l'écran d'arbitrage.
 *
 * Le repli générique (`PageSkeleton`, bandeau sombre + grille bento) ne
 * ressemblait à aucun moment à cette page : au chargement, on voyait apparaître
 * une mise en page qui n'était pas celle qui allait s'afficher. Celui-ci reprend
 * la vraie anatomie — bandeau d'indicateurs, file à gauche, dossier à droite —
 * pour que le contenu prenne la place déjà dessinée, sans saut. */
export default function Loading() {
  return (
    <View>
      <p className="eyebrow">
        <Skel width={170} height={9} />
      </p>
      <h1 className="vt">
        <Skel width={230} height={34} />
      </h1>
      <p className="vsub" style={{ display: "grid", gap: 8 }}>
        <Skel width="72%" height={13} />
        <Skel width="54%" height={13} />
      </p>

      <div className="kpi-row">
        {[0, 1, 2, 3, 4].map((i) => (
          <div className="tile" key={i}>
            <div className="tile-h">
              <Skel width={120} height={11} />
            </div>
            <Skel width={90} height={38} style={{ marginBottom: 12 }} />
            <Skel width={140} height={11} />
          </div>
        ))}
      </div>

      <section className="sec">
        <div className="sec-h">
          <b>
            <Skel width={160} height={18} />
          </b>
        </div>
        <div className="arb-work">
          <div className="arb-queue">
            <div className="arb-queue-h">
              <Skel width={130} height={14} />
            </div>
            <Skel width="100%" height={34} radius={999} style={{ marginBottom: 12 }} />
            <div style={{ display: "grid", gap: 10 }}>
              {[0, 1, 2, 3, 4].map((i) => (
                <Skel key={i} width="100%" height={74} radius={12} />
              ))}
            </div>
          </div>
          <div className="arb-stage">
            <DossierPending />
          </div>
        </div>
      </section>
    </View>
  );
}
