import { notFound } from "next/navigation";
import { View } from "@/components/shell/AppShell";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";
import { ArbitrageView } from "@/components/views/ArbitrageView";

export default async function ArbitragePage({ params }: { params: Promise<{ profile: string }> }) {
  const { profile } = await params;
  if (!PROFILE_KEYS.includes(profile as ProfileKey)) notFound();
  const key = profile as ProfileKey;

  return (
    <View>
      <ArbitrageView profile={key} />
    </View>
  );
}
