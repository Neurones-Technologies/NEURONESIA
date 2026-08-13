# 20 questions — Directeur Administratif et Financier

**Objet** : améliorer le cockpit DAF à partir de son usage réel
**Format** : entretien de 45 à 60 minutes, une question par point, réponse courte attendue
**État de départ** : 5 sections livrées — Encours et marge, Budget, Relation commerciale, Trésorerie prévisionnelle, Formation et qualité

---

## Comment lire ce document

Les questions de cadrage servaient à définir quoi construire. Celles-ci servent à **corriger ce qui est construit**. Elles supposent que le DAF a ouvert l'outil : plusieurs n'ont pas de réponse utile dans le vide.

Quatre questions portent un ⚠️ : la réponse engage un raccordement de données, pas un réglage d'écran. Ce sont elles qui déterminent si les écrans concernés sortent de la démonstration.

---

## A. Usage réel (1 à 4)

**1.** Depuis la mise à disposition, à quelle fréquence ouvrez-vous le cockpit — chaque matin, avant le comité, une fois par mois à la clôture ?

**2.** Sur les 5 onglets, lesquels ouvrez-vous vraiment ? Ceux que vous n'ouvrez jamais sont candidats à la suppression.

**3.** Quel chiffre allez-vous chercher en premier quand vous ouvrez ? Ce sera le haut de l'écran d'accueil.

**4.** Qu'avez-vous décidé ou déclenché à cause d'un chiffre du cockpit — une relance, un blocage de livraison, un arbitrage de paiement ? Un exemple concret ; s'il n'y en a aucun, c'est l'information la plus utile de l'entretien.

---

## B. Budget — sortir de la démonstration (5 à 8)

L'onglet Budget fonctionne aujourd'hui en régime mixte : les **montants votés sont posés** par nous, la **consommation est mesurée** sur les achats réels, rattachée aux lignes par des motifs sur le nom du fournisseur.

⚠️ **5.** Votre budget 2026 voté, sous quelle forme existe-t-il, et pouvez-vous nous le transmettre ce mois-ci ? Tant qu'il n'arrive pas, l'écran montre une forme, pas votre budget.

**6.** La nomenclature que nous avons posée — Matériel et infrastructure, Licences éditeurs, Prestations et sous-traitance, Logistique et douane, Télécoms — correspond-elle à votre découpage réel, ou raisonnez-vous sur d'autres lignes ?

⚠️ **7.** Le rattachement d'un achat à une ligne budgétaire se fait aujourd'hui **sur le nom du fournisseur**, faute de code analytique dans l'ERP. Une ligne « Non rattaché » recueille le reste. Deux options : quelqu'un saisit un code analytique à la commande dans l'ERP, ou nous continuons à affiner les motifs avec vous. Laquelle retenez-vous ?

**8.** Sur les lignes budgétaires : le tri par défaut doit-il être le taux de consommation ou le montant absolu ? Et à quel seuil de consommation voulez-vous une alerte — 80 %, 90 %, 100 % ?

---

## C. Ce qui est projeté et non mesuré (9 à 12)

**9.** Le **résultat net** affiché est une projection : marge d'affaires mesurée, moins des charges de structure que nous avons posées, moins un impôt à 25 %. Lisez-vous ce chiffre, ou le mot « projection » vous fait-il passer l'écran ?

**10.** Le plan de charges mensuel que nous avons posé — masse salariale, loyers, amortissements, honoraires, impôts — est-il dans le bon ordre de grandeur, ou l'écart est-il tel que la projection est inutilisable ?

⚠️ **11.** Pour que le résultat net cesse d'être une projection, il faut une des deux voies : accès aux écritures comptables, ou transmission périodique du résultat déjà calculé par la comptabilité avec sa date d'arrêté. Laquelle ouvrez-vous, et dans quel délai ?

**12.** Sur la marge : nous servons une marge d'affaires (chiffre d'affaires du dossier moins dépenses du dossier). Après usage, répond-elle à votre besoin, ou l'absence de marge brute comptable reste-t-elle bloquante ?

---

## D. Relation commerciale — le bloc le plus solide (13 à 16)

**13.** Nous affichons **deux DSO** côte à côte : le délai d'encaissement constaté sur les factures réglées, et l'encours rapporté au chiffre d'affaires. Lequel est celui que vous communiquez au conseil ? L'autre doit-il rester visible ou disparaître ?

**14.** Avez-vous maintenant une **cible chiffrée** de DSO ? Sans elle l'outil affiche un délai sans jugement, et le lecteur ne sait pas si le chiffre est bon.

⚠️ **15.** Le **DPO n'est pas calculable** : aucune facture fournisseur n'est synchronisée dans le système — la table est vide, ce n'est pas une question de volume. Ce qui est affiché à la place, ce sont les achats **engagés**, nommés comme tels. Deux questions : la synchronisation des factures fournisseurs peut-elle être ouverte côté ERP, et en attendant, retirons-nous le bloc ou le laissons-nous sous son vrai nom ?

**16.** Le classement des mauvais payeurs croise le comportement passé (retard moyen) et l'exposition présente (retard courant). Après lecture : le classement désigne-t-il les bons clients, ou voyez-vous des absents et des faux positifs ? Nommez-en un de chaque.

---

## E. Trésorerie et marquages manquants (17 à 18)

**17.** Le calendrier affiche une **variation** de trésorerie, pas une position — aucun solde bancaire n'existe dans le système. Un cumul négatif veut dire « ce mois consomme plus qu'il n'apporte », pas « à découvert ». Cette lecture vous suffit-elle, ou faut-il organiser une saisie mensuelle du solde d'ouverture de votre part ?

**18.** Deux marquages manquent et faussent la lecture du recouvrement : les **factures en litige**, comptées aujourd'hui comme des impayés, et les **clients stratégiques** qu'on ne bloque pas malgré le retard. Voulez-vous pouvoir les marquer dans l'outil — ce qui suppose d'y ouvrir une saisie, alors qu'il est aujourd'hui en lecture seule ?

---

## F. Alertes et gouvernance (19 à 20)

**19.** Les alertes avant échéance ne s'affichent que dans l'application, à l'ouverture. Quel préavis vous est utile — quinze, sept, trois jours — et à partir de quel montant, pour que l'alerte ne devienne pas du bruit ?

**20.** Les chiffres du cockpit doivent-ils désormais **coïncider avec ceux que vous communiquez au conseil** ? Si oui, il faut acter une source de vérité par indicateur, sans quoi deux vérités concurrentes s'installent — et l'outil perdra cette bataille.

---

## Les trois à ne pas manquer

| # | Question | Ce qu'elle débloque |
|---|---|---|
| 5 + 7 | Le budget voté, et par quelle clé on rattache le réalisé | Sort l'onglet Budget de la démonstration — sans les deux, il y reste |
| 15 | Les factures fournisseurs peuvent-elles être synchronisées ? | Débloque le DPO et l'échéancier de décaissement, donc la moitié de la trésorerie |
| 4 | Qu'avez-vous décidé à cause d'un chiffre du cockpit ? | Dit si l'outil est entré dans la décision ou reste un écran regardé |

---

*Document de travail — suite des questions de cadrage du 04/08/2026, à poser après une période d'usage.*
