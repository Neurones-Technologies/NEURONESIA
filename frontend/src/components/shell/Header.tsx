"use client";

import { usePathname } from "next/navigation";
import { ProfileKey } from "@/lib/types";
import {
  firstSectionOfGroup,
  groupOfSection,
  sectionsOfGroup,
  VISION_SECTIONS,
  visionGroups,
  visionNavMode,
} from "@/lib/data/sections";
import { GroupNav, SectionNav } from "./SectionNav";
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
 * globals.css).
 *
 * DEUX NIVEAUX quand le profil déclare des chapitres (`VISION_GROUPS`) : le cockpit
 * DC porte quatorze écrans, qui sur une seule rangée débordaient derrière un
 * ascenseur horizontal — la moitié du menu restait hors de vue, et rien ne disait
 * qu'il y avait autre chose. Les chapitres tiennent sur une ligne, et la seconde
 * rangée ne montre que les écrans du chapitre ouvert.
 *
 * Un profil sans chapitres (DG en scroll-spy, DAF et ses cinq onglets) garde
 * exactement le rendu d'avant : une seule rangée. */
export function Header({
  profile,
  user,
}: {
  profile: ProfileKey;
  user: { code: string; fullName: string; roleLabel: string; isAdmin: boolean; menuLabel: string };
}) {
  const pathname = usePathname();

  const sectionKey = currentSectionKey(pathname, profile);
  const surVision = sectionKey === "vision";
  const sections = surVision ? VISION_SECTIONS[profile] : undefined;
  const navMode = visionNavMode(profile);
  const groups = surVision ? visionGroups(profile) : undefined;

  const sectionActive = navMode === "route" ? currentVisionSection(pathname, profile) : undefined;
  const groupActif = groups ? (groupOfSection(profile, sectionActive) ?? groups[0]?.id) : undefined;
  const sousSections = groups && groupActif ? sectionsOfGroup(profile, groupActif) : undefined;

  // Menu long ET pages coûteuses : le préchargement au montage est remplacé par un
  // préchargement au survol (cf. NavLink). Onze liens visibles × 0,6 à 1,6 s de
  // rendu serveur, à chaque navigation, pour des écrans que l'utilisateur n'ouvre
  // pas tous — le calcul ne tient pas.
  const eager = !groups;

  const menu = groups ? (
    <GroupNav
      groups={groups}
      active={groupActif}
      eager={eager}
      hrefOf={(g) => {
        const premiere = firstSectionOfGroup(profile, g.id);
        return premiere ? `/${profile}/vision/${premiere}` : `/${profile}/vision`;
      }}
    />
  ) : sections && sections.length > 0 ? (
    <SectionNav items={sections} mode={navMode} basePath={`/${profile}/vision`} active={sectionActive} />
  ) : null;

  const utilisateur = (
    <UserMenu
      profile={profile}
      code={user.code}
      fullName={user.fullName}
      roleLabel={user.roleLabel}
      isAdmin={user.isAdmin}
    />
  );

  // Un chapitre à un seul écran n'affiche pas de seconde rangée : elle ne
  // proposerait qu'un onglet, déjà actif.
  const avecSousMenu = Boolean(sousSections && sousSections.length > 1);

  if (!avecSousMenu) {
    return (
      <header className="hdr">
        {menu}
        {utilisateur}
      </header>
    );
  }

  return (
    <header className="hdr hdr--stacked">
      <div className="hdr-row">
        {menu}
        {utilisateur}
      </div>
      <SectionNav
        items={sousSections!}
        mode="route"
        variant="sub"
        basePath={`/${profile}/vision`}
        active={sectionActive}
        eager={eager}
      />
    </header>
  );
}
