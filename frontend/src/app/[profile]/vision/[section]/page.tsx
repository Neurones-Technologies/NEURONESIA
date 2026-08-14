import { notFound, redirect } from "next/navigation";
import { View } from "@/components/shell/AppShell";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";
import { ANCIENNES_SECTIONS_DC, isVisionRoute, visionNavMode } from "@/lib/data/sections";
import { SECTION_REGISTRIES } from "@/components/views/vision/registry";

/** Une page par section, pour les profils en mode "route" (cf.
 * lib/data/sections.ts). Chaque section ne charge que ses propres appels API :
 * c'est l'intérêt du découpage face à la page unique, qui les payait tous.
 *
 * Le segment est validé contre `VISION_SECTIONS`, puis le rendu est demandé au
 * registre du profil (cf. views/vision/registry.ts) : une URL inventée tombe en
 * 404 plutôt que de rendre une page vide.
 *
 * `searchParams` porte la cadence de lecture (`?periode=mois|trimestre|annee`) et
 * l'exercice (`?annee=`) des onglets qui en ont une. Passer par l'URL plutôt que
 * par un état client garde ces onglets en composants serveur et rend une lecture
 * partageable par lien ; le registre valide les valeurs et retombe sur ses défauts
 * quand elles sont absurdes. */
export default async function VisionSectionPage({
  params,
  searchParams,
}: {
  params: Promise<{ profile: string; section: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { profile, section } = await params;
  if (!PROFILE_KEYS.includes(profile as ProfileKey)) notFound();
  const key = profile as ProfileKey;

  if (visionNavMode(key) !== "route") notFound();

  const query = await searchParams;
  const premier = (valeur: string | string[] | undefined) =>
    Array.isArray(valeur) ? valeur[0] : valeur;

  // Les quatorze sections DC d'origine avaient chacune leur URL, et ces liens ont
  // circulé. Celles qui sont devenues des vues internes sont redirigées vers la
  // page qui les porte, avec leur `?vue=` — l'écran affiché est le même. Les
  // autres paramètres (cadence, exercice) sont reconduits.
  if (key === "dc" && !isVisionRoute(key, section)) {
    const page = ANCIENNES_SECTIONS_DC[section];
    if (page) {
      const q = new URLSearchParams({ vue: section });
      const periode = premier(query.periode);
      const annee = premier(query.annee);
      if (periode) q.set("periode", periode);
      if (annee) q.set("annee", annee);
      redirect(`/dc/vision/${page}?${q}`);
    }
  }

  if (!isVisionRoute(key, section)) notFound();

  const render = SECTION_REGISTRIES[key]?.[section];
  if (!render) notFound();

  return (
    <View>
      {render({
        periode: premier(query.periode),
        annee: premier(query.annee),
        vue: premier(query.vue),
      })}
    </View>
  );
}
