import { notFound } from "next/navigation";
import { Topbar, View } from "@/components/shell/AppShell";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";
import { EnginesView } from "@/components/views/EnginesView";

export default async function MoteursPage({ params }: { params: Promise<{ profile: string }> }) {
  const { profile } = await params;
  if (!PROFILE_KEYS.includes(profile as ProfileKey)) notFound();

  return (
    <>
      <Topbar crumb="Référentiel · moteurs et données" />
      <View>
        <EnginesView />
      </View>
    </>
  );
}
