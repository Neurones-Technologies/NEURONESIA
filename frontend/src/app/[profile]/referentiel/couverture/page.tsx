import { notFound } from "next/navigation";
import { Topbar, View } from "@/components/shell/AppShell";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";
import { CoverageView } from "@/components/views/CoverageView";

export default async function CouverturePage({ params }: { params: Promise<{ profile: string }> }) {
  const { profile } = await params;
  if (!PROFILE_KEYS.includes(profile as ProfileKey)) notFound();

  return (
    <>
      <Topbar crumb="Référentiel · couverture 29 / 29" />
      <View>
        <CoverageView />
      </View>
    </>
  );
}
