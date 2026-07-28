import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { roleToProfile } from "@/lib/auth/roles";

export default async function RootPage() {
  const store = await cookies();
  const role = store.get("role")?.value;
  const profile = role ? roleToProfile(role) : null;
  redirect(`/${profile ?? "dg"}/vision`);
}
