export type ProfileKey = "dg" | "dc" | "do" | "df" | "am";

export const PROFILE_KEYS: ProfileKey[] = ["dg", "dc", "do", "df", "am"];

export type SectionKey = "vision" | "copilot" | "arbitrage" | "referentiel" | "params";

export type Variant = "r" | "w" | "s" | "n" | "a";

export interface ProfileMeta {
  code: string;
  name: string;
  role: string;
  ctx: string;
  week: string;
  menuLabel: string;
}
