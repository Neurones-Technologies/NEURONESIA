import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login"];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    return NextResponse.next();
  }

  const hasSession = request.cookies.has("session");
  if (!hasSession) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

// `robots.txt` doit figurer dans l'exclusion : le matcher est une liste de
// négations, et `.txt` n'entre dans aucune des autres (ni `api`, ni `_next/*`,
// ni les extensions d'images). Sans elle, la requête anonyme d'un crawler sur
// /robots.txt part en 307 vers /login et le crawler reçoit un 200 + HTML au lieu
// du fichier produit par app/robots.ts.
export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|robots.txt|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
