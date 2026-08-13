import type { Metadata } from "next";
import { IBM_Plex_Mono, Inter, Outfit } from "next/font/google";
import "./globals.css";

const disp = Outfit({
  variable: "--font-disp",
  subsets: ["latin"],
  weight: ["200", "300", "400", "500"],
});

const sans = Inter({
  variable: "--font-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const mono = IBM_Plex_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Neurones Intelligence — cockpit décisionnel",
  description: "Cockpit décisionnel · miroir Odoo",
  // Doublon volontaire de app/robots.ts : robots.txt règle l'exploration,
  // ce <meta> règle l'indexation. Un crawler qui a déjà l'URL (lien, historique,
  // barre d'adresse) peut indexer une page sans jamais relire robots.txt — seule
  // /login est atteignable sans session, c'est donc elle qu'on protège ici.
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="fr"
      className={`${disp.variable} ${sans.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      {/* suppressHydrationWarning (html + body) : certaines extensions de
          navigateur (ColorZilla, gestionnaires de mots de passe, LanguageTool…)
          ajoutent des attributs sur <html> ou <body> avant l'hydratation — ex.
          `cz-shortcut-listen`, `data-lt-installed`. React signalait alors une
          divergence serveur/client qui ne vient pas du code. La suppression ne
          porte que sur les attributs de ces éléments. */}
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
