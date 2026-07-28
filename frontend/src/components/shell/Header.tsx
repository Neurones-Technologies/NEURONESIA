"use client";

import { usePathname } from "next/navigation";
import { ProfileKey } from "@/lib/types";
import { SECTION_LABELS } from "@/lib/data/profiles";
import { VISION_SECTIONS } from "@/lib/data/sections";
import { SectionNav } from "./SectionNav";
import { UserMenu } from "./UserMenu";

function currentSectionKey(pathname: string, profile: ProfileKey): string {
  const rest = pathname.replace(`/${profile}/`, "").replace(`/${profile}`, "");
  return rest.split("/")[0] || "vision";
}

export function Header({
  profile,
  user,
}: {
  profile: ProfileKey;
  user: { code: string; fullName: string; roleLabel: string; isAdmin: boolean; menuLabel: string };
}) {
  const pathname = usePathname();

  const sectionKey = currentSectionKey(pathname, profile);
  // Sur la vue Cockpit, le menu de sections prend la place du bloc titre :
  // il porte déjà l'information de navigation, le titre serait redondant.
  const sections = sectionKey === "vision" ? VISION_SECTIONS[profile] : undefined;

  return (
    <header className="hdr">
      {sections && sections.length > 0 ? (
        <SectionNav items={sections} />
      ) : (
        <div className="hdr-t">
          <b>{SECTION_LABELS[sectionKey] ?? "Cockpit"}</b>
          <span>
            {user.roleLabel} · {user.menuLabel}
          </span>
        </div>
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
