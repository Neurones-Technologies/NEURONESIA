import { notFound } from "next/navigation";
import { Topbar, View } from "@/components/shell/AppShell";
import { META } from "@/lib/data/profiles";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";
import { ArbitrageView } from "@/components/views/ArbitrageView";

export default async function ArbitragePage({ params }: { params: Promise<{ profile: string }> }) {
  const { profile } = await params;
  if (!PROFILE_KEYS.includes(profile as ProfileKey)) notFound();
  const key = profile as ProfileKey;
  const meta = META[key];

  return (
    <>
      <Topbar crumb={`${meta.name} · Arbitrages`} context={meta.ctx} />
      <View>
        <ArbitrageView profile={key} />
      </View>
    </>
  );
}
