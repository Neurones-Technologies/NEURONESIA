import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import "./globals.css";

/** Fonte de TITRAGE et de CHIFFRES.
 *
 * Space Grotesk remplace Outfit. Outfit est une géométrique neutre — la fonte
 * d'affichage la plus employée des tableaux de bord générés, sans voix propre :
 * ses chiffres, qui sont pourtant le sujet de l'application, se lisaient comme
 * un titre de page d'accueil.
 *
 * Space Grotesk est une grotesque à contrastes rompus : terminaisons coupées,
 * `1` à empattement, `4` fermé, `7` barré selon la graisse. Elle donne aux
 * montants une allure d'instrument plutôt que de mise en page, ce que demande
 * un cockpit de décision. Ses chiffres sont tabulaires par défaut, ce dont
 * dépendent toutes les colonnes chiffrées de l'interface.
 *
 * Les graisses 300/400/500 d'Outfit sont conservées côté CSS ; Space Grotesk
 * n'en descend pas sous 300, la borne basse est donc portée à 300 ici. */
const disp = Space_Grotesk({
  variable: "--font-disp",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
});

const sans = Inter({
  variable: "--font-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

/** Fonte des ÉTIQUETTES et des mesures.
 *
 * JetBrains Mono remplace IBM Plex Mono : même rôle, mais un dessin plus étroit
 * à hauteur d'x plus grande, donc lisible à 9 px — la taille réelle des kickers
 * et des étiquettes de graphe de cette interface, où Plex Mono commençait à se
 * fermer. */
const mono = JetBrains_Mono({
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
