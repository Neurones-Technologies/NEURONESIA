import { notFound, redirect } from "next/navigation";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";

/** `/dg` (profil sans section) n'est pas une page : on renvoie sur le Cockpit,
 * qui est l'entrée par défaut du profil. Sans cette route, l'URL du profil seul
 * répondait 404. */
export default async function ProfileRootPage({ params }: { params: Promise<{ profile: string }> }) {
  const { profile } = await params;
  if (!PROFILE_KEYS.includes(profile as ProfileKey)) notFound();
  redirect(`/${profile}/vision`);
}
