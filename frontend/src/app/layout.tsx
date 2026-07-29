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
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="fr" className={`${disp.variable} ${sans.variable} ${mono.variable}`}>
      {/* suppressHydrationWarning : certaines extensions de navigateur
          (ColorZilla, gestionnaires de mots de passe…) ajoutent des attributs
          sur <body> avant l'hydratation — ex. `cz-shortcut-listen`. React
          signalait alors une divergence serveur/client qui ne vient pas du
          code. La suppression ne porte que sur les attributs de cet élément. */}
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
