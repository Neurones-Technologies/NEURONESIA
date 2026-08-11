import { cache } from "react";
import { apiFetch } from "./client";

/** Identité renvoyée par `/v1/auth/me` (backend/core/domain/user.py). */
export interface Me {
  id: number;
  email: string;
  full_name: string;
  role: string;
  /** `null` = aucune restriction de périmètre (administrateur). */
  allowed_views: string[] | null;
  last_login: string | null;
}

/** `/v1/auth/me`, dédupliqué sur le rendu en cours.
 *
 * Le layout de profil lit déjà l'identité pour peupler le shell, et les vues
 * qui en ont besoin (arbitrage, réglages, données) la redemandaient : deux
 * appels réseau identiques par rendu. `cache()` de React les fond en un seul.
 *
 * La mémoïsation ne vit que le temps d'un rendu serveur — elle ne met rien en
 * cache d'une requête à l'autre, l'identité reste donc relue à chaque
 * navigation non servie par le cache routeur (cf. next.config.ts). */
export const getMe = cache(() => apiFetch<Me>("/v1/auth/me"));
