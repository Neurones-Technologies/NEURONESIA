import { Note } from "./primitives";

/** Hypothèses et limites d'un écran, repliées en tête plutôt qu'empilées en pied.
 *
 * Ces textes sont la meilleure protection du cockpit contre une mauvaise lecture
 * (« un cumul négatif ne signifie pas un découvert », « la marge affichée est une
 * marge d'affaires, pas une marge comptable »). Mesuré au navigateur, ils étaient
 * jusqu'ici publiés dans une tuile terminale : sur la trésorerie, à 2 465 px de
 * défilement, l'avertissement arrivait après la décision qu'il devait éviter.
 *
 * Trois choix, dans cet ordre d'importance :
 *
 * - `<details>` natif : aucun JS, donc l'écran reste un Server Component et le
 *   panneau fonctionne avant hydratation. `Ctrl+F` du navigateur ouvre la section
 *   fermée dans les moteurs récents, la note n'est donc pas perdue pour la
 *   recherche en page.
 * - replié par défaut : la note ne prend que sa ligne de titre, ce qui la met en
 *   tête sans repousser le contenu de l'écran. Le compteur sert d'appel — il
 *   annonce qu'il y a quelque chose à lire, sans le déplier de force.
 * - `ouvert` pour les écrans où une mauvaise lecture coûte de l'argent.
 *
 * Le texte n'est ni réécrit ni tronqué : il vient du module de calcul, seul à
 * savoir ce qu'il n'a pas pu mesurer (cf. la règle posée dans `dc/source.tsx`).
 * Les notes attachées à UN bloc précis restent auprès de leur bloc — seules les
 * hypothèses d'écran remontent ici. */
export function ScreenNotes({
  notes,
  titre = "Ce que cet écran mesure et ce qu'il suppose",
  ouvert,
}: {
  /** Hypothèses, dans l'ordre de lecture. Les valeurs vides sont écartées : les
   *  champs de note du backend sont optionnels selon la source de la donnée. */
  notes: (string | null | undefined)[];
  titre?: string;
  ouvert?: boolean;
}) {
  // Dédoublonnage : plusieurs blocs du backend partagent la même phrase
  // d'hypothèse (sur la trésorerie, `vigilance.methode` et l'une des
  // `atterrissage.hypotheses` sont le même texte). Rassemblées ici, elles
  // s'affichaient deux fois de suite — une répétition qui se lit comme un défaut
  // et fait douter du reste du panneau.
  const vues = new Set<string>();
  const retenues = notes.filter((n): n is string => {
    if (typeof n !== "string") return false;
    const t = n.trim();
    if (t.length === 0 || vues.has(t)) return false;
    vues.add(t);
    return true;
  });
  if (retenues.length === 0) return null;
  return (
    <details className="scr-n" open={ouvert}>
      <summary>
        <span className="scr-n-t">{titre}</span>
        <span className="scr-n-c">{retenues.length}</span>
      </summary>
      <div className="scr-n-b">
        {retenues.map((n, i) => (
          <Note key={i}>{n}</Note>
        ))}
      </div>
    </details>
  );
}
