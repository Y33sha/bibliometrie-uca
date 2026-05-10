# Chantier — Adoption SQLAlchemy Core
Commencé le 2026-05-06.

## Contexte

Le projet utilise psycopg3 directement, avec deux familles de
constructions SQL :

- **Queries statiques** : la majorité (~80 %). Ex.
  `cur.execute("SELECT id FROM persons WHERE id = %s", (id_,))`.
  Lisibles, paramétrées, sans bug connu.
- **Queries dynamiques** : `infrastructure/db/queries/filters.py`,
  `infrastructure/db/queries/publications/facets.py`
  (`_PublicationFacetsBuilder`, ~500 lignes), listings paginés avec
  filtres variables (`addresses`, `persons/list.py`,
  `publications/list.py`). Pattern actuel : muter une `conditions:
  list[str]` et une `params: list` en parallèle, puis assembler la
  requête finale.

Ce pattern « muter deux listes en parallèle » est un mini-framework
maison déguisé. Il marche mais introduit une classe d'erreurs
runtime (désalignement string ↔ params) et n'est pas composable :
chaque builder est ad hoc. ROADMAP §1.4 anticipait précisément ce
piège.

SQLAlchemy Core remplace ce pattern par le standard de l'écosystème
Python, sans rien renvoyer côté ORM.

## Décision retenue

**Adopter SQLAlchemy Core** (pas l'ORM) comme query builder de
référence pour les queries dynamiques, en coexistence pragmatique
avec du SQL brut là où c'est plus lisible (CTE complexes, opérations
JSON spécifiques à PostgreSQL).

## Périmètre du chantier

**Inclus** :
- Toutes les queries dynamiques (`filters.py`, `*facets.py`,
  listings paginés).
- Repositories (`infrastructure/repositories/*.py`) : les méthodes
  d'écriture comme `update_*_fields` (déjà `dict`-based depuis le
  chantier ports-cleanup) deviennent `update(t).values(**fields)`.
- Pool de connexions : remplacer `AsyncConnectionPool` psycopg par
  `AsyncEngine` SQLAlchemy (driver psycopg3 conservé sous le
  capot — `postgresql+psycopg://`).

**Inclus mais à valider en phase 0** :
- Description des tables côté Python : MetaData explicite (pattern
  standard) vs reflection au démarrage. Recommandation initiale :
  MetaData explicite, déclarée dans `infrastructure/db/tables.py`,
  cohérent avec `schema.sql`. Synchronisation par revue manuelle à
  chaque migration (peu fréquent).

**Exclus** :
- ORM SQLAlchemy (mappers, sessions identity-map, `relationship()`,
  lazy loading). Hors scope. Le domaine reste pur (value objects
  dans `domain/`), aucun mapping objet-table.
- Migrations Alembic — décision séparée, voir section dédiée.
- `infrastructure/db/migrate.py` — reste tel quel (141 lignes
  lisibles, aucune raison de toucher).
- `interfaces/cli/` — les scripts one-shot continuent d'utiliser
  les repos via les factories ; pas de réécriture spécifique.

## Décisions de cadrage

### 1. Engine de bout en bout, pas builder pur

Deux options :
- **A** — SQLAlchemy uniquement comme générateur de string SQL ;
  on continue à exécuter via `cur.execute(str_sql, params)`.
- **B** *(retenu)* — SQLAlchemy `AsyncEngine` + `AsyncConnection`
  remplace le pool psycopg. `await conn.execute(stmt)` partout.

Raisonnement : en partant de zéro, B est le pattern standard. Il
ouvre proprement la voie à Alembic (qui s'attend à un Engine), il
unifie le typage des Result et il évite un mode hybride bancal. Le
driver reste psycopg3 (`postgresql+psycopg://`), donc aucune
régression de perf/feature côté DB.

**Cohérence transactionnelle pendant la migration incrémentale** :
le risque qu'un module migré (en B) appelle un service ancien (en
psycopg cur) avec une connexion différente est traité en
sous-phase 1.0 (audit en cohabitation : `async_emit_event` accepte
les deux signatures via dispatch interne). Cohabitation transitoire
jusqu'en Phase 4, où la branche psycopg disparaît. Aucune fenêtre
d'indisponibilité côté API admin pendant le chantier.

### 2. Coexistence Core / SQL brut

Règle : **Core par défaut, SQL brut quand il est strictement plus
lisible**. Critères concrets pour basculer en SQL brut :

- CTE imbriquées (`WITH RECURSIVE …` notamment) — déjà présentes
  dans `infrastructure/perimeter.py`.
- Opérations JSON PostgreSQL avancées (`->`, `->>`, `#>>`,
  `jsonb_set`, etc.) — déjà présentes dans `subjects.py`,
  `staging`, etc.
- Window functions complexes (`ROW_NUMBER() OVER (PARTITION BY …)`).

Dans tous les cas, l'exécution passe par
`AsyncConnection.execute(text(sql), params)` (bind paramétré),
jamais par interpolation string.

### 3. Description des tables (MetaData) — explicite vs reflection

Pour construire une requête, SQLAlchemy a besoin de connaître la
structure des tables (noms de colonnes, types, contraintes). Sans
ça, `select(perimeters.c.code).where(perimeters.c.id == 5)` ne sait
pas quelle colonne `code` désigne ni si elle existe. Cette
description s'appelle la **MetaData** et il y a deux façons de la
fournir :

**Option a — MetaData explicite** : on déclare en Python la
structure de chaque table dans un fichier `infrastructure/db/tables.py` :

```python
from sqlalchemy import MetaData, Table, Column, Integer, String, ARRAY

metadata = MetaData()

perimeters = Table(
    "perimeters", metadata,
    Column("id", Integer, primary_key=True),
    Column("code", String, nullable=False, unique=True),
    Column("name", String, nullable=False),
    Column("description", String),
    Column("structure_ids", ARRAY(Integer), nullable=False),
)
```

Ensuite dans les queries : `select(perimeters.c.code).where(perimeters.c.id == 5)`.

- Avantages : autocomplete IDE (`perimeters.c.` propose les colonnes),
  erreur statique si on tape une colonne inexistante, pas de coût au
  démarrage, lecture claire (un seul fichier liste toutes les tables).
- Inconvénient : duplication. Le schéma vit à la fois dans
  `schema.sql` (source réelle, alimentée par les migrations) et
  dans `tables.py` (copie Python). Si on ajoute une colonne via
  migration sans toucher `tables.py`, le code ne la voit pas.

**Option b — Reflection** : on dit à SQLAlchemy d'aller interroger
la base au démarrage pour découvrir le schéma :

```python
metadata = MetaData()
metadata.reflect(bind=engine)
perimeters = metadata.tables["perimeters"]
```

- Avantages : pas de duplication, toujours synchro avec la DB.
- Inconvénients : couplage runtime (impossible d'exécuter le code
  sans accès DB, gênant pour les tests unitaires), pas
  d'autocomplete IDE (les colonnes ne sont connues qu'au runtime),
  coût léger au démarrage de l'app.

Note importante : la MetaData décrit la **structure des tables**
(quelles colonnes existent), pas la façon dont SQLAlchemy convertit
les valeurs Python ↔ SQL — cette conversion est gérée
automatiquement par les types SQLAlchemy (`Integer`, `String`,
`ARRAY(Integer)`, etc.). Les deux concepts sont déclarés ensemble
dans `Table(...)` mais sont conceptuellement distincts.

**Recommandation initiale : option a (MetaData explicite)**.

Raisons :
- Autocomplete IDE et typage statique sont des gains réels au
  quotidien.
- Permet de tester du code sans DB (utile pour mypy / introspection).
- Le risque de drift est mitigé par : (1) un test d'intégration
  qui compare la MetaData à la DB réelle et alerte si divergence,
  (2) les migrations sont peu fréquentes (~1/mois).
- Naturel si on décide ensuite d'adopter Alembic
  (`alembic --autogenerate` lit la MetaData explicite pour
  proposer le diff de migration ; en reflection, ce gain disparaît).

À confirmer en phase 0 sur le module pilote — si l'écriture
manuelle de la MetaData s'avère trop lourde dans la pratique,
fallback vers reflection.

### 4. Le domaine reste pur

`domain/` ne connaît pas SQLAlchemy. Les value objects (`DOI`,
`ORCID`, `IdRef`, `StructureApiIds`, etc.) restent intacts. Les
ports (`domain/ports/*.py`, `application/ports/*.py`) restent des
`Protocol` sans dépendance externe.

SQLAlchemy vit exclusivement dans `infrastructure/`.

### 5. Pas de session ORM, pas d'unit of work

Pour les transactions, on reste sur le pattern actuel
(`AsyncConnection.begin()` / context manager). Pas d'introduction
de `Session.commit()` / `flush()`. Ce projet n'a pas la complexité
qui justifierait une session.

## Phasage proposé

### Phase 0 — Cadrage et POC

- [x] Ajouter `sqlalchemy==2.0.43` dans `pyproject.toml` et `uv sync`
- [x] Créer `infrastructure/db/engine.py` — AsyncEngine SA basé sur
  `postgresql+psycopg://`, paramètres pool alignés sur
  l'AsyncConnectionPool psycopg actuel. Pas branché au lifespan
  FastAPI à ce stade : cohabitera quand Phase 1 commencera.
- [x] Créer `infrastructure/db/tables.py` — MetaData avec 3 tables
  pilotes (`config`, `perimeters`, `structures`). Autres tables
  ajoutées au fur et à mesure.
- [x] POC `tests/integration/infrastructure/db/test_sqlalchemy_smoke.py`
  — INSERT/SELECT/UPDATE/RETURNING sur les 3 tables + 3 tests de
  cohérence MetaData ↔ schéma DB. 7/7 verts.
- [x] **Décision finale MetaData explicite vs reflection : explicite**
  (option a). Le test de cohérence MetaData/DB s'avère léger ; risque
  de drift gérable.
- [x] **Découverte : enums PostgreSQL** doivent être déclarés via
  `sqlalchemy.dialects.postgresql.ENUM(..., create_type=False)`. Si
  on les déclare en `Text`, Postgres rejette les INSERT car SA cast
  vers `VARCHAR` (et `VARCHAR ↛ enum_type` est interdit). Pattern à
  reproduire pour `doc_type`, `oa_status`, etc. en étendant la
  MetaData.
- [x] **Découverte : JSONB** est sérialisé automatiquement par SA
  (passer la valeur Python brute à `.values(...)`, ne pas faire de
  `json.dumps()` manuel comme le code legacy psycopg). À adapter
  dans `PgAsyncConfig.update_config_value` en Phase 1.
- [x] **Cohabitation pool psycopg / AsyncEngine SA validée** : les
  deux ouvrent leurs propres connexions sans conflit, ce qui permet
  une migration incrémentale.
- [x] **Décision option A vs B : option B retenue** (AsyncEngine de
  bout en bout). Tranchée à la sous-phase 2.1 sur le module config
  réel. Cohabitation avec `async_emit_event` résolue par dispatch
  interne (sous-phase 1.0).


### Phase 1 — Migration des queries dynamiques

Ce sont les queries qui justifient le chantier (le gain est
maximal là).

- [x] **Sous-phase 1.0 (préalable) — Audit en cohabitation** :
  `audit_log` ajouté à `tables.py`, `async_emit_event` accepte
  union `AsyncCursor | AsyncConnection` SA, dispatch interne via
  `text(...)` côté SA (pas d'import MetaData depuis application/,
  contrainte DDD). Aucun call site touché — chaque module bascule
  individuellement vers la branche SA quand il est migré. Aucune
  fenêtre d'indisponibilité côté API admin.
  - Test d'intégration `TestAsyncEmitEventViaSAConnection` couvre
    la branche SA (3 cas).
  - Note : passage à un `AuditRepository` propre (`application/`
    via port + adapter `infrastructure/`) reste prévu en Phase 3
    du chantier audit-cto.
- [x] **`filters.py` refondu** : `WhereClause(sql, binds)` +
  `assemble_where(clauses)` (binds nommés `:name`, syntaxe SA `text()`).
  ~17 fonctions `*_clause` remplacent les anciens `apply_*` mutateurs
  de `(conditions, params)`. Branche legacy supprimée à la fin de la
  Phase 1.
- [x] **Pilote stats/publishers** *(commit `aa1d5be`)* — premier
  consommateur sur l'API SA (4 filtres + APC_SUM_SA en bind nommé).
- [x] **stats/{journals,labs,summary}** *(commit `60d1c48`)* —
  3 fichiers + 6 endpoints. Helper `_common_clauses(... skip=)` pour
  les facettes croisées de stats_summary.
- [x] **persons/list** *(commit `c507a0b`)* — 3 endpoints (directory,
  search, list admin) + variantes SA `person_*_clause`.
- [x] **publications/list** *(commit `8b7e0f7`)* — 3 endpoints (list,
  export.csv, export-theses.csv) avec ~10 nouvelles `*_clause`
  (access, doc_type, source, person, corresponding, hal_status, apc,
  no_lab, country, subject, publisher_id, journal_id).
- [x] **laboratories** *(commit `edeab5a`)* — 6 endpoints. Bonus :
  `infrastructure/perimeter.async_get_persons_perimeter_root_ids`
  passé en mode dispatch.
- [x] **publications/facets** *(commit `5565d06`)* — le plus
  complexe : `_PublicationFacetsBuilder` réécrit, parallélisme
  préservé via `engine.begin()` (une AsyncConnection SA par facette).
  Bonus : persons/facets, publications/detail (all_years,
  get_publication_detail, get_publication_subjects).
- [x] **persons/detail** *(commit `9c2a672`)* — 6 endpoints
  (id/profile/theses/addresses/dashboard/subjects).
- [x] **Nettoyage `apply_*` legacy** : tous les apply_* supprimés
  une fois plus aucun consommateur. `apply_stats_apc_filter` aussi.
- [x] **subjects.py** — partie pipeline traitée au Lot 3.B sub-lot 5
  (cf. ci-dessous). Les opérations JSONB merge restent en `text()`.

### Phase 2 — Migration des modules (repos d'écriture + services + routers writes)

Migration par module complet : repository d'écriture
(`infrastructure/repositories/async_*_repository.py`), service
correspondant (`application/*.py` côté async), et routers writes
(`POST/PUT/DELETE` basculés sur `get_sa_connection()`). C'est
principalement mécanique ; gain en cohérence et en futur-proofing
pour Alembic. Les sous-phases historiquement nommées 1.1/1.2/1.3
dans les commits sont en réalité ici (cf. note de refactor de la
fiche).

- [x] **Sous-phase 2.1 — Module pilote `config` + `perimeters`**
  *(commit `ef817a3`, marqué "sous-phase 1.1" dans l'historique git)* :
  `PgAsyncConfig`, `PgAsyncPerimeterRepository`, `application/config.py`
  et les écritures des routers `config` et `perimeters` migrés en
  AsyncConnection SA (option B). `delete_perimeter` bascule
  naturellement vers la branche SA de `async_emit_event`.
  - Helper `get_sa_connection()` ajouté dans
    `interfaces/api/async_deps.py` (parallèle à `get_async_cursor`).
  - Lifespan FastAPI initialise l'AsyncEngine SA à côté du pool
    psycopg.
  - Tests `test_config_service` (20/20) ré-écrits sur la fixture
    `sa_conn`, helpers SA (`text()` paramétré).
  - **Découverte** : `ARRAY` doit être importé depuis
    `sqlalchemy.dialects.postgresql` (pas `sqlalchemy`) pour avoir
    `.contains()`. Idem pour `JSONB`. Pattern à reproduire sur les
    autres tables.
  - Endpoint `GET /api/perimeters` (lecture) reste en psycopg pour
    cette sous-phase : il dépend de la CTE récursive
    `infrastructure.perimeter`, à migrer avec ce module.
- [x] **Sous-phase 2.2 — Module `structures`**
  *(commit `5287818`, marqué "sous-phase 1.2" dans l'historique git)* :
  3 tables ajoutées à MetaData (`structures`, `structure_relations`,
  `structure_name_forms`). Repo réécrit en SA Core (delete/select/update/insert/pg_insert
  pour `ON CONFLICT DO NOTHING`). Service migré en `AsyncConnection`,
  `Json()` wrapper retiré (SA gère JSONB). Routers writes basculés
  sur `get_sa_connection()`. Conftest API étendu pour patcher
  `build_async_engine` (sinon les tests tombaient sur la base prod).
  Tests : 23/23 service + 32/32 API + suite complète 1322/1322.
- [x] **Sous-phase 2.3 — Modules `journals` + `publishers`**
  *(commit `d10b3f5`, marqué "sous-phase 1.3" dans l'historique git)* :
  4 tables ajoutées (`journals`, `journal_name_forms`, `publishers`,
  `publisher_name_forms`). `Numeric` importé. Repo journal +
  publisher réécrits en SA Core ; cross-table updates
  (publications, source_publications, apc_payments) en `text()`
  (pattern accepté). `find_shared_title_journal_pairs` en SA
  aliases. `merge_journal_into` : SELECT-puis-UPDATE pour éviter le
  warning "cartesian product". `application/journals.py` et
  `application/publishers.py` fonctions async migrées en
  `AsyncConnection`. Routers writes basculés sur
  `get_sa_connection()`. `existing_journal_ids` et
  `existing_publisher_ids` en SA pour partager la transaction du
  merge. Tests : 34/34 service + suite complète 1322/1322.
- [x] **Préalable bloc 2.4-2.7** *(commit `cf29b2e`)* — `tables.py`
  étendu avec toutes les tables nécessaires (addresses, authorships,
  source_authorships, persons*, publications*, etc.) et 4 enums
  Postgres (identifier_status, source_type, oa_type, doc_type).
  `infrastructure/perimeter.py` : helpers async dispatch-aware.
- [x] **Préalable bloc 2.4-2.7** *(commit `d7c0031`)* —
  `async_authorship_repository.py` en mode dispatch (cur psycopg |
  AsyncConnection SA), pour cohabiter avec les modules en cours de
  migration. Branche psycopg supprimée en Phase 4.
- [x] **Sous-phase 2.4 — Module `addresses`** *(commit `b9f74a9`)* :
  `async_address_repository.py` migré SA Core (insert/update/delete/
  select via tables, `pg_insert.on_conflict_do_update`, `text()` pour
  les CTE cross-aggregate sur `source_publications`/`publications`).
  `application/addresses_countries.py` et `addresses_structures.py`
  signatures `cur → conn`. Router `addresses` writes basculés sur
  `get_sa_connection()`. Helpers tests en `text()`. Exception
  cross-aggregate `address ↔ publications.countries` préservée.
  Tests : 34/34 service + suite complète 1322/1322.
- [x] **Sous-phase 2.5 — Routers authorships en SA**
  *(commit `2645140`)* : 2 endpoints
  (`PATCH /api/authorships/{id}/exclude` côté router persons,
  `PATCH /api/source-authorships/{src}/{id}/exclude` côté router
  publications) basculés sur `get_sa_connection()`. Les autres
  fonctions de `application/authorships.py` continuent d'accepter
  le dispatch (signatures `cur: Any`).
- [x] **Préalable 2.6 — `async_person_repository/` en mode dispatch**
  *(commit `789e688`)* : les 4 sous-modules `_core.py`,
  `_identifiers.py`, `_name_forms.py`, `_authorships.py` migrés en
  dispatch (pattern interne aux fonctions, cohérent avec
  `infrastructure/perimeter.py`). `__init__.py` non touché.
- [x] **Sous-phase 2.6 — Services + routers persons en SA**
  *(commit `727371b`)* : `application/persons.py` async fonctions
  signatures `cur → conn`. Router persons : ~10 endpoints write
  basculés sur `get_sa_connection()`. Tests : suite complète OK.
- [x] **Préalable 2.7 — `async_publication_repository.py` en dispatch**
  *(commit `4ca4c5f`)* : 14 méthodes en dispatch (find_by_doi/nnt/title,
  update_*, create, merge_into, mark_distinct), helpers `_json_dumps_or_none`
  et `_merge_into_sa` pour la branche SA.
- [x] **Sous-phase 2.7 — Routers admin_duplicates en SA**
  *(commit `cf2389d`)* : `mark_distinct` et `async_merge_publications`
  signature `cur → conn`. `publication_duplicates.get_publications_basic`
  en dispatch. Routers `merge` + `mark-distinct` basculés sur
  `get_sa_connection()` ; SAVEPOINT via `conn.begin_nested()`.

### Phase 3 — Migration des queries statiques restantes

Queries SELECT/INSERT/UPDATE/DELETE statiques. Gain : uniformité
du codebase, suppression complète de `cur.execute` côté code
applicatif (préalable à la Phase 4).

Hors Phase 3 :

- `interfaces/cli/*` : audit deprecated/one-shot/recurring préalable
  nécessaire (cf. audit-cto Phase 3) ; ne migrer que les scripts
  conservés.
- `infrastructure/perimeter.py` : CTE récursive, reste en `text()`.
- `infrastructure/sources/*` : extracteurs API (staging/raw),
  hors scope BDD canonique.
- `infrastructure/db/migrate.py` : exclu explicitement.
- Branches dispatch psycopg des repos sync (`publication_repository.py`) :
  disparaissent en Phase 4 quand l'orchestrateur pipeline basculera.

**Critère d'arrêt par fichier** : si un module reste plus lisible
en SQL brut (CTE complexe, opérations JSON avancées type `jsonb_set`,
window functions complexes), on garde `text()` et on documente le
choix dans une note locale.

#### Lot 3.A — Repositories sync (~113 `cur.execute`, 8 fichiers)

Pendants synchrones des `async_*_repository.py` déjà migrés en
Phase 2. Migration en mode dispatch (cur psycopg | Connection SA),
calquée sur les async qui cohabitent avec un caller psycopg encore
non migré (cf. `async_authorship_repository.py`). La branche psycopg
disparaîtra en Phase 4 quand l'orchestrateur pipeline basculera.

**Préalable** : `Engine` SA sync dans `infrastructure/db/engine.py`
(anticipé du 2ᵉ item de Phase 4 puisqu'il conditionne tout le lot).

- [x] `Engine` SA sync ajouté dans `infrastructure/db/engine.py`
  (factory `get_sync_engine`, fixture test `sa_sync_conn`).
- [x] `publication_repository.py` (22 occ.) — dispatch (13 méthodes
  + merge_into / `_merge_into_sa` helper). SA branche en `text()` :
  les queries publications sont trop intriquées en casts enum
  (oa_type, doc_type, source_type) et opérations array pour gagner
  à passer par la MetaData.
- [x] `journal_repository.py` (18 occ.) — dispatch (10 méthodes +
  merge_journal_into).
- [x] `publisher_repository.py` (17 occ.) — dispatch (7 méthodes +
  merge_publisher_into).
- [x] `person_repository/_core.py` + `_authorships.py` +
  `_name_forms.py` + `_identifiers.py` (42 occ. au total) — dispatch
  par sous-module (chaque fonction bascule sur `isinstance(conn, Connection)`).
  Pattern calqué sur `async_person_repository/*` qui était déjà en
  dispatch.
- [x] `authorship_repository.py` (14 occ.) — **supprimé** : code
  mort en prod (les 3 fonctions sync de `application/authorships.py`
  n'avaient aucun caller hors tests, scripts cités dans les
  docstrings — `split_bad_merges`, `fix_oa_person_conflicts` —
  disparus). `TestDeleteOrphanAuthorships` converti en async pour
  préserver la couverture du SQL utilisé via `async_delete_orphan_authorships`.

#### Lot 3.B — Queries pipeline (`infrastructure/db/queries/`, ~117 occ.)

Code appelé par le pipeline (sync). Bénéficie du même `Engine` SA
sync que le Lot 3.A.

Sous-lots, par étape du pipeline :

- [x] **Normalizers** (HAL/OA/WoS/ScanR/theses/Crossref) end-to-end :
  queries + ports + orchestrators + CLI + tests intégration migrés
  en SA Connection. Infra partagée (`staging.py`, `_savepoint.py`,
  `base.py`, `source_authorships.py`, `addresses.py`) nettoyée du
  dispatch transitoire. `run_pipeline.py` phases normalize migrées.
  Commits : `3edb300` (CrossRef + dispatch infra), `a22623e` (WoS),
  `bdb677a` (OA), `cf4dd24` (ScanR), `951d91d` (theses), `cd149ad`
  (HAL), `05bf493` (cleanup dispatch).
- [x] **Pipeline publications/staging/merge**  Commit
  `ac06648`.
- [x] **Pipeline persons/authorships**
- [x] **Pipeline addresses/structures**
- [x] **`subjects.py`** migré ; port + orchestrators (`subjects/run.py`,
  `_common.py:SubjectCache`, 6 ingestors, `cooccurrences/run.py`) et
  `run_pipeline.py` (phases subjects + cooccurrences) basculés sur
  `Connection` SA. Le UPSERT JSONB merge reste en `text()` (ON CONFLICT
  imbriqué avec `jsonb_each`/`jsonb_agg` — critère « SQL brut plus
  lisible »), bind `ontologies` typé `JSONB`.

#### Lot 3.C — Reste du code applicatif (~13 occ.)

- [x] `infrastructure/addresses.py` migré (suite Lot 3.B normalizers,
  commit `05bf493`).
- [x] `application/pipeline/_savepoint.py` migré (suite Lot 3.B sub-lot 2,
  commit `ac06648`).
- [x] `infrastructure/app_config.py` — dispatch ajouté aux 2 fonctions
  qui restaient en raw `cur.execute` (`get_hal_collections`,
  `get_extraction_api_ids`).
- [x] `run_pipeline.py:VACUUM` — `engine.connect()` + `AUTOCOMMIT`.
- [x] `application/audit.py` et `infrastructure/db_helpers.py` :
  faux-positifs (mentions de `cur.execute` dans des docstrings, pas
  d'appel réel).

#### Critère de complétion Phase 3

Plus aucun `cur.execute` dans le code applicatif **hors** :
- `interfaces/cli/` (en attente de l'audit dédié)
- `infrastructure/perimeter.py` (CTE récursive, choix assumé)
- `infrastructure/sources/*` (extracteurs API, hors scope)
- Branches dispatch psycopg de `publication_repository.py`
  (Phase 4 les nettoie)

### Phase 4 — Finalisation : zéro `cur.execute` applicatif

L'essentiel de la bascule du pool a été faite par le chantier
`docs/chantiers/sync-async-deduplication.md` :
- Lifespan FastAPI utilise l'`Engine` SA sync (plus d'`AsyncEngine`
  ni de pool psycopg async).
- `infrastructure/db/async_connection.py` supprimé.
- Côté sync : `Engine` SA sync en place (`build_sync_engine` /
  `get_sync_engine`).

Reste pour clore le chantier :

- [x] Tous les `psycopg.connect()` / `get_connection()` directs
  migrés vers `engine.connect()` SA (CLI imports/maintenance/pipeline,
  base.py des extracteurs, fetchers ad-hoc).
- [x] `publication_repository.py` purement SA.
- [x] Dispatch retiré de `journal_repository`, `publisher_repository`,
  `person_repository/*`, `audit_repository`, `infrastructure/perimeter.py`,
  `infrastructure/app_config.py`. `infrastructure/db_helpers.py` (utils
  psycopg) supprimé.
- [x] Plus aucun `cur.execute(...)` applicatif hors `infrastructure/db/migrate.py`
  (exclu explicitement).

### Phase 5 — Décision Alembic

À traiter une fois Phase 4 terminée (avant, c'est prématuré).

- [ ] Évaluer le coût de migration des 21+ migrations existantes
  vers Alembic.
- [ ] Décider : adopter Alembic (auto-génération des diffs MetaData)
  ou conserver `migrate.py` actuel.

## Alembic — porte ouverte

Une fois SQLAlchemy Core en place avec MetaData explicite, le coût
d'adoption d'Alembic devient mineur (Alembic se branche
naturellement sur la MetaData SQLAlchemy). Question à reposer en
fin de Phase 4 :

**Bénéfices Alembic** :
- Migrations auto-générées par diff entre MetaData et schéma DB
  (`alembic revision --autogenerate`). Plus besoin de rédiger les
  `ALTER TABLE` à la main.
- Downgrades (`alembic downgrade -1`) — utile si la DSI les exige
  ou si nous-mêmes en avons besoin un jour.
- Standard de l'écosystème Python.

**Coûts** :
- Réécriture des 21+ migrations existantes au format Alembic
  (mécanique mais long).
- Adoption d'un outil supplémentaire à comprendre pour un
  reprenant.
- Notre `migrate.py` actuel (141 lignes) est extrêmement simple
  et fait son travail.

**Critère de décision** : la motivation principale serait la
génération automatique des migrations à partir des diffs MetaData.
Si on garde MetaData explicite (donc on revoit la MetaData à chaque
migration manuelle), l'auto-génération est un vrai gain. Si on part
sur reflection, Alembic perd l'essentiel de son intérêt.

À trancher en Phase 5 avec le recul de l'utilisation réelle.

## Validation

Critères pour considérer une phase comme terminée :

- Tous les tests d'intégration passent
  (`pytest tests/integration/ -v`).
- `mypy` passe sans nouveau `ignore`.
- `lint-imports` passe (les frontières DDD ne sont pas violées —
  notamment `domain/` ⊥ SQLAlchemy).
- Pas de régression de perf perceptible sur les endpoints API
  critiques (à mesurer ponctuellement avec un timing simple sur
  `/api/publications` avec filtres).
- Pour Phase 0 : un test d'intégration spécifique vérifie la
  cohérence MetaData ↔ schéma réel
  (cf. `infrastructure/db/tables.py` introspecté contre la DB).

## Hors scope de ce chantier

- ORM SQLAlchemy. Définitivement non.
- Réécriture de `domain/` (value objects, ports). Tout reste pur.
- Migration de `interfaces/cli/` à un nouveau pattern. Les CLI
  utilisent les repos comme aujourd'hui.
- Modification du pattern de transaction (savepoints,
  context managers actuels). On garde tel quel.
- Refonte de `infrastructure/perimeter.py` (CTE récursive). Ça
  reste en `text()`.
- Création de modèles Pydantic-SQLAlchemy. Pydantic vit côté API
  (`interfaces/api/models.py`), pas couplé au schéma.

## Lien avec les autres chantiers

- `docs/chantiers/audit-cto.md` (Phase 1, item « SQLAlchemy
  Core ») — ce chantier clôt cet item.
- `docs/chantiers/sync-async-deduplication.md` — indépendant, mais
  les deux chantiers convergent : si la convergence sync/async est
  faite avant celui-ci, on a moins de fichiers à migrer ; si elle
  est faite après, le chantier sync/async sera trivialement plus
  simple parce que SQLAlchemy fournit `Engine` (sync) et
  `AsyncEngine` (async) naturellement.
- `docs/chantiers/ports-cleanup.md` (terminé) — ce chantier-ci
  consomme directement le résultat (les `update_*_fields` reçoivent
  déjà un `dict`, prêt à être passé à `update(...).values(**dict)`).
