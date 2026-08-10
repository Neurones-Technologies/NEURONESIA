import { notFound } from "next/navigation";
import { View } from "@/components/shell/AppShell";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";
import { isVisionSection, visionNavMode } from "@/lib/data/sections";
import { DC_SECTIONS } from "@/components/views/vision/dc";

/** Une page par section, pour les profils en mode "route" (cf.
 * lib/data/sections.ts). Chaque section ne charge que ses propres appels API :
 * c'est l'intérêt du découpage face à la page unique, qui les payait tous.
 *
 * Le segment est validé contre `VISION_SECTIONS` : une URL inventée tombe en 404
 * plutôt que de rendre une page vide. */
export default async function VisionSectionPage({
  params,
}: {
  params: Promise<{ profile: string; section: string }>;
}) {
  const { profile, section } = await params;
  if (!PROFILE_KEYS.includes(profile as ProfileKey)) notFound();
  const key = profile as ProfileKey;

  if (visionNavMode(key) !== "route") notFound();
  if (!isVisionSection(key, section)) notFound();

  const render = key === "dc" ? DC_SECTIONS[section] : undefined;
  if (!render) notFound();

  return <View>{render()}</View>;
}
