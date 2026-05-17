# Chantier — Couverture de tests : viser 80 %

Commencé le 2026-05-17

## Contexte

Seuil `fail_under` aujourd'hui = 70 % (`pyproject.toml`, `[tool.coverage.report]`). La couverture brute mesurée à la dernière campagne est **71 %** sur 11 920 lignes (cf. `python -m pytest tests/ --cov`). On veut pousser à **80 %** avant transmission DSI, sans écrire de tests pour le plaisir des tests : la cible est la valeur de garantie, pas le pourcentage.

Deux poches très en dessous de la moyenne, identifiées au dernier rapport :

1. **Extracteurs API** (`infrastructure/sources/*/extract_*.py`, `fetch_missing_doi.py`, `fetch_missing_hal_id.py`, `refetch_truncated.py`) — 14 % à 39 % selon les modules.
2. **Routers admin / annexes** sous les 60 % : `docs` (22 %), `admin_pipeline` (32 %), `admin_duplicates` (43 %), `journals` (48 %), `perimeters` (50 %), `subjects` (50 %), `auth` (56 %), `admin_person_duplicates` (59 %).

Le reste de la base (domain, application, queries, repositories, models Pydantic) est entre 84 % et 100 %.

## Décisions

### 1. Séparer pure functions et wiring HTTP dans les extracteurs

Les modules d'extraction (`infrastructure/sources/*/extract_*.py`, `fetch_missing_doi.py`, `fetch_missing_hal_id.py`, `refetch_truncated.py`) mélangent aujourd'hui logique testable (parsing JSON, décisions d'aiguillage, requêtes SQL paramétrées) et wiring HTTP (`httpx.get`, pagination, retry, sleep). On sépare :

- **`infrastructure/sources/<source>/parsing.py`** (nouveau) : pure functions (`extract_hal_id`, `extract_doi`, `build_query`, `build_params`, `compute_meta_hash`, ...), décisions d'aiguillage (`extract_collection` côté HAL : full-fetch vs incrémental), SQL paramétré (`tag_existing_with_collection`). Couvert par tests unitaires `tests/unit/infrastructure/sources/<source>/test_parsing.py`.
- **`infrastructure/sources/<source>/extract_<source>.py`** : ne garde que le wiring (subclass `SourceExtractor`, `fetch_page`, boucles de pagination, sleep). Exclu de la couverture via `[tool.coverage.run] omit`.

**Pourquoi.** L'argument "tests à faible ROI parce que le code change quand l'API change" tient pour le wiring HTTP (fixtures figées = illusion de couverture) mais ne s'applique pas aux pure functions ni aux décisions d'aiguillage : ce sont elles qui régressent silencieusement quand on touche au code sans rapport avec l'API. Les tests d'idempotence en aval (`tests/integration/pipeline/idempotence/`) partent d'un `raw_data` déjà obtenu — ils ne couvrent ni le parsing en amont, ni la décision full-vs-incrémental côté HAL.

Liste exhaustive des modules de wiring concernés par l'exclusion : cf. checklist Phase 1.

Les modules `infrastructure/sources/base.py` (38 %) et `infrastructure/sources/common.py` (86 %) **restent dans le scope** : ce sont des helpers partagés (retry, pagination, normalisation d'erreurs).

### 1bis. Documenter et tester l'aiguillage HAL `extract_collection`

Cas observé sur le dernier import (collection umbrella PRES_UCA) : 19 orphelins vs 12 pages full-fetch ; l'heuristique `len(orphans) < full_fetch_pages` a choisi 12 pages (500 docs/page) là où 19 fetchs individuels auraient été plus rapides en wall time. Le même set de champs (`HAL_FIELDS`, incluant `label_xml`) est demandé dans les deux modes, donc le coût par doc est équivalent — l'asymétrie tient seulement au facteur N (1 vs 500). La fonction de coût compte les appels HTTP mais ignore la taille agrégée du payload par appel.

Le passage par `parsing.py` est l'occasion de :

- Documenter l'intention de l'heuristique dans la docstring (ne pas re-full-fetch les collections umbrella après les collections labo qui ont déjà chargé la majorité des docs).
- Émettre un log explicite de la décision : `nb orphelins`, `nb pages full-fetch`, branche choisie, raison.
- Couvrir par test la branche choisie selon `(orphans, pages)` — fixe le comportement courant, permet de discuter ensuite d'un fix de la fonction de coût (cf. *Questions ouvertes*).

### 2. Couvrir les routers admin sous 70 %

Tests d'intégration FastAPI (`TestClient`), même pattern que les routers déjà à 100 % (`addresses`, `publishers`, `stats`, `structures`). Trois sous-objectifs :

- **Lecture** : endpoint répond 200 sur un état nominal.
- **Erreur** : 404 / 400 sur les cas explicites du router.
- **Effet de bord** : pour les POST/PUT/PATCH/DELETE, vérifier l'état base après l'appel.

Pas de mock sur l'infra DB : les tests d'intégration tournent contre `bibliometrie_test` (cf. `tests/integration/conftest.py`).

### 3. Cible chiffrée

Une fois (1) appliqué, recalculer le `fail_under`. Mesure post-Phase 1 : couverture totale **75.65 %** (1582 tests). `fail_under` bumpé `70 → 75`. La Phase 2 (routers admin sous 70 %) doit apporter le delta restant pour franchir 80 %.

Une fois le palier 80 % atteint, on suit la doctrine actuelle : seuil progressif jamais à la baisse.

## Phasage

### Phase 1 — Refacto extracteurs : pure functions séparées

- [x] **HAL** — `infrastructure/sources/hal/parsing.py` : `build_query`, `build_url`, `extract_hal_id`, `extract_doi`, `choose_extraction_mode`, `count_full_fetch_pages`. `extract_collection` (dans `extract_hal.py`) appelle désormais `choose_extraction_mode` et logge la décision (orphans/pages/branche). Wiring exclu : `extract_hal.py`, `fetch_missing_hal_id.py`, `fetch_missing_doi.py`.
- [x] **OpenAlex** — `infrastructure/sources/openalex/parsing.py` : `build_params`, `extract_openalex_id`, `extract_doi`, `compute_meta_hash`. `__init__.py` réduit à l'auth (`init_auth`, `auth_params`) + `SELECT_FIELDS` (cf. décision 1b). Wiring exclu : `extract_openalex.py`, `fetch_missing_doi.py`, `refetch_truncated.py`.
- [x] **ScanR** — `infrastructure/sources/scanr/parsing.py` : `build_query`, `extract_scanr_id`, `extract_doi`. Wiring exclu : `extract_scanr.py`, `fetch_missing_doi.py`.
- [x] **WoS** — `infrastructure/sources/wos/parsing.py` : `build_query`, `extract_ut`, `extract_doi`, `get_records`, `get_records_found`, `clean_doi_for_wos`. Mutualise la duplication `_extract_ut` / `_extract_doi` qui vivait à la fois dans `extract_wos.py` et `fetch_missing_doi.py`. Wiring exclu : `extract_wos.py`, `fetch_missing_doi.py`.
- [x] **Theses** — `infrastructure/sources/theses/parsing.py` : `build_query`, `extract_theses_id`, `extract_doi`, `resolve_statuses`. Wiring exclu : `extract_theses.py`.
- [x] **Crossref** — pas de `parsing.py` (rien d'extractible avec ROI). Wiring exclu : `fetch_missing_doi.py`.
- [x] Tests unitaires `tests/unit/infrastructure/sources/<source>/test_parsing.py` : HAL (26), OpenAlex (17), ScanR (12), WoS (27), Theses (15) — 97 tests verts.
- [x] HAL `choose_extraction_mode` couvert sur les 3 branches (skip / incremental / full), avec le cas PRES_UCA pinné en `full` et un cas mini-collection (42 docs, 1 orphelin) pinné en `full` — deux régressions à pinner avant de retravailler la fonction de coût.
- [x] Ajout des 12 fichiers de wiring à `[tool.coverage.run] omit` dans `pyproject.toml` (commentaire renvoyant vers cette fiche).
- [x] Couverture recalculée : 75.65 %. `fail_under` bumpé `70 → 75`.
- [x] Mise à jour `docs/architecture.md` (section Tests) et `README.md` (commande pytest cov) avec le nouveau seuil 75 %.

### Phase 2 — Routers admin sous 70 %

Par ordre de priorité (impact UI puis surface) :

- [ ] `interfaces/api/routers/admin_pipeline.py` (32 %) — endpoints de relance / consultation de runs. Pages `/admin/pipeline`.
- [ ] `interfaces/api/routers/admin_duplicates.py` (43 %) — gestion des doublons de publications. Page `/admin/duplicates`.
- [ ] `interfaces/api/routers/journals.py` (48 %) — CRUD journaux (mode admin).
- [ ] `interfaces/api/routers/perimeters.py` (50 %) — CRUD perimeters.
- [ ] `interfaces/api/routers/subjects.py` (50 %) — facettes / recherche subjects.
- [ ] `interfaces/api/routers/docs.py` (22 %) — *à arbitrer* : si le router est en passe d'être retiré ou réécrit DSI-side, ne pas y investir. Sinon, l'inclure en dernier.

### Phase 3 — Quick-wins ciblés

Optionnel si Phase 1+2 a déjà fait passer le seuil :

- [ ] `interfaces/api/routers/admin_person_duplicates.py` (59 %)
- [ ] `interfaces/api/routers/auth.py` (56 %) — dépend du contrat CAS final ; pas prioritaire avant que la doctrine d'auth soit tranchée par la DSI.
- [ ] `interfaces/api/routers/hal_problems.py` (63 %)
- [ ] `infrastructure/sources/base.py` (38 %) — helpers de retry / pagination, tests unitaires (pas d'I/O réseau).

## Questions ouvertes

- **Fonction de coût de l'aiguillage HAL `extract_collection`.** Une fois la branche choisie pinée par test (Phase 1, décision 1bis), l'heuristique actuelle (`len(orphans) < full_fetch_pages`) reste insatisfaisante : elle compte les requêtes mais ignore la taille de payload, ce qui sur les requêtes umbrella (PRES_UCA) inverse le bon choix. Pistes à arbitrer : (a) borne dure sur les orphelins (« si `orphans < N`, toujours individuel »), (b) cost function pondérée payload (poids par source via `hal_per_page_for`), (c) compteur empirique sur les derniers runs. Décision distincte de l'extraction `parsing.py`, à ouvrir une fois les tests posés.
- **Snapshot des réponses API.** Si on veut une garantie sur le format des réponses (champ renommé côté API source détecté avant le run), on peut ajouter quelques tests `respx` ciblés (1-2 par source) marqués `@pytest.mark.snapshot` et exclus du `pytest tests/` par défaut. À discuter si une régression d'API arrive en prod et qu'on veut un filet.
- **Router `docs` retiré ou conservé ?** Le frontend actuel disparaît à la transmission. Si la doc consultable côté admin est jugée Laura-only (et donc retirée avec le frontend), ne pas couvrir. Sinon, la DSI réécrira un router équivalent et nos tests serviront de spec — à inclure.
- **Tests d'auth** : conditionner à la décision DSI sur le remplacement du JWT actuel par CAS. Tant que ce n'est pas tranché, laisser auth.py à 56 % sans investir.
