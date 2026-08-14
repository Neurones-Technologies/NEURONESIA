# Test de montée en charge — API cockpit

Scénario Locust sur les endpoints de **lecture** du cockpit (`/v1/dashboard/*`).

## Prérequis

```bash
cd backend
.venv/Scripts/python.exe -m pip install locust
```

## Lancer contre une instance représentative

Ne pas tester le serveur de développement : lancé avec `--reload`, il tourne
avec **1 worker** et un watcher de fichiers actif, ce qui sérialise les
requêtes et sous-estime la production. La production tourne avec
`--workers 2` (cf. `backend/Dockerfile`).

Démarrer une instance configurée comme la production, sur un port distinct :

```bash
cd backend
.venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8100 --workers 2
```

Attendre le message de fin d'initialisation des adapters (le chargement des
modèles d'embedding prend plusieurs dizaines de secondes au premier démarrage),
puis vérifier :

```bash
curl http://127.0.0.1:8100/v1/health
```

## Exécuter la montée en charge

Paliers successifs, pour situer le point de rupture :

```bash
cd backend
.venv/Scripts/python.exe -m locust -f tests/load/locustfile.py \
    --host http://127.0.0.1:8100 --headless -u 10 -r 2 -t 2m
```

Puis relancer avec `-u 25`, `-u 50`, `-u 100`. Le seuil utile est celui où le
p95 dépasse la cible de latence ou où des erreurs apparaissent.

Interface web (courbes en direct) :

```bash
.venv/Scripts/python.exe -m locust -f tests/load/locustfile.py --host http://127.0.0.1:8100
# puis http://localhost:8089
```

## Interprétation

- `--run-time` démarre à l'initialisation du process, avant le premier
  utilisateur. Sur un run court (< 30 s), l'import de Locust (~2 s) et le login
  initial (~3 s, bcrypt cost 12) consomment une part visible du budget. Utiliser
  des paliers de **2 minutes minimum** pour des chiffres stables.
- La ligne `[setup] login` des rapports est l'amorce d'authentification, pas une
  mesure du service — l'ignorer dans les percentiles.
- Le premier appel sur un endpoint est plus lent (caches froids). Prévoir un
  palier de chauffe jeté avant la mesure de référence.
- `offer-mix` est connu comme le point lent (~318 ms de recalcul à chaque
  affichage, cf. commentaire dans `api/v1/dashboard.py`) : c'est le premier
  endroit où regarder si le p95 global dérive.

## Périmètre

Uniquement des `GET`. Les `POST .../analysis` sont exclus : ils appellent le LLM
(coût réel en tokens) et sont figés par un cache journalier, donc ils
mesureraient le cache plutôt que le service.

Les données ne sont pas modifiées par ce test — aucune écriture, hormis la mise
à jour de `last_login` du compte de test par le login initial.
