"use client";

import { usePathname } from "next/navigation";
import { ProfileKey } from "@/lib/types";
import { VISION_SECTIONS, visionNavMode } from "@/lib/data/sections";
import { SectionNav } from "./SectionNav";
import { UserMenu } from "./UserMenu";

function currentSectionKey(pathname: string, profile: ProfileKey): string {
  const rest = pathname.replace(`/${profile}/`, "").replace(`/${profile}`, "");
  return rest.split("/")[0] || "vision";
}

/** Segment de section d'une vue en mode `"route"` : `/dc/vision/pipeline`
 * → `"pipeline"`. Vide sur `/dc/vision` (avant la redirection). */
function currentVisionSection(pathname: string, profile: ProfileKey): string | undefined {
  const rest = pathname.replace(`/${profile}/`, "").replace(`/${profile}`, "");
  return rest.split("/")[1] || undefined;
}

/** En-tête de la coque : les onglets de section (scroll-spy) quand la page en
 * définit, sinon rien à gauche — pas de fil d'Ariane ni de sous-titre de
 * rôle/menu redondant avec le rail et la puce de profil. Le sélecteur de
 * profil reste plaqué à droite dans tous les cas (cf. `.psel` dans
 * globals.css). */
export function Header({
  profile,
  user,
}: {
  profile: ProfileKey;
  user: { code: string; fullName: string; roleLabel: string; isAdmin: boolean; menuLabel: string };
}) {
  const pathname = usePathname();

  const sectionKey = currentSectionKey(pathname, profile);
  const sections = sectionKey === "vision" ? VISION_SECTIONS[profile] : undefined;
  const navMode = visionNavMode(profile);

  return (
    <header className="hdr">
      {sections && sections.length > 0 && (
        <SectionNav
          items={sections}
          mode={navMode}
          basePath={`/${profile}/vision`}
          active={navMode === "route" ? currentVisionSection(pathname, profile) : undefined}
        />
      )}

      <UserMenu
        profile={profile}
        code={user.code}
        fullName={user.fullName}
        roleLabel={user.roleLabel}
        isAdmin={user.isAdmin}
      />
    </header>
  );
}
