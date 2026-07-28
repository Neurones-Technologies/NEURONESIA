import { notFound } from "next/navigation";
import { Topbar, View } from "@/components/shell/AppShell";
import { META } from "@/lib/data/profiles";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";
import { CopilotView } from "@/components/views/CopilotView";

export default async function CopilotPage({ params }: { params: Promise<{ profile: string }> }) {
  const { profile } = await params;
  if (!PROFILE_KEYS.includes(profile as ProfileKey)) notFound();
  const key = profile as ProfileKey;
  const meta = META[key];

  return (
    <>
      <Topbar crumb={`${meta.name} · Mon Copilote`} context={meta.ctx} />
      <View>
        <CopilotView profile={key} />
      </View>
    </>
  );
}
