import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: {
    /** Cache routeur client — durée de réutilisation d'un payload RSC déjà reçu.
     *
     * Sans ces valeurs, `dynamic` vaut 0 s depuis Next 15 et TOUTES nos routes
     * sont dynamiques (`apiFetch` lit le cookie de session en `no-store`, cf.
     * lib/api/client.ts) : revenir sur une section quittée trois secondes plus
     * tôt rejouait ses appels backend et réaffichait son squelette
     * (`loading.tsx`) — le « rechargement » perçu à chaque navigation.
     *
     * 60 s ne peut pas exposer de données périmées ici : les chiffres viennent
     * du miroir CRM et les narrations sont figées une fois par jour à 6h
     * (backend/modules/uc_daily_analysis). Les mutations restent justes — les
     * Server Actions d'arbitrage appellent `revalidatePath`
     * (lib/actions/arbitrage.ts), ce qui invalide aussi ce cache.
     *
     * `static` (≥ 30 s imposé par Next) s'applique aux liens en
     * `prefetch={true}`, donc au prefetch au survol de components/shell/NavLink.
     */
    staleTimes: { dynamic: 60, static: 300 },
  },
};

export default nextConfig;
