import { notFound } from "next/navigation";
import { View } from "@/components/shell/AppShell";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";
import { CopilotView } from "@/components/views/CopilotView";

export default async function CopilotPage({ params }: { params: Promise<{ profile: string }> }) {
  const { profile } = await params;
  if (!PROFILE_KEYS.includes(profile as ProfileKey)) notFound();
  const key = profile as ProfileKey;

  return (
    <View>
      <CopilotView profile={key} />
    </View>
  );
}
