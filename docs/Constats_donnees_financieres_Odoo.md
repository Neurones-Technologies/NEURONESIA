# Constats sur les données financières — audit Odoo

**Objet** : établir les chiffres réellement disponibles et fiables avant construction du cockpit DAF
**Date de l'audit** : 04/08/2026
**Source** : serveur Odoo de production, consultation en lecture seule
**Destinataires** : Direction Administrative et Financière, Comptabilité

---

## Avertissement de lecture

Cet audit a été mené en **lecture seule** : aucune donnée n'a été modifiée. Toutes les valeurs
ci-dessous sont des comptages et agrégats réels relevés dans Odoo, non des estimations.

Il en ressort une conclusion qui doit précéder toute discussion sur les tableaux de bord :
**les données financières d'Odoo sont bien plus riches que ce que l'application exploite
aujourd'hui, mais quatre défauts de qualité rendent plusieurs indicateurs inexploitables en
l'état.** Aucun de ces défauts ne relève du développement de l'application ; tous se situent
en amont, dans l'alimentation ou le paramétrage d'Odoo.

Les points marqués 🔴 exigent un arbitrage de la DAF ou de la Comptabilité avant que
l'indicateur concerné puisse être publié.

---

## 1. Ce qui existe dans Odoo — et que l'application n'exploite pas

L'application ne lit aujourd'hui que le cycle commercial (devis, commandes, factures).
L'audit établit que la comptabilité générale est intégralement disponible :

| Donnée | Volume relevé | Exploitée aujourd'hui |
|---|---|---|
| Plan comptable | 879 comptes (SYSCOHADA, classes 1 à 8) | Non |
| Écritures comptables | 139 125 lignes | Non |
| Journaux comptables | 46, dont 24 de banque et caisse | Non |
| Relevés bancaires | 1 130 | Non |
| Lignes analytiques | 27 248, sur 4 plans | Non |
| Budgets | 34, dont 4 pour l'exercice 2026 | Non |
| Factures fournisseurs | 5 683 | Partiellement (5 000) |
| Factures clients | 2 926 | Oui |

**Conséquence sur le cahier des charges du DAF** : les trois tableaux de bord demandés sont
techniquement réalisables, y compris le tableau Budget que nous pensions bloqué. Le sujet
n'est pas la disponibilité de la donnée, mais sa qualité.

---

## 2. Le budget existe — mais n'a jamais été rapproché du réalisé

### Ce qui existe

Quatre budgets sont saisis pour l'exercice 2026, avec un responsable identifié :

| Budget 2026 | Montant |
|---|---|
| Direction Commerciale | 7 834 M FCFA |
| Frais Généraux | 795 M FCFA |
| Direction des Opérations | 423 M FCFA |
| Direction Administrative et Financière | 72 M FCFA |
| **Total** | **9 124 M FCFA** |

La maille budgétaire correspond exactement au besoin exprimé : un plan analytique dédié de
**47 lignes**, codifiées par direction (`CDV-DAF-001`, `CDF-DiC-003`…), avec les intitulés
attendus — Charges du personnel, Impôts et taxes, Services extérieurs, Amortissements et
provisions, Frais financiers, Achats de marchandises, Frais de mission, Formations.

**La demande « lignes budgétaires les plus consommées » ne nécessite donc aucune création de
référentiel.** Il existe et il est structuré.

### 🔴 Le problème

| Exercice | Lignes | Budget saisi | Réalisé rapproché |
|---|---|---|---|
| 2023 | 221 | 3 690 M | **0** |
| 2024 | 194 | 4 753 M | **0** |
| 2025 | 64 | 1 584 M | **0** |
| 2026 | 45 | 9 124 M | **0** |

Le réalisé n'a **jamais** été rapproché du budget, sur aucun des quatre derniers exercices.
Les 34 budgets sont également tous restés au statut **brouillon**, jamais validés — ce qui
explique vraisemblablement l'absence de suivi automatique.

Le réalisé est pourtant calculable : la table de restitution budgétaire d'Odoo l'établit à
**3 497 M réalisés et 1 991 M engagés sur 2026**. La donnée est donc atteignable, par un
autre chemin que celui de l'interface budgétaire.

**Questions à trancher**
1. Les budgets 2026 sont en brouillon : oubli de validation, ou report volontaire ?
2. Comment le suivi de consommation est-il assuré aujourd'hui — hors Odoo, sur tableur ?
3. Le total de 9 124 M correspond-il bien au budget voté ?
4. Les 7 834 M de la Direction Commerciale relèvent-ils d'achats de marchandises (coût de
   revient) plutôt que de charges de structure ? Le rapprochement avec les autres directions
   suggère un périmètre différent.

---

## 3. Le DSO — indicateur fiable et exploitable

C'est le résultat le plus solide de l'audit. Calculé sur le lettrage comptable réel
(2 106 créances soldées, 35 085 M FCFA encaissés) :

### Le chiffre

| Méthode | Résultat |
|---|---|
| **Délai réel de règlement, pondéré par les montants** | **63,2 jours** |
| Délai réel, moyenne simple | 69,3 jours |
| Médiane | 47,0 jours |
| Ratio encours/chiffre d'affaires, exercice 2025 | 64,7 jours |

Les deux méthodes convergent sur l'exercice 2025 (63,2 j et 64,7 j) : **le chiffre est robuste**.

Dispersion : P25 = 23 j, P75 = 86 j, P90 = 155 j.

⚠️ **Le ratio encours/CA appliqué à 2026 donne 257,5 jours.** C'est un artefact : l'exercice
n'est facturé que sur six mois, ce qui gonfle mécaniquement le ratio. Sur un exercice en cours,
seul le délai réel a du sens. Un cockpit doit s'interdire d'afficher ce ratio sur l'année courante.

### La tendance est favorable

| Exercice | DSO pondéré |
|---|---|
| 2021 | 72,3 j |
| 2022 | 74,5 j |
| 2023 | 67,1 j |
| 2024 | 71,5 j |
| **2025** | **56,9 j** |

L'exercice 2025 marque une amélioration de 15 jours sur 2024. C'est un indicateur de
performance défendable devant un conseil.

*(La valeur de 9,6 j sur 2026 n'est pas une performance : seules les factures récentes déjà
réglées entrent dans le calcul — biais de sélection.)*

### La dérive contre le délai contractuel

Le délai accordé est de **19 jours en moyenne** (médiane 30 j). Nous encaissons donc à 63 jours
ce qui est contractuellement dû à 19 jours, soit **44 jours de dérive**.

| | |
|---|---|
| Factures payées en retard | **81,4 %** |
| Factures payées à l'heure ou avant | 18,6 % |
| Retard moyen pondéré | **39 jours après échéance** |
| Retard médian | 28 jours |
| Volume à plus de 90 jours de retard | 16,7 % |

### 🔴 Une anomalie de saisie à confirmer

**1 268 factures sur 2 925 portent un délai accordé de 0 jour** (échéance identique à la date
de facture), contre 1 270 à 30 jours.

Deux lectures : soit la moitié du portefeuille est réellement facturée payable comptant, soit
le champ échéance n'est pas renseigné et Odoo recopie la date de facture. Dans le second cas,
tout calcul de retard sur cette moitié du portefeuille est faussé.

---

## 4. Les encours — 🔴 chiffres non publiables en l'état

### Le constat brut

| | Client | Fournisseur |
|---|---|---|
| Factures totales | 2 926 | 5 683 |
| Factures ouvertes | 850 | 4 139 |
| Encours calculé sur les factures | 6 687 M | 9 497 M |
| **Solde du compte de tiers en comptabilité** | **4 365 M** | **1 414 M** |
| **Écart** | **2 322 M** | **8 083 M** |

Les deux valeurs devraient être identiques. Elles ne le sont pas.

### L'explication établie

L'audit écarte l'hypothèse d'un lettrage erroné sur les factures : sur 2 002 lignes de dette
fournisseur examinées, **aucune** n'est marquée comme lettrée. Les factures affichées impayées
le sont bien au niveau de la facture.

La cause est ailleurs, et elle est massive :

| Rapprochement des règlements | Rapprochés | Non rapprochés |
|---|---|---|
| Encaissements clients | 1 998 (35 072 M) | **2 924 (41 114 M)** |
| Décaissements fournisseurs | 1 810 (5 958 M) | **25 944 (70 499 M)** |

**Près de 26 000 décaissements fournisseurs, pour 70 499 M FCFA, ne sont rattachés à aucune
facture.** Les paiements sont enregistrés en banque et en comptabilité, mais le lien avec les
factures qu'ils soldent n'est pas établi.

Conséquence : **c'est la balance comptable qui est juste, et l'encours facture par facture qui
est faux.** L'encours fournisseur réel est de **1 414 M**, non de 9 497 M.

### Deux indices corroborants

- **57,7 % de l'encours fournisseur affiché a plus de deux ans d'échéance** (5 479 M), et
  95,9 % est échu à plus de 90 jours. Une dette réelle de cette ancienneté aurait produit des
  contentieux.
- **Aucune dette fournisseur à échoir**, et rien sur les tranches 0 à 60 jours. Une entreprise
  en activité a nécessairement des factures fournisseurs courantes ; leur absence signale un
  défaut d'alimentation, pas une réalité économique.

### La position nette change de signe

| Base de calcul | Créances | Dettes | Position nette |
|---|---|---|---|
| Somme des factures ouvertes | 6 687 M | 9 497 M | **−2 810 M** |
| **Balance comptable** | **4 365 M** | **1 414 M** | **+2 951 M** |

Avec 826 M FCFA de trésorerie disponible, les deux lectures décrivent des situations opposées.
**C'est l'écart entre une alerte de solvabilité et une situation saine.** Aucun de ces deux
chiffres ne doit être affiché avant arbitrage.

### Question à la Comptabilité

> Le compte fournisseur présente un solde de 1 414 M FCFA au bilan, alors que la somme des
> factures ouvertes atteint 9 497 M. L'écart de 8 083 M correspond-il aux 25 944 décaissements
> non rapprochés relevés dans Odoo ? Un apurement ou une campagne de lettrage est-il envisagé ?

### Ce qui reste exploitable malgré tout

La **concentration** n'est pas affectée par ce défaut :

| Concentration | Top 10 |
|---|---|
| Débiteurs (clients) | 44,8 % de l'encours |
| Créanciers (fournisseurs) | **61,6 %** de l'encours |

- **Clients** : Orange Côte d'Ivoire (650 M), MTN CI (418 M), BICICI (367 M) — concentration modérée.
- **Fournisseurs** : AITEK CI (1 064 M sur 124 factures), KANANYO (950 M sur 4 factures),
  HILANE TRANSIT (944 M sur 167 factures) — concentration forte.

L'**ancienneté côté client** est économiquement plausible et dégressive (2 642 M sur 2026,
1 357 M sur 2025, puis décroissant), ce qui conforte l'idée d'un encours client d'exploitation
réel. Le profil fournisseur, avec son pic sur 2022-2023, ne l'est pas.

**Point à traiter** : le 4ᵉ débiteur est **NEURONES TECHNOLOGIES BF, 320 M sur 34 factures** —
de l'intragroupe. À isoler de tout indicateur d'encours client et de DSO : la nature du risque
n'est pas comparable à une créance externe.

---

## 5. Les mauvais payeurs — un effet de segment, pas de client

Le classement par DSO client (minimum 3 factures réglées) fait apparaître une structure très
nette : **le secteur public et parapublic domine.**

| Client | DSO | Retard moyen | Volume |
|---|---|---|---|
| PORT AUTONOME D'ABIDJAN | 217 j | 158 j | 520 M |
| UNITÉ DE COORDINATION PROJET C2D-JUST | 143 j | 83 j | 451 M |
| BCEAO | 242 j | 145 j | 235 M |
| CEPICI | 152 j | 191 j | 207 M |
| BHCI | 183 j | 99 j | 118 M |

À l'opposé, les banques privées règlent rapidement :

| Client | DSO | Retard moyen | Volume |
|---|---|---|---|
| BICICI | 15 j | +10 j | 1 208 M |
| MANSA BANK | 17 j | +34 j | 201 M |
| VERSUS BANK | 18 j | −4 j | 46 M |

**Implication pour le cockpit** : un classement des mauvais payeurs qui ne distingue pas le
segment public du segment privé produira une liste que la DAF connaît déjà. La valeur ajoutée
réside dans la comparaison au comportement normal du segment, non dans le classement brut.

À noter également : les **plus gros débiteurs en montant** (Orange, MTN, BICICI) ne sont **pas**
les plus lents. Ce sont deux indicateurs distincts, à ne pas présenter sur le même axe.

---

## 6. Comptabilité générale — disponible, mais exercice 2026 incomplet

### Ce qui devient calculable

Contrairement à ce que le périmètre actuel de l'application laissait supposer :

| Indicateur | Statut | Valeur relevée (2026) |
|---|---|---|
| Charges d'exploitation (classe 6) | Calculable | 57,5 M |
| Produits (classe 7) | Calculable | 2 330,2 M |
| Résultat | Calculable | 2 272,6 M |
| Top 10 des charges par compte | Calculable | voir ci-dessous |
| Solde de trésorerie | Disponible | 825,9 M sur 24 comptes |

Top 10 des charges 2026 relevé : honoraires d'assistance technique (27,0 M), intérêts de
financement projet (11,8 M), intérêts autres financements (6,4 M), autres frais bancaires
(6,3 M), impôts fonciers et taxes annexes (4,1 M), intérêts sur loyers de location-acquisition
(1,4 M), primes d'assurance (0,6 M).

**La demande « top 10 des plus grosses charges » est donc réalisable au sens comptable strict**,
et non pas seulement comme un classement de fournisseurs.

### 🔴 La réserve

**57,5 M de charges pour 2 330 M de produits est structurellement invraisemblable.** L'exercice
2026 ne comporte que 212 lignes d'écriture sur les comptes de charges. Le résultat de 2 272,6 M
est donc un artefact d'exercice incomplet, non une performance.

**Question** : quelle est la date du dernier arrêté comptable fiable ?

### Détail de la trésorerie

825,9 M FCFA répartis sur 24 comptes, dont : caution et chèques certifiés (462,6 M),
Ecobank (395,3 M), Versus (305,5 M), BNI (79,1 M), SGBCI (53,9 M). Deux postes négatifs
significatifs : virements de fonds (−573,2 M) et BDA (−7,0 M).

---

## 7. Troncature de la synchronisation — défaut applicatif

Contrairement aux quatre points précédents, celui-ci relève de notre application et non d'Odoo.

La synchronisation des factures fournisseurs est plafonnée à 5 000 enregistrements, triés par
échéance **croissante** : nous conservons donc les plus **anciennes**.

| | |
|---|---|
| Factures fournisseurs dans Odoo | 5 683 |
| Plafond de synchronisation | 5 000 |
| **Factures ignorées** | **683** |
| Fenêtre réellement synchronisée | 14/08/2016 → **12/05/2025** |
| Montant ignoré | 2 953 M facturés, dont **2 594 M de reste dû** |

Les factures clients, elles, sont complètes (2 926 dans Odoo, 2 926 dans l'application) et
couvrent jusqu'au 06/07/2026.

**Correctif** : inverser le tri et lever le plafond. Modification simple, à réaliser avant toute
publication d'un indicateur fournisseur.

---

## 8. Synthèse — ce qui est publiable, et à quelles conditions

### Publiable immédiatement

| Indicateur | Valeur | Réserve |
|---|---|---|
| DSO réel | 63,2 j | aucune |
| Évolution du DSO 2021→2025 | 72,3 → 56,9 j | aucune |
| Retard moyen contre échéance | 39 j | sous réserve du point 3 (délais à 0 j) |
| Part des factures payées en retard | 81,4 % | idem |
| Classement DSO par client | voir §5 | à segmenter public/privé |
| Concentration des débiteurs et créanciers | 44,8 % / 61,6 % | aucune |
| Solde de trésorerie | 825,9 M | aucune |

### Publiable après correctif applicatif

| Indicateur | Correctif requis |
|---|---|
| DPO, encours fournisseur, échéancier fournisseur | Lever la troncature (§7) |
| Charges, résultat, budget, trésorerie | Ouvrir le périmètre comptable dans l'application |

### 🔴 Non publiable avant arbitrage

| Indicateur | Arbitrage requis |
|---|---|
| Encours fournisseur | 25 944 décaissements non rapprochés (§4) |
| Position nette créances/dettes | même cause — le signe du résultat en dépend |
| Budget vs consommé, lignes les plus consommées | réalisé jamais rapproché, budgets en brouillon (§2) |
| Résultat net, charges d'exploitation | exercice 2026 incomplet (§6) |
| Retard de paiement sur la moitié du portefeuille client | délais accordés à 0 jour (§3) |

---

## 9. Les quatre décisions à prendre

| # | Décision | Interlocuteur | Ce qu'elle débloque |
|---|---|---|---|
| 1 | Statuer sur les 25 944 décaissements non rapprochés | Comptabilité | Encours fournisseur, DPO, position nette, plan de trésorerie |
| 2 | Valider les budgets 2026 et organiser le rapprochement du réalisé | DAF | Tout le tableau de bord Budget |
| 3 | Ouvrir le périmètre comptable à l'application | DAF | Résultat, charges réelles, trésorerie, budget |
| 4 | Confirmer les délais de paiement à 0 jour | DAF / Administration des ventes | Fiabilité du calcul de retard sur la moitié du portefeuille |

---

## 10. Observation d'ensemble

Quatre audits successifs ont mis au jour quatre défauts de qualité de données indépendants :
troncature de synchronisation, budget jamais rapproché, règlements non lettrés, délais de
paiement non renseignés. Aucun ne relève de la conception des tableaux de bord.

**Le facteur limitant du projet n'est pas la capacité à construire des indicateurs, mais la
qualité du référentiel qui les alimente.** À ce titre, le point 4 du cahier des charges de la
DAF — la formation des utilisateurs à la qualité des données — apparaît comme le plus
structurant des quatre demandes, et non comme un volet accessoire.

Un tableau de bord construit sur ces données sans correction préalable produirait des chiffres
faux avec l'autorité de l'automatisation. Le risque n'est pas l'absence d'indicateur : c'est
l'indicateur crédible et erroné.

---

*Audit réalisé en lecture seule sur le serveur Odoo de production. Aucune donnée n'a été
modifiée. Les valeurs sont datées du 04/08/2026 et évolueront avec les saisies.*
