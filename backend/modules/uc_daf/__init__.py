"""UC DAF — pilotage du Directeur Administratif et Financier.

Répond à la note « Point DAF financier » du 04/08/2026, qui demande trois tableaux
de bord et un volet transverse :

1. BUDGET — performance globale, résultat net, marge brute réalisée à date,
   top 10 des plus grosses charges (indicateur voté par le DAF), lignes
   budgétaires les plus consommées ;
2. RELATION COMMERCIALE — DSO (créances), DPO (dettes), suivi des mauvais payeurs ;
3. TRÉSORERIE PRÉVISIONNELLE — vigilance sur les créances proches de leur échéance,
   atterrissage mensuel encaissement / décaissement sur une vue calendaire ;
4. FORMATION — bons usages de l'outil, pour éviter qu'une saisie fausse corrompe
   les données sur lesquelles tout ce qui précède est calculé.

Découpage par NATURE de ce qui est servi, comme `uc_commercial` :

- `queries.py`             lectures SQL du miroir (aucun calcul métier) ;
- `budget.py`              tableau de bord n°1 ;
- `relation_commerciale.py` tableau de bord n°2 ;
- `tresorerie_prev.py`     tableau de bord n°3 ;
- `formation.py`           volet transverse + contrôles de qualité de saisie ;
- `statique.py`            TOUT ce qui est posé faute de donnée réelle.

Ce que le miroir permet, et ce qu'il ne permet pas — la ligne de partage de ce
module, vérifiée sur les données du 12/08/2026 :

MESURÉ. Les factures CLIENTS sont là (2 957 lignes, échéance renseignée à 100 %,
date de règlement réelle sur 2 045 d'entre elles) : DSO, retard constaté, balance
âgée, mauvais payeurs et échéancier des créances sont des calculs, pas des
estimations. Les achats fournisseurs engagés le sont aussi (2 133 commandes) : le
top des charges est mesuré. Les dossiers portent CA et dépenses définitifs : la
marge brute réalisée est mesurable là où la dépense est imputée.

NON MESURÉ. `supplier_invoices` est VIDE : aucune facture fournisseur n'est
synchronisée, donc aucune échéance de dette — le DPO n'est pas calculable et le
décaissement prévisionnel n'a pas d'échéancier. Aucune table budgétaire n'existe :
le budget voté est une décision, pas une donnée. Aucune comptabilité générale
n'est raccordée : les charges de structure (salaires, loyers, amortissements,
impôts) sont hors du miroir, donc le résultat net n'est pas mesurable.

D'où la règle qui traverse le module, identique à `uc_commercial` : ce qui est
calculé sur des faits et ce qui est posé en attendant la donnée ne se mélangent
JAMAIS dans une même valeur. Chaque bloc porte `source: "reel" | "statique" |
"mixte"` et reste identifiable jusqu'à l'écran. Sur le résultat net, la marge
brute mesurée et les charges de structure posées restent deux champs distincts :
le total dérivé est nommé pour ce qu'il est, une projection.

Convention de montants, valable dans tout le module : `amount` est exprimé dans
la devise de la SOCIÉTÉ (FCFA), la colonne `currency` ne conserve que la devise du
document. C'est déjà l'hypothèse du reste du miroir (cf.
`local_crm_adapter.get_top_suppliers`, qui somme `amount` en `montant_total_xof`),
et les décimales des montants en devise le confirment — ce sont des conversions.
Le nombre de documents en devise étrangère est néanmoins remonté à l'écran comme
contrôle de qualité (1 065 achats sur 2 133, 210 factures sur 2 957).
"""
