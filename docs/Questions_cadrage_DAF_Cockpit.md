# Questions de cadrage — Cockpit Directeur Administratif et Financier

**Objet** : lever les zones d'ombre du compte-rendu du 04/08/2026 avant rédaction du cahier des charges du cockpit DAF
**Destinataire** : Directeur Administratif et Financier
**Périmètre** : cockpit DAF uniquement (volet financier)

---

## Avertissement de lecture

Ce document ne remet pas en cause les besoins exprimés. Il liste les **décisions manquantes** sans lesquelles plusieurs demandes ne peuvent pas être traduites en spécifications.

Une ligne de partage traverse tout le dossier et il faut l'énoncer d'emblée : **l'application lit aujourd'hui le cycle commercial et les factures, pas la comptabilité générale.** Nous savons donc suivre le client, la facture, l'encaissement, le fournisseur et la marge par affaire. Nous ne disposons ni de plan comptable, ni d'écritures comptables, ni de budget, ni de solde bancaire.

Conséquence directe sur les trois tableaux de bord demandés :

| Tableau de bord | Situation |
|---|---|
| **n°2 — Commercial** (DSO, DPO, mauvais clients) | Réalisable sur données réelles et fiables |
| **n°3 — Trésorerie prévisionnelle** | Réalisable en échéancier, pas en position de trésorerie |
| **n°1 — Budget** (performance, résultat net, marge brute, top 10 charges) | Largement bloqué en l'état — donnée source absente |

Trois natures de points se mêlent dans ce qui suit :

- des **définitions à trancher** (que veut dire « performance », « marge brute », « mauvais client », « atterrissage ») ;
- des **données absentes du système** qu'aucun développement ne peut inventer (budget voté, charges d'exploitation, solde bancaire, conditions de paiement fournisseurs) ;
- des **arbitrages de posture** (afficher un indicateur approché sous son vrai nom, ou attendre la donnée exacte).

Les blocs marqués ⚠️ signalent une contrainte technique à porter à la connaissance du DAF pendant l'échange — elle change souvent la réponse qu'il donnera.

---

## 1. Le budget voté

> **Point le plus bloquant du dossier.** Aucun budget n'existe aujourd'hui dans le système : ni ligne budgétaire, ni montant voté, ni exercice de référence. Tout indicateur de type « budget vs consommé » est donc impossible en l'état, quel que soit le développement réalisé.

### Questions

1. Le budget voté existe aujourd'hui sous quelle forme : un fichier Excel que vous tenez, un module budgétaire de l'ERP que nous ne lisons pas encore, une consolidation manuelle ?
2. Si c'est un fichier : qui le met à jour, à quelle fréquence, et acceptez-vous qu'il nous soit déposé périodiquement ?
3. Selon quelle maille est-il découpé : par ligne budgétaire, par compte comptable, par direction, par projet ? Cette réponse dessine littéralement l'écran des lignes les plus consommées.
4. Combien de lignes budgétaires comporte-t-il, en ordre de grandeur : une vingtaine, deux cents, deux mille ? L'ergonomie du tableau en dépend entièrement.
5. **Le rapprochement entre le budget et le réalisé, comment le faites-vous aujourd'hui ?** Pour affirmer qu'une ligne est consommée à 70 %, il faut une clé qui relie une dépense engagée à une ligne du budget : un code analytique, un centre de coût, une nomenclature commune. Existe-t-elle ?
6. Un budget révisé en cours d'exercice, cela arrive-t-il ? Si oui, l'écart doit-il se lire contre le budget initial ou contre la dernière révision ?
7. Le budget couvre-t-il les charges seules, ou aussi les produits (objectifs de recettes) ?

⚠️ **À signaler au DAF** : l'application comporte déjà un écran nommé « écart budgétaire ». Il ne compare pas un budget à un réalisé — il compare le chiffre d'affaires de l'année à celui de l'année précédente, client par client. Le libellé est trompeur et sera corrigé. Aucun budget n'y intervient.

⚠️ **Second point** : sans réponse à la question 5, le tableau de bord Budget ne peut pas exister, même si le budget nous est transmis. C'est la question à ne pas quitter la réunion sans avoir tranchée.

---

## 2. « Performance », indicateur global

### Questions

8. « Performance » désigne quoi, en une formule ? Un taux de réalisation du budget ? Un score composite ? Un chiffre d'affaires comparé à un objectif ? Une rentabilité ?
9. Cet indicateur doit-il se lire sur une seule valeur, ou se décomposer en plusieurs sous-indicateurs ?
10. Contre quoi se juge-t-il : un budget, l'exercice précédent, une cible, une norme du secteur ?
11. À quelle fréquence sa valeur doit-elle bouger : au jour, au mois, au trimestre ?

⚠️ **À signaler au DAF** : nous préférons ne pas inventer cette formule et vous la présenter ensuite comme la vôtre. Un indicateur global que le DAF ne reconnaît pas comme le sien ne sera jamais utilisé.

---

## 3. Résultat net et marge brute

> Ces deux indicateurs supposent une comptabilité générale que nous ne lisons pas. Il faut choisir une voie, pas contourner la contrainte.

### Questions

12. **Résultat net** — deux options, laquelle retenez-vous ?
    - vous nous ouvrez l'accès aux données comptables (écritures, plan de comptes, journaux) et nous le calculons ;
    - la comptabilité vous le fournit déjà calculé, vous nous le transmettez périodiquement et nous l'affichons tel quel avec sa date d'arrêté.
13. **Marge brute** — de quelle marge parlez-vous ? Nous savons calculer aujourd'hui une **marge d'affaires** : chiffre d'affaires du dossier moins dépenses du dossier, sur l'ensemble des affaires. Ce n'est pas une marge brute comptable (production vendue moins achats consommés). La marge d'affaires répond-elle à votre besoin, ou vous faut-il la marge comptable ?
14. **« Réalisée à date » : à date de quoi ?** À la facture émise, ou à l'encaissement reçu ? L'écart entre les deux est très important dans nos données, et un DAF orienté cash ne répond pas comme un DAF orienté résultat.
15. Si vous retenez la marge d'affaires : voulez-vous la lire au global, par client, par dossier, par activité ?
16. Faut-il distinguer la marge attendue (au devis), la marge provisoire et la marge définitive ? Nous disposons des trois.

⚠️ **À signaler au DAF** : afficher « Résultat net » sur une marge d'affaires serait un faux, et vous le verriez immédiatement. Nous proposons soit d'obtenir la donnée comptable, soit de nommer l'indicateur pour ce qu'il est.

---

## 4. Top 10 des plus grosses charges

> Indicateur signalé comme voté, donc attendu. Une ambiguïté doit être levée avant tout développement.

### Questions

17. « Charges » au sens comptable, ou « plus gros fournisseurs » ? Nous savons produire un **top 10 des fournisseurs par montant facturé** sur données réelles. Nous ne savons **pas** produire un top 10 de charges d'exploitation.
18. Les postes qui n'apparaîtront pas dans un classement fournisseurs — masse salariale, loyers, amortissements, impôts et taxes, frais financiers — font-ils partie de ce que vous voulez voir ? S'ils sont l'essentiel de votre besoin, le classement fournisseurs ne le couvre pas.
19. Le classement se lit-il sur les montants facturés, engagés (commandes passées) ou décaissés (réellement payés) ? Ce sont trois chiffres différents.
20. Sur quelle période : l'exercice en cours, les douze derniers mois glissants, le mois écoulé ?
21. Voulez-vous un classement figé au top 10, ou la possibilité de dérouler au-delà ?

---

## 5. Lignes budgétaires les plus consommées

> Le compte-rendu signale une précision coupée en bord de page, à reconfirmer. Cette rubrique dépend entièrement des réponses du bloc 1.

### Questions

22. Quelle était la précision manquante sur la note manuscrite ?
23. **« Le plus consommé » : en valeur absolue ou en taux de consommation ?** Une ligne à 95 % de son budget peut être plus alarmante qu'une ligne beaucoup plus grosse consommée à 20 %. Notre recommandation : afficher les deux, avec un tri par défaut sur le taux.
24. Faut-il une alerte au franchissement d'un seuil de consommation, et à quel niveau : 80 %, 90 %, 100 % ?
25. Un dépassement de ligne budgétaire doit-il remonter à quelqu'un d'autre que vous ?

---

## 6. Créances et DSO

> Bloc le plus solide du dossier : les données sont présentes, complètes et fiables. Les questions portent sur le calibrage, non sur la faisabilité.

### Questions

26. **Quelle est votre définition du DSO ?** Nous mesurons aujourd'hui un délai moyen de règlement réel, calculé sur les dates de paiement effectives. Ce n'est pas la formule « encours rapporté au chiffre d'affaires sur 365 jours ». Laquelle est votre référence — celle que vous communiquez au conseil ?
27. Un DSO global suffit-il, ou le voulez-vous segmenté : par client, par commercial, par pays, par activité ?
28. **Avez-vous une cible chiffrée ?** Sans elle, l'outil affiche un délai sans jugement : le lecteur ne sait pas si le chiffre est bon ou mauvais.
29. Le DSO doit-il se lire sur l'exercice, sur douze mois glissants, ou en tendance mois par mois ?
30. Faut-il exclure certains clients du calcul (administrations, groupe, litiges) ?

---

## 7. Dettes et DPO

### Questions

31. Même question que pour le DSO : quelle définition du DPO retenez-vous, et avez-vous une cible ?
32. Le DPO doit-il se lire au global, ou par fournisseur ?
33. Cherchez-vous à mesurer un délai de paiement, ou à détecter un risque de rupture fournisseur ?
34. Souhaitez-vous voir l'échéancier de vos dettes par tranches (à 30, 60, 90 jours et au-delà) ?

⚠️ **À signaler au DAF, sans attendre qu'il le découvre** : notre synchronisation ne remonte actuellement que les factures fournisseurs les plus **anciennes**, du fait d'une limite de volume mal orientée. Nos données fournisseurs s'arrêtent en mai 2025, alors que les factures clients vont jusqu'à juillet 2026. **Environ quatorze mois de dettes récentes manquent, dont la totalité de l'exercice en cours.** Un DPO publié aujourd'hui serait faux — et faux dans le sens rassurant. Le correctif est simple de notre côté.

**Question à trancher** : nous corrigeons puis nous livrons le DPO, ou nous le sortons de la première version le temps de fiabiliser ?

⚠️ **Second point** : les conditions de paiement négociées avec les fournisseurs ne sont renseignées pour **aucun** fournisseur dans l'ERP. Nous pouvons donc dire « nous payons à tant de jours », mais pas « nous payons avec tel écart par rapport au délai négocié ». Quelqu'un peut-il saisir ces conditions, ou renonçons-nous à cette comparaison ?

---

## 8. Suivi des mauvais clients

### Questions

35. **Donnez-nous votre règle : à partir de quel retard, et de quel montant, un client est-il « mauvais » ?**
36. Un client qui paie systématiquement avec quinze jours de retard sur trente factures est-il plus problématique que celui qui a une seule facture bloquée depuis cent vingt jours ? La réponse détermine si l'indicateur porte sur le retard moyen, le retard maximum, ou la régularité du comportement.
37. Faut-il distinguer un client qui paie tard d'un client qui **a cessé de payer** ? Nous savons détecter les deux.
38. **Qu'attendez-vous de cet écran : une liste ou une action ?** Un classement, ou une recommandation par client (relance, mise en demeure, blocage de livraison, étalement négocié) ?
39. Si recommandation : qui décide et qui exécute — vous, le commercial en charge, la direction générale ?
40. **Les factures en litige** ne sont pas des impayés. Cette information existe-t-elle quelque part, ou faut-il vous donner le moyen de marquer un litige dans l'outil ?
41. Même question pour les **clients stratégiques** qu'on ne bloque pas malgré le retard : faut-il un marquage ?
42. Le classement doit-il être visible par les commerciaux, ou rester dans votre périmètre ?

---

## 9. Trésorerie prévisionnelle

> Contrainte à poser franchement en ouverture de ce bloc : **nous n'avons aucun solde bancaire** et aucune charge récurrente (salaires, loyers, impôts, échéances d'emprunt). Nous pouvons produire un **échéancier des encaissements et décaissements attendus**. Nous ne pouvons pas produire une position de trésorerie prévisionnelle au sens strict.

### Questions

43. **L'échéancier vous suffit-il dans un premier temps**, ou une prévision sans solde de départ ni charges fixes est-elle inutilisable pour vous ?
44. Si vous voulez la position réelle : **d'où vient le solde d'ouverture ?** Relevé bancaire synchronisé, saisie manuelle mensuelle de votre part, rapprochement comptable ?
45. Et les charges fixes récurrentes : peuvent-elles être saisies une fois dans l'outil comme un échéancier récurrent, ou doivent-elles provenir d'une source existante ?
46. **Quelle maille calendaire ?** Le compte-rendu dit « mois par mois ». Une tension de trésorerie se joue souvent à la semaine, voire au jour pour les grosses échéances. Qu'est-ce qui vous est réellement utile ?
47. Sur quel horizon : trois mois, six mois, douze mois glissants ?
48. **« Prédiction des atterrissages » : prédiction ou projection ?** Deux niveaux très différents :
    - *projection* : nous retenons les échéances contractuelles telles quelles ;
    - *prédiction* : nous décalons chaque échéance selon le comportement de paiement réel du client (ce client paie toujours avec vingt jours de retard, nous projetons donc à vingt jours).
    Nous savons faire les deux, et nous avons l'historique nécessaire pour la seconde. Elle est nettement plus juste, mais elle produit un chiffre qui ne correspond à aucun document contractuel. Êtes-vous à l'aise avec cela ?
49. Voulez-vous voir plusieurs scénarios (prudent, réaliste, optimiste) ou une seule trajectoire ?
50. Les encaissements attendus doivent-ils inclure le carnet de commandes non encore facturé, ou seulement les factures émises ?

---

## 10. Alerte sur les créances proches de l'échéance

### Questions

51. **Quel préavis ?** Quinze jours avant échéance, sept jours, trois jours ?
52. L'alerte s'affiche dans l'application quand vous l'ouvrez, ou doit-elle vous être poussée par courriel ?
53. Qui la reçoit : vous seul, ou aussi le commercial en charge du compte ?
54. **Quel seuil de matérialité ?** Toutes les échéances, ou seulement au-delà d'un montant ? Sans seuil, l'alerte devient du bruit et cessera d'être lue.
55. Combien d'alertes par semaine avant que cela devienne ingérable ?
56. Une alerte doit-elle pouvoir être marquée comme traitée, pour ne pas réapparaître ?
57. Faut-il aussi une alerte symétrique sur les **dettes** proches de l'échéance, pour éviter un incident fournisseur ?

⚠️ **À signaler au DAF** : aucun canal de diffusion sortant n'existe aujourd'hui — ni courriel, ni notification mobile. Une alerte ne peut pour l'instant s'afficher que dans l'application. Ouvrir un canal externe est un chantier technique distinct.

---

## 11. Formation et qualité des données

### Questions

58. **De quel risque parlez-vous exactement** : une erreur de saisie dans l'ERP qui remonterait fausse dans les tableaux de bord, ou une mauvaise interprétation des indicateurs par les utilisateurs ? Ce ne sont pas les mêmes réponses — contrôles de cohérence dans un cas, pédagogie dans l'autre.
59. Qui utilisera le cockpit, et avec quel niveau de droits ? Qui peut voir la trésorerie, qui peut voir les marges, qui peut voir les impayés d'un client dont il n'est pas responsable ?
60. Combien de personnes sont à former, et sous quel format : session collective, tutoriels dans l'outil, guide écrit ?
61. Souhaitez-vous une trace de qui a consulté quoi ?

⚠️ **À signaler au DAF, car cela peut le rassurer et recentrer le sujet** : l'application est aujourd'hui en **lecture seule**. Personne n'y saisit de donnée financière ; tout provient de l'ERP. Une corruption des données depuis notre outil est donc structurellement impossible. Le véritable enjeu de qualité se situe en amont, dans la saisie ERP — hors du périmètre de l'application, mais bien réel.

---

## 12. Gouvernance des chiffres et périmètre

### Questions

62. **Nos indicateurs devront-ils coïncider avec ceux que vous communiquez au conseil et aux commissaires aux comptes ?** Si oui, il faut acter dès maintenant que l'outil ne remplace pas la comptabilité, et convenir d'une source de vérité par indicateur. Sinon nous créerons deux vérités concurrentes, et l'outil perdra cette bataille.
63. Le périmètre est-il une seule entité, ou plusieurs sociétés à consolider ?
64. L'exercice est-il civil, ou décalé ?
65. Tout est-il en francs CFA, ou faut-il gérer plusieurs devises et un taux de conversion ?
66. Quelle fraîcheur de données attendez-vous : temps réel, actualisation quotidienne le matin, hebdomadaire ?
67. Combien de temps consacrez-vous à la lecture d'un cockpit lors d'une session type ? Cela détermine la densité des écrans.
68. **Quelles sont les trois questions que vous vous posez chaque mois et auxquelles vous n'avez pas de réponse aujourd'hui ?**

---

## 13. Points à signaler de nous-mêmes

Deux constats issus de l'analyse des données, à porter à sa connaissance sans attendre qu'il les découvre.

### Questions

69. **La totalité des dossiers est enregistrée au statut « brouillon » dans l'ERP** — aucun n'est marqué comme confirmé ou clôturé. Est-ce le fonctionnement normal chez vous, ou un défaut de paramétrage ? Le point est important : tout indicateur qui filtrerait sur les dossiers confirmés afficherait zéro sans le signaler.
70. Un écran de synthèse affiche aujourd'hui une « position nette de trésorerie ». Il s'agit en réalité d'un écart entre les créances à encaisser et les dettes à payer — sans solde bancaire, sans échéancier, sans charges de structure. Le libellé sera corrigé. Confirmez-vous que cet écart créances/dettes garde une utilité pour vous sous son vrai nom ?

---

## Les trois questions prioritaires

Si l'échange doit être court, ces trois questions débloquent le plus grand nombre de sujets.

| # | Question | Ce qu'elle débloque |
|---|---|---|
| 1 | Le budget voté existe sous quelle forme, et **par quelle clé le rapprochez-vous du réalisé** ? | Sans réponse, le tableau de bord Budget ne peut pas exister — ni la performance, ni les lignes les plus consommées |
| 2 | « Marge brute réalisée à date » : marge comptable ou marge d'affaires, et à date de facture ou d'encaissement ? | Détermine si l'indicateur central du cockpit est livrable immédiatement ou dépend d'un accès comptable |
| 3 | Votre règle exacte du « mauvais client » : combien de jours, quel montant, retard moyen ou maximum ? | Débloque à lui seul le tableau de bord Commercial, qui est la partie livrable la plus rapidement |

---

## Récapitulatif des contraintes à porter à la connaissance du DAF

| Besoin exprimé | Contrainte |
|---|---|
| Budget vs consommé, lignes les plus consommées | Aucun budget n'existe dans le système — donnée à créer, et clé de rapprochement à définir |
| Résultat net | Suppose la comptabilité générale, non lue aujourd'hui — à ouvrir, ou à recevoir déjà calculé |
| Marge brute comptable | Seule une marge d'affaires (chiffre d'affaires moins dépenses par dossier) est calculable |
| Top 10 des charges | Réalisable sur les fournisseurs ; masse salariale, loyers, amortissements et impôts sont absents |
| DPO et dettes fournisseurs | Environ quatorze mois de factures récentes manquent — correctif simple, mais à faire avant publication |
| Délai fournisseur vs négocié | Conditions de paiement renseignées pour aucun fournisseur — saisie amont à organiser |
| Trésorerie prévisionnelle | Aucun solde bancaire ni charge récurrente — échéancier possible, position nette non |
| Alerte avant échéance | Aucun canal sortant (courriel, mobile) — infrastructure à créer |
| Statut des dossiers | Tous en « brouillon » — tout filtre sur dossier confirmé renverrait zéro silencieusement |
| Formation à la qualité des données | L'application est en lecture seule : l'enjeu réel se situe dans la saisie ERP, en amont |

---

## Points d'incohérence relevés dans le compte-rendu

À faire confirmer par le DAF lors de l'échange :

1. **§1** mentionne une précision « coupée en bord de page » sur les lignes budgétaires les plus consommées — à reconfirmer.
2. **§1** demande à la fois « résultat net » et « marge brute réalisée » : le premier suppose la comptabilité générale, le second peut se lire sur les affaires. Sont-ils attendus au même niveau d'exigence, ou l'un est-il un substitut de l'autre ?
3. Le compte-rendu acte que **l'excédent brut d'exploitation et les charges financières sont écartés** des priorités. À confirmer : est-ce un abandon définitif ou un report ?
4. Le **top 10 des charges** est marqué comme voté, alors que la donnée sous-jacente (charges d'exploitation) est absente du système. Le vote portait-il sur le principe, ou sur une définition précise déjà arrêtée ?
5. « Prédiction des atterrissages » et « prévision des encaissements et décaissements » désignent-ils le même écran, ou deux vues distinctes ?

---

## Proposition de conduite de l'échange

Ordre recommandé, pour installer la crédibilité avant d'aborder le point dur :

1. **Ouvrir sur le tableau de bord Commercial** (blocs 6 à 8) — c'est là que la donnée est la plus fiable et la livraison la plus rapide.
2. **Enchaîner sur la trésorerie** (blocs 9 et 10), en posant d'emblée la limite du solde bancaire.
3. **Aborder ensuite le budget** (blocs 1 à 5) en énonçant clairement qu'il s'agit d'un chantier distinct, dépendant d'une donnée que le DAF détient et que nous n'avons pas.
4. **Terminer par la gouvernance** (bloc 12), notamment la question 62 sur la cohérence avec les chiffres communiqués au conseil.

Ne pas clore la réunion sans la réponse à la **question 5** (clé de rapprochement budget/réalisé) ni au **bloc 7** (arbitrage sur le DPO).

---

*Document de travail établi à partir du compte-rendu du 04/08/2026 et de l'analyse des données disponibles dans l'application.*
