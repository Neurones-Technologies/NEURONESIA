export interface EngineData {
  code: string;
  title: string;
  desc: string;
  tag: string;
  feeds: string;
  note: string;
  isLlm?: boolean;
}

export const ENGINES: EngineData[] = [
  {
    code: "M1",
    title: "Rupture de rythme",
    desc: "Écart entre le délai depuis le dernier événement et l'intervalle habituel du compte.",
    tag: "6 modules",
    feeds: "03 radar de dépendance · 08 cross-sell · 18 exposition · 22 next best action · 23 alerte rythme · 24 renouvellement",
    note: "Entrées : sale.order, account.move. Paramètre unique par compte : intervalle médian et dispersion sur 24 mois. Seuil de départ : dernier délai > médiane + 1,5 écart, minimum 3 commandes d'historique.",
  },
  {
    code: "M2",
    title: "Dérive de délai",
    desc: "Glissement d'un délai réel constaté par rapport à son engagement et à son propre historique.",
    tag: "4 modules",
    feeds: "14 fiabilité fournisseurs · 16 encaissement comportemental · 17 dérive de paiement · 18 exposition",
    note: "Entrées : account.move et dates de paiement côté client, purchase.order et dates de réception côté fournisseur. Même calcul, deux sens. Seuil de départ : pente positive sur 3 mois consécutifs et écart > 10 jours.",
  },
  {
    code: "M3",
    title: "Écart backlog / facturation",
    desc: "Différence entre la courbe de facturation réelle et la courbe théorique du contrat.",
    tag: "7 modules",
    feeds: "02 atterrissage · 11 consommation backlog · 12 visibilité · 13 dérive d'affaire · 20 anomalies · 22 next best action · 24 renouvellement",
    note: "Entrées : sale.order.line, account.move.line, rattachement commande / facture. C'est le moteur le plus transverse, et celui dont la qualité dépend le plus du taux de rattachement mesuré au profiling.",
  },
  {
    code: "M4",
    title: "Écart prix achat / vente",
    desc: "Évolution comparée du prix d'achat et du prix de vente sur une même référence ou compétence.",
    tag: "5 modules",
    feeds: "03 radar de dépendance · 04 écart budgétaire · 15 tension sous-traitance · 19 effet ciseau · 20 anomalies",
    note: "Entrées : purchase.order.line, sale.order.line, référentiel de familles normalisé. Prérequis bloquant : sans normalisation des libellés, ce moteur ne produit rien d'exploitable.",
  },
  {
    code: "M5",
    title: "Scoring pipeline",
    desc: "Probabilité et crédibilité d'une opportunité, calibrées sur la fiabilité historique observée.",
    tag: "5 modules",
    feeds: "02 atterrissage · 06 crédibilité forecast · 07 opportunités à risque · 09 motifs de perte · 10 coaching",
    note: "Entrées : crm.lead et surtout les snapshots quotidiens. Seul moteur dont l'existence dépend d'une décision à prendre immédiatement : Odoo écrase les états, l'historique non capté aujourd'hui est définitivement perdu.",
  },
  {
    code: "LLM",
    title: "Couche de narration",
    desc: "Ni détecteur ni prédicteur : elle met en mots, hiérarchise et rédige ce que les cinq moteurs ont détecté.",
    tag: "11 modules",
    feeds: "01 briefing · 04 écart budgétaire · 05 langage naturel · 06 crédibilité · 09 motifs de perte · 10 coaching · 21 fiche compte · 22 next best action · 25 rédaction · 26 file d'arbitrage · 27 dossier d'arbitrage",
    note: "Choix assumé · pas de prévision chiffrée par apprentissage. Le volume de données — quelques milliers d'opportunités et de factures — ne le justifie pas, et un score non explicable ne survit pas à un comité de direction. Chaque affirmation produite par cette couche cite son moteur, son chiffre déclencheur et son seuil.",
    isLlm: true,
  },
  {
    code: "REG",
    title: "Registre de décisions",
    desc: "Ni détecteur ni narrateur : il conserve les options soumises, l'option retenue, son propriétaire, sa date de revue et ce qui s'est réellement passé ensuite.",
    tag: "4 modules",
    feeds: "26 file d'arbitrage · 27 dossier d'arbitrage · 28 engagements et revues · 29 fiabilité des recommandations",
    note: "Entrées : sorties horodatées des cinq moteurs, décisions saisies, et magasin d'instantanés pour la vérification rétrospective. C'est le seul composant qui rend l'outil auditable : sans lui, aucune recommandation n'est vérifiable après coup et l'outil ne peut pas démontrer sa valeur.",
  },
];

export const ENGINES_CLOSING_NOTE =
  "Deux décisions restent à prendre avant le développement · lancer le snapshot quotidien cette semaine, avant toute autre chose. Et cadrer deux à trois semaines de profiling qualité : taux de remplissage des dates et montants d'opportunités, cohérence des libellés produits, taux de rattachement facture / commande. Ces trois pourcentages déterminent lesquels des vingt-cinq modules sont honnêtement livrables.";
