import { ReactNode } from "react";
import { ProfileKey } from "@/lib/types";
import { META } from "@/lib/data/profiles";
import { Rail } from "./Rail";
import { Header } from "./Header";
import { DetailProvider } from "@/components/ui/detail";

export interface ShellUser {
  code: string;
  fullName: string;
  roleLabel: string;
  isAdmin: boolean;
}

export function AppShell({
  profile,
  user,
  children,
}: {
  profile: ProfileKey;
  user: ShellUser;
  children: ReactNode;
}) {
  return (
    <DetailProvider>
      <div className="app live">
        <Rail profile={profile} code={user.code} />
        <div className="stage">
          <Header profile={profile} user={{ ...user, menuLabel: META[profile].menuLabel }} />
          <main className="canvas">{children}</main>
        </div>
      </div>
    </DetailProvider>
  );
}

export function Topbar({ crumb, context }: { crumb: string; context?: string }) {
  return (
    <div className="topbar-wrap">
      <div className="topbar">
        <div className="crumb">{crumb}</div>
        <div className="topbar-r">{context && <span className="chip">{context}</span>}</div>
      </div>
    </div>
  );
}

export function View({ children }: { children: ReactNode }) {
  return <section className="view">{children}</section>;
}
