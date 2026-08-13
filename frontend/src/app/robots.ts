import type { MetadataRoute } from "next";

/**
 * Cockpit interne, intégralement derrière authentification : aucune page n'a
 * vocation à être indexée, d'où un `Disallow: /` global (pas de `Sitemap:`,
 * qui n'aurait aucun sens ici).
 *
 * Sans ce fichier, `/robots.txt` n'existait pas ET le proxy le redirigeait vers
 * /login (cf. l'exclusion `robots.txt` du matcher dans src/proxy.ts) : les
 * crawlers recevaient un 200 + HTML de page de connexion en guise de robots.txt
 * — invalide (Lighthouse : « Unknown directive » sur `<!DOCTYPE html>`), et
 * surtout aucune consigne de non-indexation. Les deux morceaux vont ensemble :
 * ce fichier seul serait lui aussi redirigé.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      disallow: "/",
    },
  };
}
