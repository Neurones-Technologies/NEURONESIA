# Questions de cadrage — Cockpit Directeur Commercial

**Objet** : lever les zones d'ombre du compte-rendu du 04/08/2026 avant rédaction du cahier des charges du cockpit DC
**Destinataire** : Directeur Commercial
**Périmètre** : cockpit DC uniquement

---

## Avertissement de lecture

Ce document ne remet pas en cause les besoins exprimés. Il liste les **décisions manquantes** sans lesquelles plusieurs demandes ne peuvent pas être traduites en spécifications.

Trois natures de points s'y mêlent :

- des **définitions à trancher** (que veut dire « pic d'activité », « ratio d'efficacité », « à compléter ») ;
- des **données absentes du système** qu'aucun développement ne peut inventer (objectifs commerciaux, historique des étapes, secteur d'activité, activité de prospection) ;
- des **arbitrages de périmètre** (le fichier de visite relève de la saisie terrain, pas du pilotage DC).

Les blocs marqués ⚠️ signalent une contrainte technique à porter à la connaissance du DC pendant l'échange — elle change souvent la réponse qu'il donnera.

---

## 1. Objectifs commerciaux et le chiffre « 30 millions »

> **Point le plus bloquant du dossier.** Aucun objectif commercial n'existe aujourd'hui dans le système : ni table, ni champ, ni import. Tout indicateur d'écart vs objectif est donc impossible en l'état.

### Questions

1. « 30 millions » : en FCFA ou en euros ?
2. Le compte-rendu emploie ce chiffre à deux endroits avec deux sens différents — seuil de traçage du cycle de vie (§2) et objectif de vente (§3). S'agit-il du même chiffre ?
3. L'objectif de 30 M porte sur qui et sur quelle période : par commercial et par an ? Par affaire ? Pour l'équipe entière ?
4. Où vivent les objectifs aujourd'hui — un fichier Excel, une note, une décision orale ?
5. Qui les fixe, et à quelle fréquence sont-ils révisés en cours d'année ?
6. À quelle maille voulez-vous lire le Gap : par commercial, par secteur, par trimestre — ou les trois croisés ?
7. Le volume de leads annuel à générer était illisible sur la note manuscrite : quel est le chiffre ?

⚠️ **À signaler au DC** : le briefing quotidien qui vous est adressé demande déjà à l'IA de commenter « la couverture de l'équipe par rapport aux objectifs », alors qu'aucun objectif ne lui est fourni. Le texte produit sur ce point est donc à considérer comme non fiable tant que la question n'est pas tranchée.

---

## 2. Cycle de vie des opportunités (seuil 30 M)

### Questions

8. « Tracer de bout en bout » signifie quoi concrètement : voir la chronologie d'une affaire (dates de passage d'étape), la durée passée à chaque étape, ou les deux ?
9. À quoi sert cette trace au quotidien : détecter les affaires enlisées, mesurer la vélocité moyenne de l'équipe, ou justifier a posteriori une perte ?
10. Combien d'affaires le seuil de 30 M représente-t-il selon vous — une vingtaine par an, ou plusieurs centaines ?

⚠️ **À signaler au DC** : l'historique des changements d'étape n'est pas conservé aujourd'hui — le système écrase l'étape précédente à chaque mise à jour. On sait où en est une affaire, pas par où elle est passée ni depuis combien de temps elle stagne. Cette donnée existe bien dans l'ERP, elle n'est simplement pas récupérée. C'est un chantier technique à part entière.

---

## 3. Comptes dormants et actifs

> Un moteur de détection existe déjà et classe les comptes selon leur rythme de commande. Ses seuils sont aujourd'hui des valeurs par défaut, jamais validées métier.

### Questions

11. À partir de combien de temps sans commande considérez-vous un compte comme dormant — 6 mois, 12 mois, autre ?
12. Le silence se mesure sur les commandes signées ou sur les opportunités créées ? Un compte qui génère des opportunités sans jamais signer est-il dormant ou actif ?
13. « Dynamiser les comptes » : attendez-vous une liste d'actions à mener (« relancer ces 12 comptes cette semaine ») ou un simple suivi d'état ?
14. Faut-il une catégorie intermédiaire entre dormant et actif — un compte « qui ralentit » ?
15. Un compte dormant qui présente aussi des impayés doit-il être traité différemment des autres ?

---

## 4. Détection des pics d'activité

> Le terme n'est pas défini dans le compte-rendu et recouvre trois réalités très différentes, dont une seule est mesurable aujourd'hui.

### Questions

16. Un pic d'activité, de votre point de vue, c'est quoi : le client commande davantage que d'habitude ? Il sollicite davantage (demandes de devis, rendez-vous) ? Ou une actualité externe le concerne (levée de fonds, appel d'offres, nouveau projet) ?
17. **La dernière fois qu'un compte a fait un pic, comment l'avez-vous appris ?**
18. Le pic se mesure-t-il par rapport au passé du compte (il commande trois fois plus que d'habitude) ou dans l'absolu (au-dessus d'un certain montant) ?
19. Sur quel horizon un pic est-il pertinent : la semaine, le mois, le trimestre ?

⚠️ **À signaler au DC** : si le signal de pic provient de rendez-vous, d'appels ou d'échanges par e-mail, cette donnée n'existe pas dans le système — elle n'est pas remontée de l'ERP. Seul le rythme de commande est mesurable en l'état.

---

## 5. Alertes proactives

### Questions

20. Une alerte doit atteindre le commercial où : dans l'application quand il l'ouvre, par e-mail, sur son téléphone ?
21. Quelle latence est acceptable : temps réel, tous les matins, une fois par semaine ?
22. Qui reçoit l'alerte : le commercial concerné seul, ou vous en copie ?
23. Combien d'alertes par semaine avant que cela devienne du bruit que l'on ignore ?
24. Que doit contenir une alerte pour être utile : le constat seul, ou le constat plus l'action recommandée ?

⚠️ **À signaler au DC** : aucun canal de diffusion sortant n'existe aujourd'hui — ni e-mail, ni notification mobile, ni SMS. Une alerte ne peut pour l'instant s'afficher que dans l'application. Ouvrir un canal externe est un chantier technique distinct.

---

## 6. Indice d'efficacité par commercial

### Questions

25. « Ratio de deals » : quel numérateur et quel dénominateur ? Deals gagnés sur deals traités ? CA signé sur pipeline généré ? Deals sur temps écoulé ?
26. Un commercial qui signe peu d'affaires mais de gros montants est-il plus efficace qu'un qui en signe beaucoup de petites ? La réponse détermine si l'indice est pondéré par le montant.
27. L'indice sert-il à comparer les commerciaux entre eux, ou à suivre la progression de chacun dans le temps ?
28. Faut-il neutraliser l'effet du portefeuille hérité ? Un commercial sur grands comptes historiques n'est pas comparable à un chasseur de nouveaux clients.
29. Sur quelle période l'indice se lit-il : glissante sur 12 mois, par trimestre, depuis le début de l'année ?

⚠️ **À signaler au DC** : les commerciaux sont aujourd'hui de simples champs texte dans les données, sans référentiel. Une même personne apparaît sous plusieurs orthographes, et il n'existe aucune notion d'équipe, de manager ni de territoire. Un classement fiable suppose de fiabiliser ce référentiel au préalable.

---

## 7. Indice de prospection

### Questions

30. « Nombre d'opportunités générées » : comptez-vous toute opportunité créée, ou seulement celles atteignant un montant ou une qualification minimale ?
31. Distinguez-vous un lead d'une opportunité ? Si oui, à quel moment un lead devient-il une opportunité ?
32. Le focus « nouveaux comptes / nouveaux clients » : un nouveau compte, c'est un compte jamais facturé, ou un compte dormant réactivé ?
33. L'indice doit-il être lu par commercial, ou pour l'équipe globale ?

⚠️ **À signaler au DC** : seules les opportunités sont remontées de l'ERP, pas les leads en amont. Un objectif exprimé en « volume de leads » n'est pas mesurable en l'état.

---

## 8. Analyse sectorielle et part de marché

> Point mort du dossier en l'état actuel des données.

### Questions

34. **Le secteur d'activité n'est renseigné que pour un client sur environ 1 400.** Qui peut le renseigner, sur quelle nomenclature, et dans quel délai ?
35. Quelle granularité de secteur souhaitez-vous : une dizaine de grandes catégories (Banque, Télécom, Public, Industrie…), ou plus fin ?
36. S'agit-il du secteur du client, ou du domaine de l'offre vendue ? Le compte-rendu évoque « la santé du marché orienté IA et infrastructure », ce qui renvoie plutôt à l'offre.
37. « Part de marché » par rapport à quel univers de référence ?
38. Disposez-vous d'une source externe de taille de marché (étude, syndicat professionnel, données publiques) ?

⚠️ **À signaler au DC** : sans donnée de marché externe, nous ne pouvons calculer qu'une part de notre propre portefeuille — pas une part de marché réelle. Ce sont deux indicateurs très différents, et les confondre conduirait à des décisions erronées.

---

## 9. Opportunités à closer et à compléter

### Questions

39. « À compléter » signifie quoi précisément : quels champs manquants rendent un dossier incomplet ? Montant ? Date d'échéance ? Interlocuteur décideur ? Autre ?
40. Existe-t-il une règle de complétude déjà admise dans l'équipe, ou faut-il la définir ?
41. « À closer » désigne-t-il une étape précise du pipeline, ou une échéance proche ?
42. Que doit-il se passer quand une opportunité reste incomplète trop longtemps ?

---

## 10. Fichier de visite et comptes rendus

### Questions

43. Qui saisit le compte rendu de visite : le commercial, l'account manager, vous ?
44. Quand est-il saisi : au retour de visite depuis un mobile, ou le soir au bureau ?
45. Que contient un compte rendu minimal : date, compte, interlocuteur, sujet, prochaine action ? Autre chose ?
46. Souhaitez-vous lire les comptes rendus, ou seulement suivre un taux de couverture (« ce compte n'a pas été visité depuis quatre mois ») ?
47. Une visite doit-elle être rattachée à une opportunité, ou seulement à un compte ?

⚠️ **À signaler au DC** : il s'agit d'un module de saisie destiné aux commerciaux, et non d'un indicateur de pilotage. Le traiter séparément permettrait de livrer plus vite sur le cockpit lui-même.

---

## 11. Cadence de revue et aide à la décision

### Questions

48. Le point mensuel, trimestriel et annuel porte-t-il sur les mêmes indicateurs à trois fréquences, ou sur des indicateurs différents selon l'horizon ?
49. Quelles sont les trois questions que vous vous posez systématiquement en revue de performance, et auxquelles vous n'avez pas de réponse aujourd'hui ?
50. Sur le « comment améliorer » : attendez-vous des recommandations générales (« relancer les comptes dormants ») ou nominatives et actionnables (« appeler tel interlocuteur chez tel client avant vendredi ») ?
51. Une recommandation doit-elle pouvoir être marquée comme suivie ou écartée, pour mesurer ensuite si elle a produit un effet ?
52. Combien de temps consacrez-vous à la lecture du cockpit lors d'une session type ?

---

## Les trois questions prioritaires

Si l'échange doit être court, ces trois questions débloquent le plus grand nombre de sujets.

| # | Question | Ce qu'elle débloque |
|---|---|---|
| 1 | 30 millions, en FCFA ou en euros — et est-ce le même chiffre aux deux endroits du compte-rendu ? | Tout le dimensionnement : objectifs, seuil de cycle de vie, calibrage des indicateurs |
| 2 | La dernière fois qu'un compte a fait un pic d'activité, comment l'avez-vous appris ? | Révèle si le signal de pic est présent dans nos données ou non — donc si la fonctionnalité est réalisable |
| 3 | Le secteur d'activité de vos clients, qui peut le renseigner ? | Sans réponse, toute l'analyse sectorielle reste morte quel que soit le développement réalisé |

---

## Récapitulatif des contraintes à porter à la connaissance du DC

| Besoin exprimé | Contrainte |
|---|---|
| Gap vendu vs objectif | Aucun objectif n'existe dans le système — donnée à créer |
| Cycle de vie de bout en bout | L'historique des étapes n'est pas conservé — présent dans l'ERP, à récupérer |
| Analyse sectorielle | Secteur renseigné pour 1 client sur ~1 400 — chantier de saisie amont |
| Alerte proactive | Aucun canal sortant (e-mail, mobile, SMS) — infrastructure à créer |
| Indice de prospection sur leads | Seules les opportunités sont remontées, pas les leads |
| Pics d'activité par sollicitation | Rendez-vous, appels et e-mails ne sont pas remontés — seul le rythme de commande est mesurable |
| Classement des commerciaux | Commerciaux stockés en texte libre, sans référentiel ni équipe |
| Fichier de visite | Module de saisie terrain — hors périmètre du cockpit de pilotage |

---

## Points d'incohérence relevés dans le compte-rendu

À faire confirmer par le DC lors de l'échange :

1. **§2** annonce « trois critères combinés » puis n'en énumère que deux : le nombre d'opportunités à venir et le CA déjà réalisé. Quel est le troisième ?
2. **« 30 millions »** apparaît en §2 comme seuil de traçage et en §3 comme objectif de vente. Même chiffre ou coïncidence ?
3. **Le volume de leads annuel** est signalé comme illisible sur la note manuscrite — à reconfirmer.

---

*Document de travail établi à partir du compte-rendu du 04/08/2026 et de l'analyse des données disponibles dans l'application.*
