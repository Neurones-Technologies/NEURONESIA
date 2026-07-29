import { ShellSkeleton } from "@/components/ui/skeleton";

// Repli affiché pendant que `[profile]/layout.tsx` résout la session (fetch
// /v1/auth/me) au tout premier chargement — les navigations suivantes entre
// onglets sont couvertes par les `loading.tsx` de chaque page.
export default function Loading() {
  return <ShellSkeleton />;
}
