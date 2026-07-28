import { notFound } from "next/navigation";
import { Topbar, View } from "@/components/shell/AppShell";
import { META } from "@/lib/data/profiles";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";
import { ParamsView } from "@/components/views/ParamsView";

export default async function ParamsPage({ params }: { params: Promise<{ profile: string }> }) {
  const { profile } = await params;
  if (!PROFILE_KEYS.includes(profile as ProfileKey)) notFound();
  const key = profile as ProfileKey;
  const meta = META[key];

  return (
    <>
      <Topbar crumb={`${meta.name} · Paramètres`} context={meta.ctx} />
      <View>
        <ParamsView profile={key} />
      </View>
    </>
  );
}
