import Link from "next/link";

/** Panneau modal de l'écran Comptes.
 *
 * Rendu CÔTÉ SERVEUR d'après l'URL (`?compte=<id>`, `?nouveau=1`) : ouvrir un
 * panneau est une navigation, pas un `fetch`. Trois conséquences voulues — le
 * lien se partage, le retour arrière referme, et rien n'est chargé deux fois.
 *
 * La fermeture est un lien, à deux endroits : la croix et le fond. Aucun état
 * client, donc aucune animation d'entrée — c'est le prix payé pour que le
 * panneau existe dans le HTML rendu.
 *
 * Reste hors de portée sans JavaScript : le piège de focus et la touche Échap.
 * `aria-modal` l'annonce pourtant aux lecteurs d'écran ; c'est assumé, la
 * fermeture restant atteignable au clavier par le lien de la croix, premier
 * élément focusable du panneau.
 */
export function Modale({
  eyebrow,
  titre,
  fermer,
  large,
  children,
}: {
  eyebrow: string;
  titre: string;
  /** URL de retour à la liste, filtres conservés. */
  fermer: string;
  large?: boolean;
  children: React.ReactNode;
}) {
  return (
    <>
      <Link className="ovl on" href={fermer} aria-label="Fermer" />
      <div className="mdl-w">
        <section
          className={`mdl${large ? " mdl--l" : ""}`}
          role="dialog"
          aria-modal="true"
          aria-label={titre}
        >
          <div className="mdl-h">
            <div>
              <p className="mdl-k">{eyebrow}</p>
              <h3>{titre}</h3>
            </div>
            <Link className="drw-x" href={fermer} aria-label="Fermer">
              &times;
            </Link>
          </div>
          <div className="mdl-b">{children}</div>
        </section>
      </div>
    </>
  );
}
