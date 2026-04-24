# TODO Claude

## Suite de la refonte `domain/pipeline_modes.py`

- **Docs à mettre à jour** (`monthly` → `full`, 3 modes au lieu de 4) :
  - `README.md` (exemples `--mode`)
  - `docs/exploitation.md` (tableau de planification cron, ligne "monthly")
  - `docs/pipeline.md` (description des modes)
  - `docs/guide-utilisateur.md` (mention "modes weekly et monthly")
- **Crons server-side** : vérifier que les tâches planifiées n'appellent plus
  `--mode monthly` (remplacer par `--mode full`).
- **Harmonisation `extract_theses.py`** : accepter `--mode` et `--year` comme
  les autres extracteurs, pour uniformiser le traitement et permettre un
  éventuel `weekly` theses si besoin un jour (absence actuelle non justifiée
  par la source).

## Suite du split `cross_imports` → `fetch_missing_hal_id` + `fetch_missing_doi`

La phase `cross_imports` a été éclatée en deux phases distinctes, et les 4
scripts `cross_import_<source>.py` ont été fusionnés en un dispatcher unique
`interfaces/cli/pipeline/fetch_missing_doi.py` + un adapter par source dans
`infrastructure/sources/<source>/fetch_missing_doi.py`.

- **Docs à mettre à jour** :
  - `docs/pipeline.md` (section "Phase 2 — cross_imports" à scinder en 2a et 2b,
    références aux 4 scripts `cross_import_<source>.py` qui n'existent plus).
  - `CONTRIBUTING.md` (section "cross_imports" et "Script autonome
    `infrastructure/sources/<source>/cross_import_<source>.py`" — obsolètes).
  - `ROADMAP.md` ligne 194-195 (liste des scripts de cross-import).
- **Backoff `not_found_at` sur DOI** : pour limiter la croissance du pool de
  DOI retentés à chaque run, stocker un `not_found_at TIMESTAMP` sur les DOI
  qu'une source n'a pas pu résoudre, et ne les réessayer qu'après N jours
  (30 ?). Chantier séparé.

## Suite de la suppression de `harvest_hal_identifiers`

ORCID/IdRef des auteurs HAL sont désormais extraits depuis le TEI
(`label_xml`) pendant la normalisation — la phase dédiée qui interrogeait
l'API `ref/author` n'existe plus. La clé `hal_ref_author` a été retirée
de `api_base_urls` (migration 007, `infrastructure/app_config.py`,
`infrastructure/db/seed.sql`). À vérifier côté docs :

- Références à l'API `ref/author` HAL ou à `harvest_hal_identifiers` à
  retirer de `docs/pipeline.md`, `docs/sources.md` et `README.md` si
  présentes.

## Background jobs pour les endpoints de propagation massive

Le fix no-op sur `review_structure_link` (commit 9376bbd) règle le cas
fréquent (confirmer une auto-détection = no-op sans propagation). Reste
le cas d'un **vrai changement** massif : rejeter l'UCA sur une adresse
à 67k source_authorships, ou batch sur plusieurs adresses populaires →
CTE longue + UPDATE massif → 504 timeout reverse-proxy.

Plan :
- Seuil (ex: `PROPAGATION_SYNC_THRESHOLD = 5000` authorships) : en
  dessous, propagation synchrone comme aujourd'hui.
- Au-dessus : `fastapi.BackgroundTasks` pour décorréler la réponse de
  la propagation. Le client reçoit 202 avec `{propagation_pending:
  True, authorship_count: N}`, la propagation tourne en arrière-plan
  avec sa propre connexion DB (ne pas réutiliser celle de la requête).
- Frontend : gérer le 202 → afficher "propagation en cours, ça peut
  prendre quelques minutes" + rafraîchir après un délai / polling.
- Limites de `fastapi.BackgroundTasks` : même process, pas persistant
  aux restarts. Si le risque est acceptable pour une utilisation admin
  (l'utilisatrice relance la mutation si besoin), on reste simple. Sinon,
  introduire un job queue (pg-boss like) — plus gros chantier.

Endpoints candidats (à vérifier) : `review_structure_link`,
`batch_review_structure_link`, `unassign_manual_structure`, puis les
endpoints pays `batch_set_country_by_ids` / `batch_set_country_by_filter`.

## Audit endpoints long-running

Lister les endpoints POST/PUT/PATCH qui peuvent franchir le timeout
reverse-proxy (60s classique) selon le volume. Priorité :
user-triggered (pas les scripts CLI). Candidats pressentis :

- `review_structure_link` / `batch_review_structure_link` /
  `unassign_manual_structure` (périmètre d'adresses populaires)
- `batch_set_country_by_ids` / `batch_set_country_by_filter` (pays
  sur beaucoup d'adresses)
- Endpoints merge de `admin/duplicates` (publications / persons)
- `orphan-authorships/assign` (création de personne + rattachement)

Livrable audit : tableau par endpoint avec volume max observable,
temps moyen, temps P99, décision (sync / seuil + bg task / toujours
bg task).

## Audit "sync I/O dans les coroutines"

Distinct du précédent. Chercher les endpoints `async def` qui
appellent des fonctions faisant du `requests.get(...)` ou des
opérations psycopg2/psycopg en mode blocking sans `await` — ça
bloque l'event loop et ruine la concurrence de **tous les clients**.

Heuristique de recherche :
- Rechercher `def ` (pas `async def`) dans les routers/services qui
  font des appels HTTP ou DB
- Vérifier les imports `requests` et `psycopg` non-async dans le flow
  d'un endpoint
- Potentiellement instrumenter avec un handler qui trace les
  coroutines dépassant un seuil de temps entre deux `await`.
