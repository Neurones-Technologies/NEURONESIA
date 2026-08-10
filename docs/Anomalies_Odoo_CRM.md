# Anomalies et blocages — Odoo CRM & Facturation

> **Périmètre** — deux sources distinctes, extraites de `erpntci.neuronestech.com` / base `test`
> le **2026-08-04** :
>
> | Source | Volume | Montant | Nature |
> |---|---|---|---|
> | `crm.lead` (opportunités) | 7 715 | 231,26 Md XOF | CA **espéré** (prévisionnel) |
> | `account.move` (factures postées) | 2 926 fact. + 157 avoirs | **41,75 Md XOF net** | CA **réellement facturé** |
> | `sale.order` (commandes) | 11 777 | — | Inexploitable en l'état (voir A13) |
>
> ⚠️ Les deux premiers montants **ne sont pas comparables** : le premier est un pipeline espéré,
> le second un chiffre d'affaires réalisé.
>
> ⚠️ **Aucune écriture n'a été faite dans Odoo.** Toutes les analyses, déduplications et
> reclassements décrits ici sont réalisés **en mémoire**, sur une copie extraite en lecture seule.
> La base est strictement intacte.

---

## 1. Synthèse — vue globale

### Périmètre CRM (`crm.lead`)

| ID | Anomalie | Gravité | Volume | CA concerné | Effet sur le reporting |
|----|----------|:-------:|--------|-------------|------------------------|
| **A1** | `create_date` écrasée par la migration | 🔴 Bloquant | 4 927 opp. (64 %) | — | Aucune tendance possible sur la date de création |
| **A2** | `x_domaine` non renseigné avant 2022 | 🔴 Bloquant | 2 876 opp. (37 %) | 72,34 Md | Analyse par catégorie impossible avant 2022 |
| **A3** | Deux référentiels de stages superposés | 🔴 Bloquant | 7 715 opp. | 231,26 Md | Taux de gain faux (100 % apparent sur 2018-2021) |
| **A4** | Opportunités périmées jamais clôturées | 🟠 Majeur | 2 274 opp. | 73,34 Md | Pipeline surévalué d'un facteur ~2 |
| **A5** | Doublons de saisie | 🟠 Majeur | 86 groupes / 93 lignes | 2,56 Md | CA réalisé et pipeline gonflés |
| **A6** | `x_domaine` / `x_nature` en texte libre | 🟠 Majeur | 18 valeurs déviantes | — | Agrégations éclatées, doublons de catégories |
| **A7** | `x_nature` vide à 47 % | 🟠 Majeur | 3 642 opp. | — | Part de revenu récurrent non mesurable |
| **A8** | Remplissage très inégal selon les équipes | 🟠 Majeur | Sales CIV 43 %, Sales BF 0 % | 103,7 Md | Comparaison inter-équipes faussée |
| **A9** | Stages en doublon FR/EN | 🟡 Mineur | 79 opp. sur 3 paires | 102,92 Md répartis sur 2 libellés | Reporting Odoo natif éclaté |
| **A10** | Probabilité incohérente avec le stage | 🟡 Mineur | 25 opp. ouvertes | 0,18 Md | Pipeline pondéré biaisé |
| **A11** | Opportunités sans échéance | 🟡 Mineur | 447 opp. | 8,05 Md | Exclues de tout axe temporel |
| **A12** | Champs de pilotage peu alimentés | 🟡 Mineur | `x_mb` 70 % vide, `x_focus` 90 % vide | — | Marge et priorisation non exploitables |

### Périmètre Facturation (`account.move`, `sale.order`)

| ID | Anomalie | Gravité | Volume | CA concerné | Effet sur le reporting |
|----|----------|:-------:|--------|-------------|------------------------|
| **A13** | Commandes fantômes à 4 115 **milliards** | 🔴 Bloquant | 2 commandes | 8 231 Md fictifs | `sale.order` inutilisable pour tout indicateur |
| **A14** | Taux d'avoir en dérive : 1 % → 28 % | 🔴 Bloquant | 157 avoirs | −5,34 Md | CA mensuel et classements commerciaux faussés |
| **A15** | Comptes techniques en tête des ventes | 🟠 Majeur | 423 factures | 11,95 Md (28,6 %) | Près d'un tiers du CA non attribuable |
| **A16** | Groupe Orange éclaté en 10 tiers | 🟠 Majeur | 10 comptes | 10,22 Md (24,5 %) | Premier client invisible dans les classements |
| **A17** | Commercial à CA net négatif | 🟡 Mineur | 1 utilisateur | −0,42 Md | Rôle ADV comptabilisé comme vente |
| **A18** | Lien opportunité ↔ facture quasi absent | 🟡 Mineur | 46 / 7 715 opp. | — | Taux de transformation réel non calculable |

**Cinq blocages** au total empêchent toute analyse fiable — trois côté CRM (séquelles de migration),
deux côté facturation. **Sept points majeurs** dégradent la sincérité des chiffres publiés.

---

## 2. Blocages structurels

### A1 — `create_date` écrasée par la migration 🔴

**Constat.** 4 927 opportunités portent la date de création `2026-04-07`. La répartition dans le
temps est absurde :

| Année de `create_date` | Nb |
|---|---|
| 2018 | 905 |
| 2019 | 1 231 |
| 2020 | 110 |
| 2021 | 516 |
| 2022 | 2 |
| 2023 | 4 |
| 2024 – 2025 | **0** |
| 2026 | 4 947 *(dont 4 927 le seul 07/04)* |

**Cause.** Reprise de données en masse lors du passage au nouvel ERP : la date de création
technique a été réécrite à la date d'import, la date métier d'origine n'a pas été conservée.

**Conséquence.** Le champ ne peut servir ni d'axe temporel, ni au calcul d'ancienneté, ni à la
mesure de durée de cycle de vente.

**Contournement appliqué.** Utilisation de `date_deadline` (« Expected Closing »), continue de
2018 à 2027 et renseignée sur 94 % du parc.

**Correctif.** Créer un champ `x_date_origine` alimenté depuis l'export de l'ancien système si
celui-ci est encore accessible. À défaut, acter que l'antériorité réelle est définitivement perdue
et le documenter pour les futurs analystes.

---

### A2 — `x_domaine` non renseigné avant 2022 🔴

**Constat.** Le champ portant la nature de l'offre est vide sur toute la période antérieure à 2022.

| Année | Total | Renseigné | % | CA non catégorisé |
|---|---|---|---|---|
| 2018 | 453 | 0 | **0,0 %** | 8,90 Md |
| 2019 | 1 097 | 0 | **0,0 %** | 36,42 Md |
| 2020 | 306 | 3 | **1,0 %** | 8,07 Md |
| 2021 | 539 | 45 | **8,3 %** | 7,89 Md |
| 2022 | 480 | 478 | 99,6 % | 0,10 Md |
| 2023 | 432 | 432 | 100,0 % | 0 |
| 2024 | 943 | 914 | 96,9 % | 1,08 Md |
| 2025 | 1 984 | 1 978 | 99,7 % | 0,46 Md |
| 2026 | 1 026 | 981 | 95,6 % | 1,37 Md |
| sans échéance | 447 | 0 | 0,0 % | 8,05 Md |

**Total non catégorisé : 2 876 opportunités, 72,34 Md XOF (31 % du CA).**

**Cause.** Le champ a été créé avec le nouveau système et n'a jamais fait l'objet d'une reprise
rétroactive.

**Conséquence.** Toute tendance par catégorie d'offre est **impossible avant 2022** — non pas
dégradée, mais inexistante. La série exploitable démarre en 2022.

**Correctif.** Deux options :
1. **Rétro-catégorisation semi-automatique** par mots-clés sur le libellé. Les intitulés sont
   souvent explicites (« Refresh WAN », « DATA CENTER », « VIRTUALISATION »), un taux de
   récupération de 60-70 % est plausible. À livrer avec un indicateur de confiance par ligne et
   une validation humaine avant tout import.
2. **Acter la rupture** et ne produire de reporting par domaine que sur 2022+.

---

### A3 — Deux référentiels de stages superposés 🔴

**Constat.** La base contient deux jeux de stages qui ne se recouvrent pas dans le temps.

| Système | Stages | Volume | Période (`date_deadline`) |
|---|---|---|---|
| Ancien (EN) | `New`, `Qualified`, `Proposition`, `Won` | 2 770 | 2018 → 2021 |
| Nouveau (FR) | `1-Qualification` → `9-Annulé` | 4 945 | 2022 → 2027 |

**Le piège.** L'ancien référentiel **ne comporte aucun stage « Perdu »**. Les affaires perdues y
sont matérialisées par l'archivage (`active = false`) et/ou `won_status = lost` :

- 1 039 opportunités archivées dans l'ancien système
- 371 portent `won_status = lost` sans jamais avoir de stage négatif

**Conséquence mesurée.** Un calcul de taux de gain fondé sur le seul `stage_id` produit
**100 % de réussite sur 2018-2021**, ce qui est faux. Valeurs réelles après reconstruction via
`won_status` / `active` : 62 % (2018), 47 % (2019), 37 % (2020), 56 % (2021).

**Contournement appliqué.** Statut consolidé selon la règle :
```
Gagné    si stage ∈ {6-Gagné, Won} ou won_status = won
Perdu    si stage ∈ {7-Perdu, 9-Annulé} ou won_status = lost ou active = false
Suspendu si stage ∈ {8-Suspendu}
sinon    En cours
```

**Correctif.** Documenter cette règle comme référence unique, et l'implémenter côté cockpit
plutôt que de la laisser à la charge de chaque analyste. **La rupture 2021 → 2022 observable
dans toutes les séries est un artefact de migration, pas un fait commercial.**

---

## 3. Points majeurs

### A4 — 2 274 opportunités périmées jamais clôturées 🟠

**Constat.** Dossiers dont l'échéance est dépassée au 04/08/2026 mais toujours en statut ouvert :

| Année d'échéance | Nb |
|---|---|
| 2018 | 43 |
| 2019 | 350 |
| 2020 | 151 |
| 2021 | 313 |
| 2022 | 2 |
| 2024 | 60 |
| 2025 | 550 |
| 2026 (échues) | 805 |
| **Total** | **2 274 — 73,34 Md XOF** |

**Conséquence.** Le pipeline affiché est massivement surévalué. Des dossiers de 2019 encore
« ouverts » sept ans après leur échéance ne sont pas des affaires vivantes : ils ont été
abandonnés sans clôture formelle.

**Correctif.**
1. Campagne de revue sur l'antériorité > 12 mois (857 dossiers antérieurs à 2022).
2. Automatisation : passage en « Suspendu » à J+90 après échéance dépassée sans mise à jour,
   avec notification au commercial avant bascule.

📎 Détail : [`anomalies_odoo_deadlines_depassees.csv`](anomalies_odoo_deadlines_depassees.csv) — 2 274 lignes.

---

### A5 — Doublons de saisie 🟠

**Critère retenu** : même client + même libellé normalisé (casse, accents, ponctuation) + même montant.

> **Écueil évité.** Un critère plus large (client + montant + année) remontait 436 groupes, mais
> 399 d'entre eux avaient des libellés différents — « Formation Cisco » et « CISCO ASA FIREPOWER »
> chez le même client sont deux affaires distinctes. Ce critère aurait détruit du CA réel.

> **Exception échéanciers.** Deux groupes ressemblent à des doublons mais n'en sont pas :
> MOWALI « abonnement cloud Azure » (7 × 20 M, échéances mensuelles) et SUNU GROUP
> « solution de collaboration M365 » (4 × 20 M). Ce sont des **plans de facturation récurrents**,
> conservés dans les calculs.

**Résultat.**

| | Brut | Après déduplication | Écart |
|---|---|---|---|
| Opportunités | 7 715 | 7 622 | −93 |
| CA total | 231,26 Md | 228,71 Md | **−2,56 Md (−1,11 %)** |

**Répartition des 93 lignes écartées.**

| Axe | Détail |
|---|---|
| Statut | **Gagné : 40** · Perdu : 25 · En cours : 21 · Suspendu : 7 |
| Équipe | BU : 51 · Sales CIV : 33 · Sales BF : 7 · Sales AM : 2 |
| Année | 2019 : 18 · 2024 : 15 · 2026 : 15 · 2023 : 14 · n.d. : 9 · 2025 : 8 · 2022 : 7 · 2018 : 4 · 2021 : 2 · 2020 : 1 |

⚠️ **40 doublons portent sur des affaires « Gagné »** : le CA réalisé est surévalué, pas seulement
le prévisionnel. Impact potentiel sur le calcul des commissions.

**Top 10 par CA redondant.**

| Client | Libellé | Montant | Nb | IDs | Garder | CA redondant |
|---|---|---|---|---|---|---|
| ECOBANK CI | Acquisition solution infogérance baie | 443,1 M | 2 | 7783, 7784 | 7784 | 443,1 M |
| ECOBANK CI | Acquisition solution infogérance baie | 440,1 M | 2 | 7787, 7788 | 7788 | 440,1 M |
| ANPTIC Burkina | Extension visioconférence | 400,0 M | 2 | 979, 1061 | 979 | 400,0 M |
| ORANGE BF | Acquisition serveurs projet CEM | 79,9 M | 3 | 1254, 1634, 1699 | 1254 | 159,8 M |
| ECOBANK CI | Démantèlement data center siège | 110,0 M | 2 | 8052, 8053 | 8053 | 110,0 M |
| BRIDGE BANK FINANCES | Acquisition F5 2026 | 96,7 M | 2 | 8114, 8115 | 8115 | 96,7 M |
| ABI | Contrat maintenance équipement réseau | 45,0 M | 3 | 8440, 8441, 8442 | 8440 | 90,0 M |
| ECOBANK CI | Upgrade téléphonie | 76,6 M | 2 | 8169, 8170 | 8170 | 76,6 M |
| PAA | Renouvellement Darktrace | 68,2 M | 2 | 8214, 8215 | 8214 | 68,2 M |
| COOPEC | AO audit sécurité | 60,0 M | 2 | 769, 1107 | 1107 | 60,0 M |

**Deux motifs récurrents** :
- **ECOBANK CI** — 4 groupes, 1,07 Md redondant à elle seule.
- **AFRICA GLOBAL LOGISTICS CI** — 10 modules de formation dupliqués à 2,0 M chacun.

Le schéma dominant est la **re-saisie manuelle** (deux commerciaux créant la même affaire, ou une
relance enregistrée comme nouvelle opportunité), pas une duplication technique.

**Correctif.** Contrôle d'unicité à la création : alerte si une opportunité existe avec même client
et libellé proche dans les 90 jours glissants.

📎 Détail : [`anomalies_odoo_doublons.csv`](anomalies_odoo_doublons.csv) — 179 lignes, une par
enregistrement, avec colonne `action` = GARDER / ECARTER. Règle de conservation : l'enregistrement
le plus récent (`create_date`, puis `id`).

---

### A6 — `x_domaine` et `x_nature` en texte libre 🟠

**Constat.** Les deux champs portant la catégorisation métier sont de type `char` (texte libre),
sans liste de valeurs. Conséquence directe et mesurable :

**`x_domaine`** — 12 valeurs distinctes pour 8 domaines réels :

| Valeur saisie | Occ. | Anomalie |
|---|---|---|
| `Modern Network Integration` | 16 | Variante de casse de `Modern Network integration` |
| `Expert & managed Services` | 1 | Variante de casse de `Expert & Managed Services` |
| `Security` | 1 | Hors nomenclature (→ `Secured IT` ?) |
| `Connectivity` | 1 | Hors nomenclature (→ `Modern Network integration` ?) |

**`x_nature`** — 17 valeurs distinctes pour 2 concepts :

| Valeur saisie | Occ. | Anomalie |
|---|---|---|
| `Recurrent` / `Reccurent` / `Recurring` / `REcurrent` / `reccurent` / `recurring` | 867 / 60 / 47 / 1 / 5 / 2 | **6 orthographes** pour un même concept |
| `One shot` / `One Shot` / `one shot` / `ONe shot` / `ONE shot` | 3 053 / 16 / 1 / 1 / 1 | **5 variantes de casse** |
| `3-Transmise`, `6-Gagné`, `Montage` | 1 chacun | **Copier-coller d'un stage** dans le champ nature |
| `8000000` | 1 | **Copier-coller d'un montant** |

**Correctif.** Convertir les deux champs en `selection` (ou `many2one` vers un modèle dédié si la
nomenclature doit évoluer), avec reprise des valeurs existantes selon la table de correspondance
fournie. Chantier estimé à une journée, il fiabilise définitivement l'axe d'analyse.

📎 Détail : [`anomalies_odoo_referentiels.csv`](anomalies_odoo_referentiels.csv) — 18 valeurs
déviantes avec cible proposée.

---

### A7 — `x_nature` vide à 47 % 🟠

**Constat.** 3 642 opportunités sur 7 715 n'ont pas de nature renseignée. Sur les 4 073 restantes :
3 072 « One shot », 982 « Récurrent », 15 « Mixte ».

**Conséquence.** La part de revenu récurrent — indicateur de valorisation le plus structurant pour
une ESN — n'est pas mesurable de façon fiable. Les **24,1 %** de récurrent observés sur le périmètre
renseigné ne sont pas projetables sur l'ensemble.

**Correctif.** Rendre le champ obligatoire au passage en « Transmise » (et non à la création, pour
ne pas freiner la saisie amont).

---

### A8 — Remplissage très inégal selon les équipes 🟠

| Équipe | `x_domaine` renseigné | CA portefeuille |
|---|---|---|
| Sales AM | 928 / 947 — **98,0 %** | 26,7 Md |
| BU | 2 626 / 3 545 — 74,1 % | 88,3 Md |
| Sales CIV | 1 285 / 2 957 — **43,5 %** | **103,7 Md** |
| Sales BF | 0 / 252 — **0,0 %** | 12,3 Md |

**Conséquence.** Sales CIV, le plus gros portefeuille en CA, est renseigné à moins de la moitié.
Toute comparaison inter-équipes par domaine est structurellement faussée — l'écart de qualité de
saisie y est systémique, pas accidentel.

**Correctif.** Traiter le sujet comme un point de conduite du changement (accompagnement,
non-régression contrôlée), pas seulement comme une contrainte technique.

---

## 4. Points mineurs

### A9 — Stages en doublon FR/EN 🟡

| Paire | Occurrences | CA cumulé de la paire |
|---|---|---|
| `8-Suspendu` / `8- Suspendu` | 682 / **55** | 24,31 Md |
| `1-Qualification` / `1- Qualification` | 731 / **21** | 25,95 Md |
| `7-Perdu` / `7- Perdu` | 939 / **3** | 52,67 Md |

L'écart tient à une **espace après le tiret**. Seules **79 opportunités** sont sur les variantes,
mais elles suffisent à scinder en deux des catégories totalisant **102,92 Md**. Ces stages ont été
fusionnés dans nos analyses ; en l'état ils **éclateront tout reporting Odoo natif** (vues kanban,
rapports standards, graphiques).

**Correctif.** Fusionner les stages en double dans `crm.stage` (79 opportunités à réaffecter).

---

### A10 — Probabilité incohérente avec le stage 🟡

25 opportunités ouvertes (0,18 Md) présentent une probabilité contradictoire avec leur stage :
24 en « Transmise » et 1 en « Négociation », toutes affichées à **0 %**.

Un dossier transmis au client à 0 % de probabilité n'a pas de sens : soit il est perdu et doit être
clôturé, soit le champ n'est pas tenu. L'enjeu financier est faible, mais le signal est celui d'un
suivi non tenu sur ces dossiers.

Probabilités moyennes constatées par stage (cohérentes globalement) :

| Stage | Nb | Proba moyenne |
|---|---|---|
| Qualification | 1 800 | 20,2 % |
| Montage | 77 | 20,9 % |
| Transmise | 1 407 | 53,7 % |
| Négociation | 161 | 77,3 % |
| Contractualisation | 8 | 87,5 % |

📎 Détail : [`anomalies_odoo_probabilites.csv`](anomalies_odoo_probabilites.csv) — 25 lignes.

---

### A11 — 447 opportunités sans échéance 🟡

447 dossiers (8,05 Md) n'ont pas de `date_deadline`. Comme `create_date` est inexploitable (A1),
ils sont **exclus de tout axe temporel** et n'apparaissent dans aucune série annuelle.

---

### A12 — Champs de pilotage peu alimentés 🟡

| Champ | Libellé | Renseigné | Remarque |
|---|---|---|---|
| `x_fp_reference` | N° FP | 3 228 / 7 715 (41,8 %) | — |
| `x_mb` | Marge brute (%) | 2 299 / 7 715 (29,8 %) | 1 valeur à **−7 %** |
| `x_dr` | DR ? | 1 527 / 7 715 (19,8 %) | Sémantique du champ à clarifier |
| `x_focus` | Focus | 807 / 7 715 (10,5 %) | Quasi inutilisé |

La marge brute renseignée sur moins d'un tiers du parc interdit tout pilotage par la rentabilité.

**Autres points de forme** : 551 opportunités à CA = 0 (7,1 %) — **entièrement concentrées sur
l'ancien système**, zéro depuis 2022 : la qualité de chiffrage s'est nettement améliorée.

---

## 5. Anomalies de facturation

Cette section porte sur `account.move` (factures) et `sale.order` (commandes) — la source du
**CA réellement réalisé**, distincte du prévisionnel des opportunités.

**Chiffre de référence : 41,75 Md XOF net** = 47,09 Md facturés − 5,34 Md d'avoirs, sur 2019-2026
(dernière facture en base : **06/07/2026**).

---

### A13 — Commandes fantômes à 4 115 milliards XOF 🔴

**Constat.** Deux commandes en brouillon portent un montant aberrant :

| Référence | Client | Montant HT |
|---|---|---|
| `FP/2019/1843` | AIR CÔTE D'IVOIRE | **4 115 503 112 482 XOF** |
| `FP/2019/1842` | AIR CÔTE D'IVOIRE | **4 115 503 112 482 XOF** |

Soit **8 231 Md à elles deux**, sur un total `sale.order` de 8 442 Md — elles représentent 97,5 %
du montant cumulé des commandes.

**Ordre de grandeur** : 4 115 milliards XOF ≈ 6,3 milliards EUR, soit environ **deux fois le budget
annuel de l'État de Côte d'Ivoire** pour une seule commande. Il s'agit sans ambiguïté d'une erreur
de saisie (probablement un montant saisi en unités monétaires élémentaires, ou un test).

**Conséquence.** Tout indicateur bâti sur `sale.order` (carnet de commandes, taux de transformation,
prévisionnel) est inexploitable tant que ces deux lignes existent. Elles sont en état *brouillon*,
donc **n'affectent pas le CA facturé** — le chiffre de 41,75 Md reste fiable.

**Correctif.** Supprimer ou corriger les deux commandes. Ajouter une contrainte de plafond à la
saisie (alerte au-delà d'un seuil, par exemple 5 Md).

---

### A14 — Taux d'avoir en dérive : 1 % → 28 % 🔴

**Constat.** Le poids des avoirs sur le facturé brut est passé de 1,1 % à 28,4 % en sept ans.

| Année | Factures | Brut (Md) | Nb avoirs | Avoirs (Md) | **Taux d'avoir** |
|---|---|---|---|---|---|
| 2019 | 347 | 3,72 | 8 | −0,04 | 1,1 % |
| 2020 | 378 | 5,93 | 7 | −0,20 | 3,3 % |
| 2021 | 433 | 5,29 | 10 | −0,22 | 4,2 % |
| 2022 | 406 | 4,25 | 7 | −0,05 | 1,1 % |
| 2023 | 434 | 6,58 | 23 | −0,48 | 7,3 % |
| 2024 | 304 | 7,42 | 12 | −0,89 | **11,9 %** |
| 2025 | 417 | 10,65 | 46 | −2,55 | **24,0 %** |
| 2026\* | 207 | 3,25 | 44 | −0,92 | **28,4 %** |

\* Exercice partiel, arrêté au 06/07/2026.

La rupture est nette à partir de 2023, et s'accélère. **Le nombre d'avoirs a été multiplié par 6
entre 2022 et 2025** (7 → 46), leur montant par 51.

**Concentration par client** — certains comptes présentent des taux d'avoir insoutenables :

| Client | Avoirs | Montant | Brut facturé | Taux |
|---|---|---|---|---|
| Banque Africaine de Développement (BAD) | 14 | −1,52 Md | 4,66 Md | **32,6 %** |
| Orange LIBERIA | 8 | −0,84 Md | 4,05 Md | 20,8 % |
| SOCIÉTÉ GÉNÉRALE CI | 5 | −0,43 Md | 3,69 Md | 11,6 % |
| Unité Coord. C2D-JUSTICE | 3 | −0,30 Md | 0,62 Md | **48,6 %** |
| GT BANK | 4 | −0,15 Md | 0,66 Md | 23,6 % |
| MANSA BANK | 2 | −0,13 Md | 0,17 Md | **75,0 %** |
| NESTLÉ CI | 5 | −0,12 Md | 0,23 Md | **52,6 %** |
| CARGILL COCOA | 6 | −0,11 Md | 0,32 Md | 33,4 % |

**Les 5 plus gros avoirs** :

| Montant | Date | Client | Émis par | Pièce d'origine |
|---|---|---|---|---|
| −687,5 M | 24/06/2025 | BAD | User_test | `FP/2025/11679` |
| −499,6 M | 15/12/2025 | BAD | Yaya SAKO | `JV/2025/12/0020` |
| −294,1 M | 22/04/2024 | Orange LIBERIA | Loua Désiré BELLAI | `FP/2023/8946` |
| −242,3 M | 06/08/2025 | SOCIÉTÉ GÉNÉRALE CI | Komenan Yacouba YAO | `FP/2025/11121` |
| −225,5 M | 13/05/2023 | Orange LIBERIA | Segui Mireille KOUADIO | `JVE/2023/05/0004` |

**Conséquence sur la lecture mensuelle.** Certains mois voient leur CA effacé par les avoirs :

| Mois | Brut | Avoirs | **Taux** |
|---|---|---|---|
| avril 2024 | 0,53 Md | −0,57 Md | **109,1 %** — CA net négatif |
| juin 2025 | 0,84 Md | −0,73 Md | **86,8 %** |
| juin 2024 | 0,25 Md | −0,16 Md | 63,9 % |
| juin 2026 | 0,75 Md | −0,38 Md | 50,7 % |
| décembre 2025 | 1,98 Md | −0,86 Md | 43,5 % |

**Un pic de facturation mensuel peut donc être un artefact comptable, pas une performance
commerciale.** Décembre 2025 illustre le cas : premier mois en brut (1,98 Md), il retombe en
deuxième position en net (1,12 Md).

**Point d'attention.** Les références des avoirs (`JV/`, `JVE/`, `JVEXO/`) sont des écritures
diverses, pas des annulations de factures de vente classiques. Plusieurs pointent vers une pièce
d'origine elle-même de type `JV`. Cela suggère des **régularisations comptables** plutôt que des
annulations commerciales — mais rien dans les données ne permet de trancher.

**Correctif.**
1. **Documenter le motif** de chaque avoir (champ dédié ou `ref` normalisée). Sans motif, impossible
   de distinguer une erreur de facturation d'une annulation de marché ou d'une régularisation.
2. Revue du compte **BAD** en priorité (1,52 Md d'avoirs, 32,6 %).
3. Décider d'une convention de reporting : le CA communiqué est-il brut ou net d'avoirs ? Les deux
   chiffres diffèrent de 11,3 % sur la période.

📎 Détail : [`anomalies_odoo_avoirs.csv`](anomalies_odoo_avoirs.csv) — 157 avoirs.

---

### A15 — Comptes techniques en tête du classement des ventes 🟠

**Constat.** Les deux premiers « commerciaux » par CA facturé ne sont pas des personnes :

| Rang | Compte | Factures | CA net | Part | Nature |
|---|---|---|---|---|---|
| 1 | **`User_test`** | 232 | 8,18 Md | **19,6 %** | Compte technique |
| 5 | **`Assistance Commerciale`** | 191 | 3,77 Md | **9,0 %** | Compte collectif |
| | **Total non attribuable** | **423** | **11,95 Md** | **28,6 %** | |

**Répartition temporelle de `User_test`** : 1,62 Md (2019), 3,27 Md (2020), 2,52 Md (2021),
0,60 Md (2022), puis quasi nul. Le compte s'éteint après 2022 — une reprise d'attribution a été
faite, mais **l'historique 2019-2021 reste bloqué sur un compte technique**. Ses principaux clients
sont ORANGE CI (4,92 Md), Orange LIBERIA (1,27 Md) et la BAD (0,52 Md).

`Assistance Commerciale` suit la trajectoire inverse : nul jusqu'en 2022, puis 0,16 → 0,50 →
2,26 Md (2025) → 0,85 Md (2026 partiel). Il **absorbe une part croissante du CA récent**, et porte
à lui seul 74 % du pic de mai 2026.

**Conséquence.** Le classement commercial réel est faussé. Hors comptes techniques, le premier
vendeur est **Yaya SAKO (5,78 Md)**, pas `User_test`.

**Correctif.** Réaffecter l'historique `User_test` aux commerciaux réels si la correspondance est
reconstituable ; à défaut, l'exclure explicitement de tout classement. Clarifier le rôle
d'`Assistance Commerciale` : compte de back-office ou véritable canal de vente ?

---

### A16 — Groupe Orange éclaté en 10 tiers distincts 🟠

**Constat.** Le groupe Orange est facturé sous 10 comptes séparés :

| Compte | CA net |
|---|---|
| ORANGE CÔTE D'IVOIRE | 6,76 Md |
| Orange LIBERIA | 3,20 Md |
| ORANGE BANK | 0,07 Md |
| ORANGE MONEY GROUP | 0,07 Md |
| ORANGE CENTRAFRIQUE SA | 0,05 Md |
| ORANGE CLOUD & CYBER SOLUTIONS | 0,03 Md |
| ORANGE MONEY CÔTE D'IVOIRE | 0,02 Md |
| ORANGE DOBB, ORANGE RDC SA, ORANGE BANK AFRICA | 0,02 Md |
| **Total groupe** | **10,22 Md — 24,5 % du CA** |

**Conséquence.** Le premier client de l'entreprise **n'apparaît nulle part** comme tel. Les
classements font ressortir ORANGE CI (16,2 %) puis MTN CI (7,9 %), masquant qu'un quart du chiffre
d'affaires dépend d'un seul groupe. C'est un angle mort en matière de risque de concentration.

*Nota* : certaines de ces entités sont juridiquement distinctes et facturées séparément à juste
titre. L'anomalie n'est pas leur existence, mais **l'absence de lien de groupe** permettant une vue
consolidée.

**Correctif.** Renseigner le champ `parent_id` sur `res.partner` pour rattacher les filiales à une
société mère, ou créer une catégorie de partenaire « Groupe Orange ». Odoo sait alors consolider
nativement.

*(Voir aussi le point 5 de la section « Questions métier » sur le doublon présumé
`ORANGE CÔTE D'IVOIRE` / `BAHO Serge-Commercial-ORANGE CI` côté CRM.)*

---

### A17 — Commercial à CA net négatif 🟡

**Constat.** `KANGA AMANI EMILE CONSTANT` affiche un CA net de **−0,42 Md** :
14 factures pour +0,12 Md, contre **17 avoirs pour −0,54 Md**.

Ce profil — plus d'avoirs que de factures — est celui d'un rôle d'**administration des ventes**
(émission des régularisations), pas d'un commercial. Il apparaît pourtant au classement des ventes,
en dernière position avec un montant négatif.

**Correctif.** Distinguer les utilisateurs ADV des commerciaux dans les rapports, ou n'affecter les
avoirs qu'au commercial d'origine de la facture annulée.

---

### A18 — Lien opportunité ↔ facture quasi absent 🟡

**Constat.** Seules **46 opportunités sur 7 715** (0,6 %) portent une commande liée (`order_ids`),
pour 60 commandes distinctes. Côté factures, `invoice_origin` est renseigné à 99,6 % (3 070 / 3 083),
mais pointe vers des références de commande ou d'écriture, pas vers l'opportunité d'origine.

**Conséquence.** Il est **impossible de calculer un taux de transformation réel**
(opportunité gagnée → commande → facture), ni de rapprocher les 231 Md de pipeline des 41,75 Md
effectivement facturés. Les deux univers cohabitent sans passerelle.

**Correctif.** Activer le lien `opportunity_id` sur `sale.order` dans le processus de création de
commande. C'est un paramétrage Odoo standard, pas un développement.

---

## 6. Saisonnalité du chiffre d'affaires

Analyse ajoutée à la demande — elle n'est pas une anomalie mais un constat structurant, dont la
lecture est directement affectée par A14 (avoirs).

### Profil mensuel moyen 2019-2025

| Mois | Part moyenne du CA annuel |
|---|---|
| **Décembre** | **20,7 %** |
| Août | 10,3 % |
| Octobre | 9,1 % |
| Novembre | 9,0 % |
| Mars | 8,2 % |
| Septembre | 7,1 % |
| Avril | 7,0 % |
| Mai | 6,7 % |
| Juin | 6,7 % |
| Février | 6,4 % |
| Juillet | 6,2 % |
| Janvier | 2,8 % |

**Décembre est le mois de pic structurel**, premier ou deuxième chaque année : 25,0 % (2019),
12,4 % (2020), 25,2 % (2021), 21,6 % (2022), 20,7 % (2023), 26,2 % (2024), 13,8 % (2025).
Janvier est systématiquement le creux.

**Le second semestre porte 57 à 66 % du CA annuel** — 66,0 % (2019), 63,4 % (2020), 59,4 % (2021),
61,3 % (2022), 62,3 % (2023), 66,2 % (2024), 57,2 % (2025). Profil cohérent avec des cycles de
commande publique et de clôture budgétaire client.

### 2025 — les 12 mois

| Mois | Factures | Brut (Md) | Avoirs (Md) | **Net (Md)** | % année |
|---|---|---|---|---|---|
| Janvier | 15 | 0,16 | −0,02 | 0,14 | 1,8 % |
| Février | 30 | 0,92 | −0,00 | 0,92 | 11,4 % |
| Mars | 28 | 0,45 | −0,09 | 0,36 | 4,5 % |
| **Avril** | 21 | 1,84 | −0,24 | **1,61** | **19,8 %** |
| Mai | 47 | 0,33 | −0,01 | 0,32 | 4,0 % |
| Juin | 23 | 0,84 | −0,73 | 0,11 | 1,4 % |
| Juillet | 36 | 0,40 | 0,00 | 0,40 | 4,9 % |
| Août | 22 | 1,17 | −0,40 | 0,77 | 9,5 % |
| Septembre | 55 | 1,00 | −0,19 | 0,81 | 10,1 % |
| Octobre | 33 | 0,87 | −0,01 | 0,86 | 10,6 % |
| Novembre | 32 | 0,69 | −0,01 | 0,68 | 8,4 % |
| Décembre | 75 | 1,98 | −0,86 | 1,12 | 13,8 % |
| **Total** | **463** | **9,64** | **−1,54** | **8,10** | 100 % |

**Pic 2025 : avril — 1,61 Md sur 21 factures seulement.** Trois comptes font 1,36 Md sur 1,61 :
BAD (0,76 Md), MOOV AFRICA CI (0,35 Md), MTN CI (0,25 Md). Commerciaux : Yaya SAKO (0,76 Md) et
Aristide Daniel CAUPHY (0,64 Md).

⚠️ **Décembre est premier en brut (1,98 Md) mais deuxième en net (1,12 Md)** après 0,86 Md d'avoirs.
Juin est le creux (0,11 Md) pour la même raison : 0,84 Md facturés, 0,73 Md annulés.

### 2026 — exercice partiel

| Mois | Factures | Brut (Md) | Avoirs (Md) | **Net (Md)** | % période |
|---|---|---|---|---|---|
| Janvier | 11 | 0,33 | −0,14 | 0,19 | 8,4 % |
| Février | 30 | 0,34 | −0,09 | 0,24 | 10,4 % |
| Mars | 50 | 0,47 | −0,14 | 0,34 | 14,5 % |
| Avril | 43 | 0,57 | −0,12 | 0,45 | 19,2 % |
| **Mai** | 37 | 0,79 | −0,05 | **0,74** | **31,8 %** |
| Juin | 35 | 0,75 | −0,38 | 0,37 | 15,8 % |
| Juillet | 1 | 0,00 | 0,00 | 0,00 | 0,0 % |
| Août → Décembre | — | — | — | *à venir* | — |
| **Total à date** | **251** | **3,25** | **−0,92** | **2,33** | 100 % |

**Pic 2026 à date : mai — 0,74 Md.** ⚠️ `Assistance Commerciale` y porte **0,55 Md sur 0,74 (74 %)** —
un compte collectif, pas un commercial identifié (voir A15). Comptes principaux : Cellule de
Coordination de la Coopération (0,19 Md), NSIA Banque (0,10 Md), PROSUMA (0,09 Md).

**Ce pic est provisoire** : au vu de la saisonnalité, décembre devrait le dépasser.

### Comparaison à périmètre égal (janvier-juin)

| Mois | 2025 | 2026 | Évolution |
|---|---|---|---|
| Janvier | 0,14 | 0,19 | +37 % |
| Février | 0,92 | 0,24 | −74 % |
| Mars | 0,36 | 0,34 | −6 % |
| Avril | 1,61 | 0,45 | −72 % |
| Mai | 0,32 | 0,74 | +129 % |
| Juin | 0,11 | 0,37 | +233 % |
| **S1** | **3,46** | **2,33** | **−33 %** |

**Le retrait de 33 % est trompeur.** Il tient presque entièrement au pic d'avril 2025 (dossier BAD).
Hors avril, le S1 2025 fait 1,85 Md contre **1,88 Md en 2026** — quasi-stabilité. La tendance
mai-juin 2026 est franchement positive (+129 %, +233 %). **2026 est plus régulier, pas plus faible.**

**Projection d'atterrissage 2026** : si la saisonnalité habituelle se reproduit (57-66 % du CA au S2),
l'exercice se situerait entre **5,5 et 6,8 Md**, contre 8,10 Md en 2025. À confirmer — il reste six
mois, dont décembre.

📎 Détail : [`ca_mensuel_facture.csv`](ca_mensuel_facture.csv) — 89 lignes, tous exercices.

---

## 7. Classement commercial et concentration client

### CA net facturé par commercial (tous exercices)

| # | Commercial | Factures | CA net (Md) | % | Clients | Ticket moy. |
|---|---|---|---|---|---|---|
| 1 | ⚠️ `User_test` *(compte technique)* | 232 | 8,18 | 19,6 % | 20 | 35,3 M |
| 2 | **Yaya SAKO** | 387 | 5,78 | 13,8 % | 99 | 14,9 M |
| 3 | **Segui Mireille KOUADIO** | 318 | 5,34 | 12,8 % | 100 | 16,8 M |
| 4 | **Aristide Daniel CAUPHY** | 106 | 4,88 | 11,7 % | 19 | 46,1 M |
| 5 | ⚠️ `Assistance Commerciale` *(collectif)* | 191 | 3,77 | 9,0 % | 75 | 19,7 M |
| 6 | Zirihi Stéphane NAHI | 428 | 2,95 | 7,1 % | 105 | 6,9 M |
| 7 | Koffi Paulin APEDO | 207 | 2,04 | 4,9 % | 72 | 9,9 M |
| 8 | Oumar SANOGO | 165 | 1,99 | 4,8 % | 49 | 12,1 M |
| 9 | Loua Désiré BELLAI | 82 | 1,44 | 3,4 % | 45 | 17,6 M |
| 10 | Gwladys KINIMO | 341 | 1,41 | 3,4 % | 135 | 4,1 M |
| 11 | Guy-Martial DATCHA | 118 | 0,92 | 2,2 % | 44 | 7,8 M |
| 12 | Maryline AGOU | 41 | 0,59 | 1,4 % | 18 | 14,5 M |
| … | *20 autres < 0,5 Md* | | | | | |
| 32 | ⚠️ KANGA AMANI EMILE CONSTANT *(ADV)* | 31 | **−0,42** | −1,0 % | 25 | — |

**Hors comptes techniques, le premier vendeur est Yaya SAKO (5,78 Md).**

### Concentration du portefeuille

| Périmètre | Part du CA |
|---|---|
| Top 5 comptes | **47,1 %** |
| Top 10 | 61,3 % |
| Top 20 | 71,4 % |
| Top 50 | 84,7 % |
| *Total* | *468 comptes facturés* |

**Cinq clients font près de la moitié du chiffre d'affaires.** Consolidé, le groupe Orange pèse
24,5 % à lui seul (A16). C'est un risque de concentration à part entière, qui n'apparaît dans aucun
indicateur actuel.

📎 Détail : [`ca_par_commercial.csv`](ca_par_commercial.csv) (32 lignes) et
[`ca_par_compte.csv`](ca_par_compte.csv) (468 lignes).

---

## 8. Impact consolidé sur les indicateurs publiés

### Périmètre CRM — prévisionnel

| Indicateur | Valeur brute | Valeur corrigée | Écart |
|---|---|---|---|
| Nombre d'opportunités | 7 715 | 7 622 | −93 |
| CA total | 231,26 Md | 228,71 Md | −2,56 Md |
| Pipeline ouvert (nb) | — | 2 524 | — |
| Pipeline ouvert (CA) | 108,55 Md* | **84,54 Md** | −24,01 Md |
| Pipeline pondéré | 37,40 Md* | 30,54 Md | −6,86 Md |

\* Valeurs d'un premier calcul fondé sur le seul `stage_id`. L'écart de 24 Md ne provient pas des
doublons (0,4 Md) mais de la prise en compte correcte de `won_status` sur l'ancien système (A3).

**Le chiffre de pipeline à retenir est 84,54 Md**, dont **39,10 Md (46 %) sans domaine renseigné** —
majoritairement les dossiers antérieurs à 2022 jamais clôturés (A4). Tant qu'ils restent ouverts,
ils polluent toute analyse par catégorie du pipeline actuel.

### Périmètre Facturation — réalisé

| Indicateur | Valeur | Remarque |
|---|---|---|
| CA facturé brut (2019-2026) | 47,09 Md | 2 926 factures |
| Avoirs | −5,34 Md | 157 pièces, **11,3 % du brut** (A14) |
| **CA net facturé** | **41,75 Md** | Chiffre de référence |
| Dont non attribuable à un commercial | 11,95 Md | **28,6 %** (A15) |
| Dont groupe Orange consolidé | 10,22 Md | **24,5 %** (A16) |
| Carnet de commandes (`sale.order`) | *inexploitable* | 8 231 Md fictifs (A13) |

**Écart pipeline / réalisé** : 84,54 Md de pipeline ouvert contre 8,10 Md facturés en 2025 — un
rapport de 1 à 10. Ce n'est pas nécessairement anormal (le pipeline couvre plusieurs exercices et
inclut les dossiers périmés d'A4), mais **le taux de transformation réel reste incalculable**
faute de lien opportunité ↔ facture (A18).

---

## 9. Plan d'action proposé

Classé par rapport valeur / effort.

| # | Action | Anomalies traitées | Effort | Gain |
|---|---|---|---|---|
| 1 | **Corriger les 2 commandes à 4 115 Md** | A13 | **~15 min** | Débloque tout indicateur `sale.order` |
| 2 | Clôturer les 2 274 dossiers périmés | A4 | Faible — revue métier, aucun dev | Sincérité immédiate du pipeline |
| 3 | **Audit des avoirs : documenter le motif** | A14 | Revue comptable | Explique 5,34 Md et fiabilise le CA mensuel |
| 4 | Corriger les 40 doublons en statut « Gagné » | A5 | Faible — 40 fiches | Fiabilise le CA réalisé et les commissions |
| 5 | **Rattacher les 10 entités Orange (`parent_id`)** | A16 | ~1 h | Révèle le vrai premier client (24,5 % du CA) |
| 6 | Fusionner les stages en double dans `crm.stage` | A9 | ~2 h | Débloque le reporting Odoo natif |
| 7 | **Réaffecter / exclure `User_test` des classements** | A15 | ~0,5 jour | Rend le classement commercial exploitable |
| 8 | Passer `x_domaine` / `x_nature` en listes fermées | A6 | ~1 jour de dev | Supprime la divergence à la source |
| 9 | Contrôle d'unicité à la création | A5 | ~1 jour de dev | Traite la cause des doublons |
| 10 | Rendre `x_domaine` + `x_nature` obligatoires en « Transmise » | A2, A7 | ~0,5 jour | Garantit le futur sans freiner l'amont |
| 11 | Automatiser le passage en « Suspendu » à J+90 | A4 | ~0,5 jour | Évite la reconstitution du stock |
| 12 | **Activer `opportunity_id` sur `sale.order`** | A18 | Paramétrage standard | Rend calculable le taux de transformation |
| 13 | Plan de remise à niveau Sales CIV / Sales BF | A8 | Conduite du changement | Comparabilité inter-équipes |
| 14 | Rétro-catégorisation assistée des 2 876 non catégorisés | A2 | ~2 jours + validation | Récupère 60-70 % de 72,34 Md |
| 15 | Documenter la règle de statut consolidé dans le cockpit | A3 | ~0,5 jour | Évite que chaque analyste la réinvente |

**Les cinq premières actions sont à fort rendement immédiat** : l'action 1 coûte quinze minutes et
débloque un module entier ; les actions 3 et 5 ne demandent aucun développement.

---

## 10. Questions métier ouvertes

Ces points ne sont pas des anomalies techniques mais des constats qui appellent un arbitrage.

### Positionnement commercial

1. **Datacenter Facilities** — 282 opportunités, 12,70 Md engagés sur 2022-2026, **0,30 Md gagnés**
   (29 % de réussite). Question de positionnement, pas de CRM.
2. **Modern Network integration** — 406 perdus contre 281 gagnés, sur les plus gros tickets de la
   maison (51,3 M de moyenne). L'entreprise perd là où elle mise le plus.
3. **Expert & Managed Services** — explose en volume (501 opportunités en 2025) à 9,3 M de ticket
   moyen. Si un objectif commercial est indexé sur le *nombre* d'opportunités, ce domaine gonfle le
   compteur sans peser sur le CA.

### Structure client

4. **Deux comptes Orange distincts côté CRM** — `ORANGE CÔTE D'IVOIRE` (74 opp., 8,14 Md) et
   `BAHO Serge-Commercial-ORANGE CI` (224 opp., 11,27 Md). S'il s'agit du même client, le
   rapprochement en ferait le premier compte du portefeuille devant MTN CI (17,05 Md).
   *Côté facturation, le même groupe est éclaté en 10 tiers — voir A16.*
5. **Risque de concentration** — 5 clients font 47,1 % du CA facturé, le groupe Orange consolidé
   24,5 % à lui seul. Ce risque n'est suivi par aucun indicateur actuel. Faut-il en faire un KPI ?
6. **Échéanciers récurrents** — MOWALI et SUNU GROUP sont saisis comme N opportunités identiques
   plutôt qu'une opportunité avec plan de facturation. À normaliser, faute de quoi tout
   dédoublonnage futur les cassera.

### Facturation

7. **Pourquoi le taux d'avoir a-t-il été multiplié par 25 depuis 2019 ?** (1,1 % → 28,4 %).
   Changement de process de facturation, litiges clients, ou pratique de régularisation comptable ?
   Les références `JV`/`JVE`/`JVEXO` orientent vers la troisième hypothèse, mais rien ne le confirme.
8. **Convention de reporting CA** — brut ou net d'avoirs ? L'écart est de 11,3 % sur la période, et
   jusqu'à 43,5 % sur un mois donné (décembre 2025). Une règle unique doit être arrêtée.
9. **Rôle d'`Assistance Commerciale`** — compte de back-office ou véritable canal de vente ? Il porte
   9 % du CA total et 74 % du pic de mai 2026, ce qui rend l'arbitrage nécessaire pour tout suivi
   de performance individuelle.

---

## 11. Fichiers de détail

### Anomalies CRM

| Fichier | Contenu | Lignes |
|---|---|---|
| [`anomalies_odoo_doublons.csv`](anomalies_odoo_doublons.csv) | 86 groupes, une ligne par enregistrement, colonne `action` GARDER/ECARTER | 179 |
| [`anomalies_odoo_deadlines_depassees.csv`](anomalies_odoo_deadlines_depassees.csv) | Dossiers ouverts à échéance dépassée, triés par montant | 2 274 |
| [`anomalies_odoo_referentiels.csv`](anomalies_odoo_referentiels.csv) | Valeurs déviantes de `x_domaine` / `x_nature` + cible proposée | 18 |
| [`anomalies_odoo_probabilites.csv`](anomalies_odoo_probabilites.csv) | Opportunités ouvertes à probabilité incohérente | 25 |

### Anomalies et analyses de facturation

| Fichier | Contenu | Lignes |
|---|---|---|
| [`anomalies_odoo_avoirs.csv`](anomalies_odoo_avoirs.csv) | 157 avoirs postés, triés du plus lourd au plus léger | 157 |
| [`ca_mensuel_facture.csv`](ca_mensuel_facture.csv) | CA brut / avoirs / net par mois, 2019-2026, avec taux d'avoir | 89 |
| [`ca_par_commercial.csv`](ca_par_commercial.csv) | CA net par commercial et par exercice | 32 |
| [`ca_par_compte.csv`](ca_par_compte.csv) | CA net par compte client, avec cumul et commercial principal | 468 |

Encodage UTF-8 avec BOM, séparateur `;` — ouverture directe dans Excel.

---

*Document généré le 2026-08-04 à partir d'une extraction en lecture seule d'Odoo
(`crm.lead`, `account.move`, `sale.order`). Dernière facture en base : 06/07/2026.
Aucune modification n'a été apportée à la base.*
