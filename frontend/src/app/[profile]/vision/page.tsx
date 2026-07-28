import { notFound } from "next/navigation";
import { View } from "@/components/shell/AppShell";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";
import { DgVision } from "@/components/views/vision/DgVision";
import { DcVision } from "@/components/views/vision/DcVision";
import { DoVision } from "@/components/views/vision/DoVision";
import { DfVision } from "@/components/views/vision/DfVision";
import { AmVision } from "@/components/views/vision/AmVision";

function renderVision(key: ProfileKey) {
  switch (key) {
    case "dg":
      return <DgVision />;
    case "dc":
      return <DcVision />;
    case "do":
      return <DoVision />;
    case "df":
      return <DfVision />;
    case "am":
      return <AmVision />;
  }
}

// Le menu de sections vit dans l'en-tête de la coque (cf. Header.tsx +
// lib/data/sections.ts) : la page ne rend que le contenu de la vue.
export default async function VisionPage({ params }: { params: Promise<{ profile: string }> }) {
  const { profile } = await params;
  if (!PROFILE_KEYS.includes(profile as ProfileKey)) notFound();
  const key = profile as ProfileKey;

  return <View>{renderVision(key)}</View>;
}
