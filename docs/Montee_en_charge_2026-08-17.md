# Montée en charge — campagne du 17 août 2026

Campagne de paliers Locust sur les endpoints de lecture `/v1/dashboard/*`,
selon le protocole de `backend/tests/load/README.md`.

## Conditions

- Poste de travail Windows (pas le VPS de production — les chiffres absolus
  peuvent différer, la forme de la courbe est représentative).
- Backend uvicorn `--workers 2` sur le port 8100, conforme au Dockerfile.
- Compte de test jetable (rôle admin), supprimé après la campagne.
- Palier de chauffe de 60 s jeté (caches froids), puis paliers de 2 minutes.
- Ligne `[setup] login` exclue des statistiques (amorce, pas une mesure).

## Résultats par palier

| Utilisateurs | Requêtes | Erreurs | Médiane | p95 | Max | Débit |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 545 | 0 | 82 ms | 580 ms | 1,5 s | 4,6 req/s |
| 25 | 1 292 | 0 | 130 ms | 790 ms | 2,0 s | 10,9 req/s |
| 50 | 2 516 | 0 | 180 ms | 1 100 ms | 2,6 s | 21,1 req/s |
| 60 | 2 009 | 0 | 520 ms | 4 500 ms | 41 s | 16,9 req/s |
| 75 | 2 240 | 0 | 780 ms | 4 500 ms | 15,3 s | 16,2 req/s |
| 100 | 1 888 | 0 | 1 300 ms | 11 000 ms | 59 s | 15,9 req/s |

## Lecture

- **Point de rupture : entre 50 et 60 utilisateurs simultanés.** Jusqu'à 50,
  le débit croît avec la charge (4,6 → 21,1 req/s) et le p95 reste ≈ 1 s.
  À 60, le débit **chute** (16,9 req/s) et le p95 est multiplié par 4 :
  le backend n'absorbe plus, il empile.
- **Le service ne « plante » jamais** : zéro erreur HTTP sur les 10 490
  requêtes de la campagne, `/health` répond à 200 même à 100 utilisateurs.
  La dégradation est une asphyxie de latence, pas un crash — à 100
  utilisateurs, l'écran d'accueil (`kpis`) répond en 4,9 s en médiane,
  `offer-mix` monte à 26 s en p95, `next-actions` à 59 s au pire.
- **Endpoints qui s'effondrent en premier** (à 100 utilisateurs) : `dso`
  (médiane 6,6 s), `offer-mix` (p95 26 s), `next-actions` (max 59 s),
  `kpis` (p95 7,6 s) — les agrégations Python pures, GIL oblige, sérialisent
  les 2 workers malgré le déport `_hors_boucle` (cf. `api/v1/dashboard.py`).

## Verdict

Capacité utile : **~50 utilisateurs simultanés** avec un p95 ≈ 1,1 s.
Au-delà de 60, l'application devient inutilisable (écrans à plusieurs
secondes) sans jamais renvoyer d'erreur.

Premier levier identifié de longue date : figer l'agrégat `offer-mix`
(recalculé à chaque affichage alors qu'il ne change qu'aux syncs Odoo),
sur le modèle du cache journalier des narrations.
