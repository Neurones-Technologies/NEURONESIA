import { ENGINES, ENGINES_CLOSING_NOTE } from "@/lib/data/engines";
import { MiniLabel, ModuleCard, Mods, Note, ViewHeader } from "@/components/ui/primitives";

export function EnginesView() {
  return (
    <>
      <ViewHeader
        eyebrow="Référentiel · architecture fonctionnelle"
        title="Cinq moteurs, vingt-neuf vues"
        subtitle="Les vingt-neuf fonctionnalités ne sont pas vingt-neuf développements. Elles reposent sur cinq détecteurs, une couche de narration et un registre de décisions : construire les moteurs une fois, décliner les vues ensuite."
      />

      <Mods>
        {ENGINES.map((e) => (
          <ModuleCard key={e.code} n={e.code} title={e.title} desc={e.desc} engine={e.tag} llm={e.isLlm}>
            <MiniLabel>Alimente</MiniLabel>
            <div className="rows">
              <div className="row">
                <div>
                  <div className="row-n">{e.feeds}</div>
                </div>
              </div>
            </div>
            <Note>{e.note}</Note>
          </ModuleCard>
        ))}
      </Mods>

      <Note accent style={{ marginTop: 24 }}>
        {ENGINES_CLOSING_NOTE}
      </Note>
    </>
  );
}
