import { COVERAGE_ROWS } from "@/lib/data/coverage";
import { Kpi, KpiStrip, Legend, ModuleCard, Note, Tag, ViewHeader } from "@/components/ui/primitives";

export function CoverageView() {
  return (
    <>
      <ViewHeader
        eyebrow="Référentiel · contrôle de couverture"
        title="Couverture 29 / 29"
        subtitle="Les vingt-neuf fonctionnalités validées, rattachées à leur profil, à leur moteur de détection et aux objets Odoo mobilisés. Un module non couvert apparaîtrait en rouge dans cette table."
      />

      <KpiStrip>
        <Kpi label="Fonctionnalités" value="29 / 29" valueVariant="s" detail={<span className="up">couverture complète</span>} />
        <Kpi label="Profils" value="5 / 5" detail="5 modules + 4 transverses" />
        <Kpi label="Moteurs" value="5" detail="+ narration + registre" />
        <Kpi label="Objets Odoo" value="6" detail="périmètre initial confirmé" />
        <Kpi label="Hors périmètre" value="1" detail={<span className="wa">tendances techno marché</span>} />
      </KpiStrip>

      <ModuleCard
        n="—"
        title="Table de couverture"
        desc="Les modules 01 à 25 sont rattachés à un profil. Les modules 26 à 29 sont transverses : ils portent la décision, non le constat."
        engine="contrôle"
      >
        <div style={{ overflowX: "auto" }}>
          <table className="tb">
            <thead>
              <tr>
                <th>N°</th>
                <th>Profil</th>
                <th>Fonctionnalité</th>
                <th>Moteur</th>
                <th>Objets Odoo</th>
                <th>État</th>
              </tr>
            </thead>
            <tbody>
              {COVERAGE_ROWS.map((r) => (
                <tr key={r.n}>
                  <td className="mono">{r.n}</td>
                  <td>{r.profil}</td>
                  <td>{r.feature}</td>
                  <td className="mono">{r.engine}</td>
                  <td className="mono">{r.objects}</td>
                  <td>
                    <Tag variant={r.variant}>{r.status}</Tag>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Legend
          items={[
            { swatch: { background: "var(--signal-soft)", border: "1px solid #C3D6CE" }, label: "couvert par le périmètre Odoo confirmé" },
            { swatch: { background: "var(--watch-soft)", border: "1px solid #E6D3A8" }, label: "proxy assumé, faute de feuilles de temps" },
          ]}
        />
        <Note>
          Trois modules sur vingt-neuf reposent sur un proxy et non sur une mesure directe. Ils sont signalés comme
          tels dans l&apos;interface, sur chaque écran concerné, plutôt que présentés comme une mesure de charge
          réelle. Ouvrir les feuilles de temps et la comptabilité analytique les transformerait en mesures exactes et
          ajouterait la marge par affaire.
        </Note>
      </ModuleCard>
    </>
  );
}
