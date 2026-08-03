import { notFound } from "next/navigation";
import { View } from "@/components/shell/AppShell";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";
import { ArbitrageView } from "@/components/views/ArbitrageView";

/** Le dossier instruit vit dans l'URL (`?dossier=<subject_ref>`) plutôt que dans
 * un état client : un dossier d'arbitrage se discute à plusieurs, son lien doit
 * pouvoir se coller dans un message. */
export default async function ArbitragePage({
  params,
  searchParams,
}: {
  params: Promise<{ profile: string }>;
  searchParams: Promise<{ dossier?: string | string[] }>;
}) {
  const [{ profile }, query] = await Promise.all([params, searchParams]);
  if (!PROFILE_KEYS.includes(profile as ProfileKey)) notFound();
  const key = profile as ProfileKey;
  const selected = Array.isArray(query.dossier) ? query.dossier[0] : query.dossier;

  return (
    <View>
      <ArbitrageView profile={key} selected={selected} />
    </View>
  );
}
