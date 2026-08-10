import { notFound, redirect } from "next/navigation";
import { View } from "@/components/shell/AppShell";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";
import { defaultVisionSection, visionNavMode } from "@/lib/data/sections";
import { DgVision } from "@/components/views/vision/DgVision";
import { DoVision } from "@/components/views/vision/DoVision";
import { DfVision } from "@/components/views/vision/DfVision";
import { AmVision } from "@/components/views/vision/AmVision";

function renderVision(key: ProfileKey) {
  switch (key) {
    case "dg":
      return <DgVision />;
    case "do":
      return <DoVision />;
    case "df":
      return <DfVision />;
    case "am":
      return <AmVision />;
    // `dc` est en mode "route" : jamais rendu ici, redirigé ci-dessous.
    default:
      notFound();
  }
}

// Le menu de sections vit dans l'en-tête de la coque (cf. Header.tsx +
// lib/data/sections.ts) : la page ne rend que le contenu de la vue.
//
// Les profils en mode "route" (DC) n'ont pas de page unique : chaque section est
// une page sous [section]/, et cette URL redirige vers la première.
export default async function VisionPage({ params }: { params: Promise<{ profile: string }> }) {
  const { profile } = await params;
  if (!PROFILE_KEYS.includes(profile as ProfileKey)) notFound();
  const key = profile as ProfileKey;

  if (visionNavMode(key) === "route") {
    const first = defaultVisionSection(key);
    if (first) redirect(`/${key}/vision/${first}`);
  }

  return <View>{renderVision(key)}</View>;
}
