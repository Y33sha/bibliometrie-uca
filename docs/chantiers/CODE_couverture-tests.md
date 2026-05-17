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

Une fois (1) appliqué, recalculer le `fail_under`. Mesures :

- Post-Phase 1 : 75.65 % (1582 tests). `fail_under` 70 → 75.
- Post-Phase 2 : 77.09 % (1678 tests). `fail_under` 75 → 77.

Le palier 80 % n'est pas franchi par Phase 1+2. Phase 3 (`base.py`, éventuellement `auth.py`) et la couverture d'autres poches diffuses (orchestrateurs pipeline, helpers) sont nécessaires pour atteindre 80.

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

### Phase 2 — Couvrir les routers sous 70 %

Tests d'intégration FastAPI (`TestClient`) sur les routers dont la couverture initiale est sous 70 %. Critère unique = pourcentage de couverture ; le nom du module (`admin_*` ou pas) n'est pas un discriminant — le nommage est incohérent côté code (`journals`, `perimeters`, `subjects` portent des opérations admin sans préfixe `admin_`). À rationaliser dans un sous-dossier `routers/admin/` après le chantier tests.

- [x] `interfaces/api/routers/admin_pipeline.py` (32 → 100 %)
- [x] `interfaces/api/routers/admin_duplicates.py` (43 → 100 %)
- [x] `interfaces/api/routers/journals.py` (48 → 100 %)
- [x] `interfaces/api/routers/perimeters.py` (50 → 100 %)
- [x] `interfaces/api/routers/subjects.py` (50 → 100 %)
- [x] `interfaces/api/routers/admin_person_duplicates.py` (59 → 100 %)
- [x] `interfaces/api/routers/hal_problems.py` (63 → 100 %)
- [x] `interfaces/api/routers/docs.py` (22 %) — **abandonné** : router court, éphémère (Laura prévoit de le réécrire) ; pas de ROI sur les tests.
- [x] Couverture post-Phase 2 mesurée : 77.09 % (1678 tests). `fail_under` bumpé `75 → 77`. Le palier 80 % n'est pas franchi par Phase 1+2 — Phase 3 + autres poches diffuses nécessaires.

### Phase 3 — Couvrir les autres poches sous-couvertes

Mesure détaillée post-Phase 2 (`coverage report --include="application/pipeline/*" --sort=cover`) : 5 orchestrateurs pipeline à 0 % et 3 sous 20 %. C'est la principale poche restante pour franchir 80 %. Phase 3 enrichie en conséquence ; estimation d'impact = `stmts × (1 - cov)`.

**3a — Orchestrateurs pipeline à 0 %** (gain le plus massif)

- [x] `application/pipeline/normalize/normalize_crossref.py` (181 stmts, 0 %) — orchestrateur normalize source Crossref ; semble totalement non testé, à confirmer.
- [ ] `application/pipeline/enrich/enrich_journal_apc.py` (107 stmts, 0 %) — enrichissement APC via DOAJ + OpenAlex sources. Demande des mocks `respx`.
- [ ] `application/pipeline/enrich/enrich_oa_status.py` (68 stmts, 0 %) — enrichissement OA via Unpaywall. Demande des mocks `respx`.
- [x] `application/pipeline/countries/refresh_publication_countries.py` (20 stmts, 0 %) — petit script SQL, test d'intégration trivial.
- [x] `application/pipeline/publications/merge_pubs_by_nnt.py` (26 stmts → 100 %)

**3b — Orchestrateurs pipeline sous 20 %**

- [ ] `application/pipeline/publications/match_or_create_publications.py` (119 stmts, 17 %) — cœur du pipeline publications, sous-testé pour son poids.
- [ ] `application/pipeline/publications/merge_by_key.py` (41 stmts, 13 %) — helper de merge ; probablement couvert indirectement par `merge_pubs_by_hal_id` mais à expliciter.
- [ ] `application/pipeline/persons/populate_person_name_forms.py` (28 stmts, 17 %) — orchestrateur des formes de noms personnes.

**3c — Helpers et routeur suspendu**

- [ ] `infrastructure/sources/base.py` (38 %) — helpers de retry / pagination, tests unitaires sans I/O réseau. Quick-win technique distinct.
- [ ] `interfaces/api/routers/auth.py` (56 %) — dépend de la décision DSI sur le remplacement du JWT par CAS. À traiter une fois la doctrine d'auth tranchée.

**3d — Normalizers à compléter** (optionnel selon palier atteint après 3a+3b)

Tous partiellement couverts par les tests d'idempotence existants ; il reste les branches edge.

- [ ] `application/pipeline/normalize/normalize_wos.py` (312 stmts, 47 %) — gros volume, beaucoup à gagner.
- [ ] `application/pipeline/affiliations/resolve_addresses.py` (105, 49 %).
- [x] `application/pipeline/publications/merge_pubs_by_hal_id.py` (70 stmts → 100 %)
- [ ] `application/pipeline/normalize/normalize_theses.py` (107, 52 %).
- [ ] `application/pipeline/normalize/normalize_openalex.py` (221, 57 %).
- [ ] `application/pipeline/normalize/base.py` (116, 68 %).
- [ ] `application/pipeline/normalize/normalize_hal.py` (296, 71 %).

## Questions ouvertes

- **Fonction de coût de l'aiguillage HAL `extract_collection`.** Une fois la branche choisie pinée par test (Phase 1, décision 1bis), l'heuristique actuelle (`len(orphans) < full_fetch_pages`) reste insatisfaisante : elle compte les requêtes mais ignore la taille de payload, ce qui sur les requêtes umbrella (PRES_UCA) inverse le bon choix. Pistes à arbitrer : (a) borne dure sur les orphelins (« si `orphans < N`, toujours individuel »), (b) cost function pondérée payload (poids par source via `hal_per_page_for`), (c) compteur empirique sur les derniers runs. Décision distincte de l'extraction `parsing.py`, à ouvrir une fois les tests posés.
- **Snapshot des réponses API.** Si on veut une garantie sur le format des réponses (champ renommé côté API source détecté avant le run), on peut ajouter quelques tests `respx` ciblés (1-2 par source) marqués `@pytest.mark.snapshot` et exclus du `pytest tests/` par défaut. À discuter si une régression d'API arrive en prod et qu'on veut un filet.
- **Router `docs` retiré ou conservé ?** Le frontend actuel disparaît à la transmission. Si la doc consultable côté admin est jugée Laura-only (et donc retirée avec le frontend), ne pas couvrir. Sinon, la DSI réécrira un router équivalent et nos tests serviront de spec — à inclure.
- **Tests d'auth** : conditionner à la décision DSI sur le remplacement du JWT actuel par CAS. Tant que ce n'est pas tranché, laisser auth.py à 56 % sans investir.
