import { notFound, redirect } from "next/navigation";
import { View } from "@/components/shell/AppShell";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";
import { defaultVisionSection, visionNavMode } from "@/lib/data/sections";
import { DoVision } from "@/components/views/vision/DoVision";
import { AmVision } from "@/components/views/vision/AmVision";

function renderVision(key: ProfileKey) {
  switch (key) {
    case "do":
      return <DoVision />;
    case "am":
      return <AmVision />;
    // `dg`, `dc` et `df` sont en mode "route" : jamais rendus ici, redirigés
    // ci-dessous. L'ancienne page unique du DG a été découpée en cinq pages
    // (cf. views/vision/dg/index.tsx).
    default:
      notFound();
  }
}

// Le menu de sections vit dans l'en-tête de la coque (cf. Header.tsx +
// lib/data/sections.ts) : la page ne rend que le contenu de la vue.
//
// Les profils en mode "route" (DC, DF) n'ont pas de page unique : chaque section
// est une page sous [section]/, et cette URL redirige vers la première.
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
