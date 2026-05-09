# Chantier — Convergence sync/async (suppression de la duplication)

## État : à instruire

Décision actée (option **D** ci-dessous), implémentation à dérouler
quand le chantier sera lancé. Estimation : 2-4 jours répartis,
migration progressive 1 router à la fois.

## Contexte

L'API FastAPI et le pipeline maintiennent **deux familles de
repositories quasi identiques** : variantes sync (utilisées par le
pipeline et les CLI) et variantes async (utilisées par les routes
FastAPI). Pour le seul agrégat `Person`, la duplication représente
~1425 lignes (sync 743 + async 682).

7 agrégats × 2 variantes = 14 fichiers de repositories qui
parallèlent presque ligne pour ligne. Tout ajout de méthode ou
modification de signature doit être fait dans les deux variantes,
avec un risque de drift silencieux.

L'origine historique est une migration FastAPI sync → async (ancien
chantier §2.12) appliquée par réflexe « FastAPI moderne = async » sans
interroger le profil d'usage réel de l'application.

## Cadrage du besoin réel

L'API actuelle (`interfaces/api/`) sert :
- aujourd'hui : Laura, utilisatrice unique, depuis le frontend admin
  (~1 utilisateur concurrent)
- à terme proche : quelques admins UCA pour la curation
- à terme long (~1 an) : reprise par la DSI qui réécrira
  probablement sa propre API publique en surcouche. L'API actuelle
  reste alors **outil de gestion interne** (quelques utilisateurs
  concurrents max)

Volume de concurrence anticipé : **inférieur à 10 requêtes
simultanées en pic**. Largement dans le domaine du threadpool sync.

Streaming temps réel (logs pipeline en direct, notifs push) :
intéressant à terme mais **non prioritaire**.

Opérations longues (attribution pays par batch, propagation massive)
: à traiter via **background jobs** (chantier déjà identifié dans
TODO_CLAUDE), problème **orthogonal** au choix sync/async.

## Options évaluées

### Option A — Tout async (le pipeline aussi)

Migrer le pipeline entièrement en async (`asyncio.run()` au top
level, `await` partout, conversion des ~50 fichiers sync vers
async).

- **Pour** : une seule famille de code, cohérence avec FastAPI.
- **Contre** : chantier **énorme et risqué** (pipeline en prod,
  régressions probables), pour zéro bénéfice fonctionnel (pipeline
  séquentiel par nature).

**Écartée** : coût/bénéfice catastrophique pour un pipeline batch
mono-thread.

### Option B — Codegen ou abstraction générique

Écrire une seule définition de chaque repository, générer les deux
variantes via codegen ou via une abstraction qui paramètre `await`.

- **Pour** : single source of truth, garde les deux modes.
- **Contre** :
  - Pas de framework standard Python pour ce codegen → outillage maison
    à maintenir
  - Le code lu (template) ≠ le code exécuté (généré) → debugging
    complique
  - Variante « abstraction » quasi impossible en Python parce que
    `await` n'est pas un opérateur conditionnel

**Écartée** : ajoute de la complexité d'outillage pour résoudre un
problème qui peut être résolu en supprimant simplement une moitié.

### Option C — Statu quo + test de parallélisme

Garder les deux familles, ajouter un test qui vérifie la parité
sync/async.

- **Pour** : aucun coût de migration.
- **Contre** : ne résout rien, accumule la dette, le test ne fait
  que constater la duplication.

**Écartée** : Laura veut résoudre la dette, pas la documenter.

### Option D — Tout sync, FastAPI exécute les routes en threadpool *(retenue)*

FastAPI accepte indifféremment `def route(...)` et `async def
route(...)`. Les routes `def` sont exécutées dans un threadpool
Starlette (~40 workers par défaut). Conséquences :

- Toutes les routes deviennent `def` (sans `await`)
- Les ~14 fichiers `async_*_repository.py` sont supprimés
- Les routes utilisent les **mêmes** repositories sync que le pipeline
- Le pool DB async (`build_async_pool`) est supprimé, on garde
  uniquement le pool sync
- Les middlewares actuellement `async def` (auth, timing) peuvent
  rester tels quels — FastAPI s'en arrange

**Pour** :
- Une seule famille de repositories, plus de drift possible
- Suppression nette de code (~14 fichiers + variantes Person + pool
  async + dépendances `async_deps.py`)
- Migration **incrémentale** (1 router à la fois, pas de big bang)
- Risque de régression faible (suppression de code, pas réécriture)
- Simplifie le mental model : un seul cursor, un seul style

**Contre** :
- Perte théorique de la concurrence asyncio « pure » (event loop)
- Plafond de concurrence ~40 requêtes simultanées (taille du
  threadpool Starlette par défaut, ajustable)
- Si streaming/SSE est introduit plus tard, il faudra repasser ces
  endpoints précis en `async def` (cohabitation possible)

## Décision retenue : D

Pour les raisons suivantes :

1. **Volume de concurrence anticipé largement inférieur au plafond
   threadpool** : 5-10 simultanés vs ~40 dispo. Aucun risque de
   saturation pratique.
2. **Pas de besoin actuel ou planifié de streaming temps réel**.
3. **Opérations longues seront gérées par background jobs**, pas
   par async (problème orthogonal).
4. **API actuelle restera probablement interne** après reprise DSI
   (qui fera sa propre API publique).
5. **Réversibilité** : si une route précise a un jour besoin
   d'async (streaming SSE par exemple), on la repasse en `async def`
   sans toucher au reste. La cohabitation est supportée par
   FastAPI.

## Plan d'implémentation

### Phase 1 — Préparation (non destructif)

- [x] Bumper `db_pool_max` dans `.env.example` et la doc à 30
  (audit-cto Phase 3, commit `1275236`). Préparation du pool sync
  à absorber la concurrence threadpool.
- [x] Vérifier qu'aucune route async actuelle n'utilise un pattern
  `async def` fonctionnellement obligatoire. Audit fait :
  - **1 route async-only identifiée** : `admin_feedback.py:140`
    `feedback_rerun` — endpoint SSE qui streame stdout d'un
    subprocess (`asyncio.create_subprocess_exec` +
    `StreamingResponse text/event-stream`). Reste légitimement
    en `async def` (cohabitation FastAPI). N'utilise **aucune
    connexion DB** → pas de blocker pour la suppression de l'infra
    async DB.
  - **2 routes utilisent `BackgroundTasks`** (`addresses.py`
    `set_address_country` / `batch_set_country`) : compatible avec
    routes sync, FastAPI exécute les tasks dans un thread peu
    importe la nature de la route.
  - **Aucun WebSocket, long-polling, autre pattern bloquant.**
- [x] Recenser les middlewares `async def` actuels — 3 middlewares
  `@app.middleware("http")` dans `interfaces/api/app.py` :
  `auth_middleware` (l. 151), `strip_prefix` (l. 196),
  `timing_middleware` (l. 208). Plus `lifespan` (l. 72) et 6
  exception handlers async. Tous peuvent rester async : FastAPI/
  Starlette gèrent l'orchestration indépendamment de la nature
  (sync/async) des routes elles-mêmes.

### Phase 1.5 — Préparation Phase 2 : infra sync côté API

Avant de migrer le premier router, poser les briques DB sync utilisables
depuis les `Depends` FastAPI :

- [x] `interfaces/api/deps.py` : ajouter `db_conn_sync()` qui yield un
  `Connection` SA sync ouvert via `engine.begin()` (commit/rollback
  auto). Pendant la migration, cohabite avec `db_conn` (async) côté
  `async_deps.py`.
- [x] `interfaces/api/app.py` lifespan : instancier le sync Engine SA
  via `build_sync_engine()` + `set_sync_engine()`, dispose au shutdown.
  Les trois (pool psycopg async, AsyncEngine SA, Engine SA sync)
  cohabitent ; Phase 3 supprime les deux premiers.

Pas besoin d'un pool psycopg sync séparé : on bascule directement
les routers vers SA Core (cohérent avec le travail SQLA Lot 3.A
sur les repos sync, dispatch cur | Connection). Les routers
migrés utilisent `Connection` SA sync, pas un curseur psycopg.

### Phase 2 — Migration progressive, 1 router à la fois

Pour chaque router dans `interfaces/api/routers/` :

1. Si le port async (`AsyncXxxQueries`) n'a pas d'équivalent sync :
   ajouter un Protocol sync `XxxAdminQueries` dans
   `application/ports/xxx_queries.py` (à côté de l'async).
2. Si l'adapter sync n'existe pas dans `infrastructure/db/queries/xxx.py` :
   ajouter une classe `PgXxxAdminQueries` (Connection SA sync). Mêmes
   requêtes que la version async, juste sans `await`.
3. Ajouter une factory `xxx_admin_queries` dans
   `interfaces/api/deps.py` qui injecte `db_conn_sync`.
4. Convertir les routes du router : `async def` → `def`, retirer les
   `await`, remplacer la dépendance async par la sync.
5. Lancer la suite de tests d'intégration.
6. Vérifier manuellement le comportement dans le frontend (au moins
   en spot-check).
7. Commit séparé par router (rollback granulaire possible).

Routers déjà sync nativement (rien à migrer) : `auth.py`, `docs.py`.

Ordre suggéré : commencer par les petits (`subjects`, `config`, etc.)
puis les CRUD admin, puis les gros (`publications`, `persons`,
`laboratories`).

**Routers migrés** :
- [x] `subjects.py` — pilote (commit `6e9c8f8`). 2 routes, 1 nouveau
  Protocol `SubjectsAdminQueries`, 1 nouvelle classe
  `PgSubjectsAdminQueries`, 1 factory `subjects_admin_queries`.
  Sert de modèle pour les suivants.
- [x] `subjects.py`, `config.py` (auth.py et docs.py étaient déjà
  natifs sync). Pour config : ajout des Protocols sync `ConfigStore`
  (`application/ports/config.py`) et `ConfigQueries`
  (`application/ports/config_queries.py`), classes sync `PgConfig`
  et `PgConfigQueries` dans `infrastructure/db/queries/config.py`,
  factory `config_store` dans `infrastructure/repositories/__init__.py`,
  factories `config_queries_sync` / `config_store_sync` dans
  `interfaces/api/deps.py`. Le service `application/config.py:update_config_value`
  est passé en sync (suppression de la version async, le seul caller
  prod basculait en même temps). Helper `infrastructure/perimeter.py:get_perimeter_structure_ids`
  étendu en dispatch (cur | Connection) pour servir
  `PgConfigQueries.get_hal_collections`. 3 tests adaptés en sync.
- [x] `admin_pipeline.py` — déjà natif sync, rien à migrer.
- [x] `hal_problems.py` — Protocol sync `HalProblemsQueries`, classe
  sync `PgHalProblemsQueries`, factory `hal_problems_queries_sync`,
  6 routes `def`. Tests interfaces : 13/13 passent.
- [x] `admin_duplicates.py` (publications) — Protocol sync
  `PublicationDuplicatesQueries`, classe sync `PgPublicationDuplicatesQueries`,
  factory `publication_duplicates_queries_sync`. Services
  `application/publications.py`: `mark_distinct` migré en sync
  (suppression async), `async_merge_publications` supprimée
  (utilisait `merge_publications` sync existant côté CLI). 3 routes
  `def`, factories transverses ajoutées : `audit_repo_sync`,
  `publication_repo_sync`. 2 tests `TestMarkDistinct` migrés en sync ;
  `TestAsyncMergePublications` supprimé (couvert par `TestMergePublications`).
- [x] `admin_person_duplicates.py` — Protocol sync
  `PersonDuplicatesQueries`, classe sync `PgPersonDuplicatesQueries`,
  factory `person_duplicates_queries_sync`. Service
  `application/persons.py:mark_distinct` migré en sync (suppression
  async). 5 routes `def`, factories ajoutées : `person_repo_sync`,
  `person_duplicates_queries_sync`. 2 tests `TestMarkDistinctPersons`
  migrés en sync ; 1 test audit sync. Total Phase 2.2 : 36 tests
  ciblés passent.
- [x] `journals.py` — Protocol sync `JournalQueries`, classe sync
  `PgJournalQueries`, factory `journal_queries_sync`. Services
  `application/journals.py:update_journal` / `merge_journals` migrés en
  sync (suppression async). 4 routes `def`, factories ajoutées :
  `journal_repo_sync`. Tests `TestUpdateJournal`, `TestMergeJournals`
  migrés en sync.
- [x] `publishers.py` — Protocol sync `PublisherQueries`, classe sync
  `PgPublisherQueries`, factory `publisher_queries_sync`. Services
  `application/publishers.py:update_publisher` / `merge_publishers`
  migrés en sync (suppression async). 4 routes `def`, factories
  ajoutées : `publisher_repo_sync`. Tests `TestUpdatePublisher`,
  `TestMergePublishers` migrés en sync.
- [x] `laboratories.py` — Protocol sync `LaboratoriesQueries`, classe
  sync `PgLaboratoriesQueries` (~360 LOC, 6 méthodes incluant
  `get_laboratory_persons` avec ses facettes). Factory
  `laboratories_queries_sync`. 6 routes `def`. Helpers
  `infrastructure/perimeter.py:get_persons_perimeter_root_ids` et
  `get_persons_structure_ids_list` étendus en dispatch (cur | Connection)
  pour servir le sync.
- [x] `perimeters.py` — Protocol sync `PerimetersAdminQueries` ajouté
  à côté de `AsyncPerimetersAdminQueries`, classe sync
  `PgPerimetersAdminQueries`. Nouveau Protocol sync `PerimeterRepository`
  + adapter `PgPerimeterRepository` (l'agrégat n'avait que la variante
  async jusqu'ici). Services `application/config.py` (5 fonctions :
  `add_perimeter_structure`, `remove_perimeter_structure`,
  `create_perimeter`, `update_perimeter`, `delete_perimeter`) migrés
  en sync (suppression nette des variantes async). 6 routes `def`,
  factories ajoutées : `perimeter_repo_sync`,
  `perimeters_admin_queries_sync`. Tests `test_config_service.py`
  (20 tests) migrés en sync.
- [x] `admin_feedback.py` — Protocol sync `AdminFeedbackQueries`,
  classe sync `PgAdminFeedbackQueries`, factory
  `admin_feedback_queries_sync`. 4 routes `def` ; **`feedback_rerun`
  reste `async def`** (pilote un subprocess en streaming SSE,
  incompatible threadpool — cohabitation supportée). Tests
  `test_admin_feedback_api.py` (15 tests) restent inchangés.
- [x] **Conftest tests interfaces** : `tests/integration/interfaces/conftest.py`
  patche désormais `build_sync_engine` en plus de `build_async_engine`
  pour rediriger l'Engine SA sync vers `bibliometrie_test`. Sans ce
  patch, les routes sync écrivaient sur la base prod en test (cf. bug
  rencontré au premier run de `test_admin_feedback_api.py`).

Total Phase 2.3 : 5 routers migrés (journals, publishers, laboratories,
perimeters, admin_feedback hors SSE), 54 tests application + 50 tests
interfaces ciblés passent.
- [x] `stats.py` — Protocol sync `StatsQueries` ajouté à
  `application/ports/stats_queries.py`. Classe sync `PgStatsQueries`
  dans `infrastructure/db/queries/stats/__init__.py`. Les 4 sous-modules
  stats (publishers, journals, labs, summary) ont chacun gagné un
  `*_sync` à côté de l'async, factorisé via un helper `_build_*_sql`
  partagé. Factory `stats_queries_sync`, helper `get_root_structure_id_sync`
  (lookup process-cached, identique à la variante async). 7 routes `def`,
  15 tests interfaces passent.
- [x] `structures.py` — Nouveau Protocol sync `StructureRepository`
  + adapter `PgStructureRepository`. Protocol sync `StructuresQueries`
  + classe sync `PgStructuresQueries`. Service `application/structures.py`
  (5 fonctions : create/update/delete structure, create/delete relation,
  create/update/delete name_form) migré en sync (suppression nette des
  variantes async, single caller pattern). 9 routes `def`, factories
  ajoutées : `structure_repo_sync`, `structures_queries_sync`. Tests
  `test_structures_service.py` (23 tests) migrés en sync. Tests interfaces
  `test_structures_api.py` : 32 tests inchangés passent.
- [x] `publications.py` — Migration en swap net (single API caller) :
  les 4 modules de query async (`list.py`, `facets.py`, `detail.py`,
  `__init__.py`) sont **convertis sur place** vers sync (suppression
  des variantes async, plus de cohabitation sur ce port). Protocol
  port renommé `PublicationsQueries` (sync). `facets.py` perd son
  `asyncio.gather` parallèle au profit d'une exécution séquentielle
  sur la même Connection (le router tourne déjà dans un thread Starlette ;
  pas de bénéfice à paralléliser des requêtes courtes contre la même
  base). Nouveau Protocol sync `AuthorshipRepository` + adapter
  `PgAuthorshipRepository` (utilisé pour le seul use case applicatif
  du router : `set_source_authorship_excluded_sync`). Tests
  `test_publications_list.py` (7), `test_publications_detail.py` (11),
  et `test_publications_api.py` (26) : 44 tests passent. Service
  `application/authorships.py` cohabite sync/async pendant que le reste
  des routers (persons, addresses) finit la migration.
- [x] `addresses.py` (batch 2a) — Migration en swap net (single API caller) :
  `infrastructure/db/queries/addresses.py` converti sur place vers sync
  (suppression `PgAsyncAddressesQueries`, port renommé `AddressesQueries`).
  Nouveau Protocol sync `AddressRepository` + adapter `PgAddressRepository`.
  Services `application/addresses_countries.py` et
  `application/addresses_structures.py` (8 fonctions au total) migrés en
  sync (suppression nette, single caller). 5 fonctions sync ajoutées à
  `application/authorships.py` à côté des async (cohabitation pour
  `exclude_authorship`, `delete_orphan_authorships` qui restent appelés
  depuis `application/persons.py` async, jusqu'à batch 2b) :
  `propagate_uca_for_addresses_sync`, `set_source_authorship_excluded_sync`,
  `detach_source_sync`, `exclude_authorship_sync`,
  `delete_orphan_authorships_sync`. 12 routes `def`. `bg_propagate_countries_sync`
  ajouté à `interfaces/api/deps.py` (utilise un sync engine.begin() short-lived
  pour les BackgroundTasks). Singleton sync `_perimeter_queries_sync_singleton`
  via `get_perimeter_queries_sync`. Tests `test_addresses_service.py` (34),
  `test_authorships_service.py` (22), `test_addresses_queries.py` (16),
  `test_addresses_api.py` (45) : 117 tests passent.
- [x] `persons.py` (batch 2b) — Migration en swap net (single API caller) :
  les 5 modules de query async dans `infrastructure/db/queries/persons/`
  (`list.py`, `facets.py`, `detail.py`, `admin.py`, `__init__.py`) sont
  convertis sur place vers sync (suppression `PgAsyncPersonsQueries`, port
  renommé `PersonsQueries`). `application/persons.py` réécrit en sync : les
  9 fonctions API-only (`set_rejected`, `update_name`, `remove_identifier`,
  `update_identifier_status`, `reassign_identifier`, `detach_name_form`,
  `assign_orphan_authorship`, `batch_assign_orphan_authorships`,
  `detach_authorships`) passent de async à sync ; les 3 wrappers redondants
  (`async_create_person`, `async_add_identifier`, `async_merge_person`)
  sont supprimés (l'API utilise les versions sync existantes utilisées
  par le pipeline). 28 routes `def`, factory ajoutée :
  `persons_queries_sync`. `interfaces/api/async_deps.py` perd les imports
  `AsyncPersonsQueries` / `PgAsyncPersonsQueries` et la factory
  `persons_queries`. Tests : 113 ciblés passent (test_persons_service: 36,
  test_persons_api: 77).

Total Phase 2.4 : 7 routers migrés (stats, structures, publications,
addresses, persons + admin_pipeline déjà sync). Tous les `async def` dans
`interfaces/api/routers/` ont été convertis en `def` (sauf le SSE
`feedback_rerun` qui reste async par nature). 202 tests application + 241
tests interfaces passent en suite isolée (chaque suite). Reste de la
cohabitation sync/async : `application/authorships.py` (variantes async
non utilisées en prod, supprimées en Phase 3), `infrastructure/repositories/async_*.py`
(16 fichiers), `interfaces/api/async_deps.py`. Phase 3 supprime tout
ce code mort.

### Phase 3 — Suppression du code async devenu mort

Une fois tous les routers migrés :

- [ ] Supprimer les 8 fichiers `infrastructure/repositories/async_*.py`
  (et le sous-package `async_person_repository/`)
- [ ] Supprimer les factories `async_*_repository` dans
  `infrastructure/repositories/__init__.py`
- [ ] Supprimer les classes `Async*Repository` dans `domain/ports/*`
- [ ] Supprimer `infrastructure/db/async_connection.py` et le
  lifespan async de `interfaces/api/app.py`
- [ ] Supprimer `interfaces/api/async_deps.py`
- [ ] Supprimer les query services async dans
  `infrastructure/db/queries/` (renvoyer toutes les routes vers les
  variantes sync)
- [ ] Retirer `pytest-asyncio` de `pyproject.toml` (sauf si encore
  utile pour des tests pipeline async ponctuels comme
  `fetch_missing_doi`)
- [ ] Retirer `psycopg-pool` async path s'il n'est plus utilisé

### Phase 4 — Doc

- [ ] Mettre à jour `docs/architecture.md` (section "Patterns
  d'injection") : retirer la mention de la cohabitation sync/async,
  expliquer que l'API utilise les mêmes repositories que le pipeline,
  via threadpool.
- [ ] Documenter la valeur de `db_pool_max` recommandée et le
  raisonnement (concurrence threadpool × marge).
- [ ] Mettre à jour `infrastructure/repositories/__init__.py`
  docstring (plus de mention sync/async).

## Points de vigilance

- **Pool DB sous-dimensionné** : avec un threadpool à 40 workers et un
  pool DB à `max=10`, certaines requêtes attendront leur tour.
  Bumper le pool DB **avant** la migration pour éviter une dégradation
  perceptible.
- **Tests d'intégration asyncio** : les fixtures `async_db` et les
  tests `async def test_*` doivent être convertis ou supprimés au fur
  et à mesure de la migration des routers concernés.
- **Pipeline d'extraction async restant** : `fetch_missing_doi.run_async`
  utilise httpx + asyncio.Semaphore pour saturer les rate-limits
  d'API. Ce code reste async et n'est pas concerné par le chantier
  (c'est de l'async « ponctuel » dans un contexte sync via
  `asyncio.run()`).
- **Audit logging via ContextVar** : l'audit log utilise
  `contextvars` pour propager le user courant. Les ContextVar sont
  thread-safe et fonctionnent identiquement en async et en threadpool
  (chaque requête a son contexte). Pas de modification nécessaire.

## Réversibilité

Forte. À tout moment, on peut :
- Repasser une route en `async def` si un besoin spécifique émerge
  (ex : SSE pour les logs pipeline).
- Recréer un repository async pour un agrégat précis si nécessaire.
- Cohabiter sync et async dans la même API sans friction.

La décision n'est pas un point de non-retour.

## Lien avec d'autres chantiers

- **Background jobs** (TODO_CLAUDE) : indépendant, mais
  complémentaire. Une fois D fait, les background jobs seront plus
  simples à implémenter (pas de double pattern à supporter).
- **Pipeline subprocess vs imports** : indépendant (chantier
  pipeline isolé du choix API).
- **Réécriture doc Phase 4 audit-cto** : intègrera la nouvelle
  architecture sans la couche async.
