/** Phrase d'accroche d'un écran — ce qu'il faut retenir, avant les chiffres.
 *
 * Le panneau `Brief` (bandeau sombre en tête de cockpit) porte le briefing du jour
 * généré par le LLM. Il est servi par `getBriefing()`, qui produit UN briefing par
 * RÔLE et non par écran : le poser sur les cinq onglets DAF afficherait cinq fois
 * le même texte. Ce composant répond au même besoin — savoir en une phrase ce que
 * dit l'écran — mais se compose des données déjà chargées, sans appel de plus et
 * sans LLM.
 *
 * Volontairement plus discret que `Brief` : c'est une accroche de lecture, pas un
 * briefing. Un écran ne doit pas avoir deux panneaux d'ouverture concurrents, donc
 * `df/encours`, qui porte le vrai `Brief`, n'en reçoit pas.
 *
 * `signaux` accepte deux à quatre constats courts. Le premier `alerte` est mis en
 * évidence — au-delà, tout serait mis en évidence et donc rien ne le serait. */
export function ScreenLede({
  texte,
  signaux,
}: {
  /** Une phrase. Ce que l'écran dit, pas ce qu'il contient. */
  texte: string;
  signaux?: { label: string; alerte?: boolean }[];
}) {
  return (
    <div className="lede">
      <p className="lede-t">{texte}</p>
      {signaux && signaux.length > 0 && (
        <div className="lede-s">
          {signaux.map((s, i) => (
            <span key={i} className={`lede-p${s.alerte ? " lede-p--a" : ""}`}>
              {s.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
