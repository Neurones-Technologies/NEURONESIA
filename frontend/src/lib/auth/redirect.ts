/** Cible de repli quand `next` est absent ou refusé. */
export function defaultTarget(profile: string): string {
  return `/${profile}/vision`;
}

/**
 * Valide la cible de redirection post-login lue dans `?next=`.
 *
 * Le paramètre vient de l'URL, donc de l'utilisateur : sans filtrage il permet
 * une redirection ouverte (`?next=https://evil.tld` renverrait la victime hors
 * du domaine après une connexion légitime). On n'accepte donc qu'un chemin
 * interne, et on rejette tout ce qui pourrait être relu comme une autorité :
 *   - `//evil.tld` et `/\evil.tld` — chemins protocol-relative,
 *   - `https://…`, `javascript:…` — toute URL absolue ou pseudo-schéma,
 *   - `/login` — sinon la connexion reboucle sur elle-même.
 *
 * Retourne la cible sûre, ou `null` si `next` est inutilisable (l'appelant
 * retombe alors sur `defaultTarget`).
 */
export function safeNextPath(next: string | null): string | null {
  if (!next) return null;

  // Un `next` encodé une fois de trop (`%2Fevil`) ou malformé ne doit pas jeter.
  let path: string;
  try {
    path = decodeURIComponent(next);
  } catch {
    return null;
  }

  if (!path.startsWith("/")) return null;
  if (path.startsWith("//") || path.startsWith("/\\")) return null;

  // `/login` (avec ou sans query) renverrait l'utilisateur sur le formulaire.
  if (path === "/login" || path.startsWith("/login/") || path.startsWith("/login?")) {
    return null;
  }

  return path;
}
