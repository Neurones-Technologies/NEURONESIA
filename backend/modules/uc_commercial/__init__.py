"""UC Commercial — pilotage du Directeur Commercial.

Répond au compte-rendu d'entretien DC du 04/08/2026 et au cadrage
`docs/Questions_cadrage_DC_Cockpit.md`. Le module est découpé selon la NATURE de
ce qu'il sert, pas selon les écrans :

- `queries.py`    lectures SQL du miroir (aucun calcul métier) ;
- `referentiel.py` identité des commerciaux (texte libre Odoo → identité stable) ;
- `comptes.py`     animation de compte : top comptes, pics d'activité, acquisition ;
- `qualite_pipe.py` opportunités à closer / à compléter ;
- `cycle_vie.py`   traçage des affaires au-dessus du seuil, mouvement du pipe ;
- `objectifs.py`   objectifs et Gap ;
- `prospection.py` efficacité par commercial, indice de prospection ;
- `marche.py`      axes stratégiques, secteurs, part de marché, veille ;
- `visites.py`     fichier de visite ;
- `alertes.py`     file d'alertes dérivée des signaux ci-dessus ;
- `statique.py`    TOUT ce qui est encore figé faute de donnée réelle.

La règle qui traverse le module : ce qui est calculé sur des faits et ce qui est
posé en attendant la donnée ne se mélangent JAMAIS dans une même valeur. Chaque
retour porte `source: "reel" | "statique" | "mixte"`, et un bloc `statique` est
identifiable jusqu'à l'écran. Un chiffre de démonstration présenté comme mesuré
est pire que pas de chiffre : il se retrouve dans une revue de performance.
"""
