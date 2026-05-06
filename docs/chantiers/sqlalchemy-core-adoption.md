# Chantier — Adoption SQLAlchemy Core
Commencé le 2026-05-06.

## État : phase 0 terminée — phases 1+ à exécuter

Décision actée : on adopte SQLAlchemy Core. La porte vers Alembic
reste ouverte et sera réévaluée à la fin du chantier en
coût-bénéfice (cf. section dédiée).

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
- [ ] **Décision option A vs B** (SA comme query builder pur vs
  AsyncEngine de bout en bout) : reportée à la Phase 1, à trancher
  sur le module config réel. Le POC démontre que B est viable ;
  l'arbitrage final dépendra de la complexité de cohabitation avec
  `async_emit_event` (qui attend un cur psycopg) dans
  `delete_perimeter`.


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
- [x] **Sous-phase 1.1 — Module pilote `config` + `perimeters`** :
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
- [ ] `infrastructure/db/queries/filters.py` — refondre l'API en
  retournant des fragments SQLAlchemy composables au lieu de muter
  `(conditions, params)`.
- [ ] `infrastructure/db/queries/publications/facets.py`
  (`_PublicationFacetsBuilder`) — le plus complexe ; vérifier que
  la lisibilité gagne réellement.
- [ ] Listings paginés : `addresses.py`, `persons/list.py`,
  `publications/list.py`, `journals.py`, `publishers.py`,
  `structures.py`.
- [ ] `subjects.py` — partiellement (queries dynamiques uniquement,
  les opérations JSON spécifiques restent en SQL brut).

À chaque étape : commit séparé, tests d'intégration verts, pas de
mélange ancien/nouveau pattern dans un même fichier.

### Phase 2 — Migration des repositories d'écriture

Repositories `infrastructure/repositories/async_*_repository.py` :
les méthodes d'écriture (`update_*_fields`, `create_*`,
`delete_*`, etc.). C'est mécanique, aucun pattern dynamique : gain
principalement en cohérence et en futur-proofing pour Alembic.

- [ ] `async_perimeter_repository.py` (le plus simple, validation
  du pattern).
- [ ] `async_config_repository.py` → la partie config dans
  `infrastructure/db/queries/config.py` (PgAsyncConfig).
- [x] **Sous-phase 1.2 — `async_structure_repository.py` + `application/structures.py` + router writes** :
  3 tables ajoutées à MetaData (`structures`, `structure_relations`,
  `structure_name_forms`). Repo réécrit en SA Core (delete/select/update/insert/pg_insert
  pour `ON CONFLICT DO NOTHING`). Service migré en `AsyncConnection`, `Json()`
  wrapper retiré (SA gère JSONB). Routers writes basculés sur
  `get_sa_connection()`. Conftest API étendu pour patcher
  `build_async_engine` (sinon les tests tombaient sur la base prod).
  Tests : 23/23 service + 32/32 API + suite complète 1322/1322.
- [ ] `async_journal_repository.py`.
- [ ] `async_publisher_repository.py`.
- [ ] `async_address_repository.py`.
- [ ] `async_authorship_repository.py`.
- [ ] `async_person_repository/` (multi-fichiers).
- [ ] `async_publication_repository.py`.

### Phase 3 — Migration des queries statiques restantes

Queries SELECT/INSERT/UPDATE/DELETE statiques sans construction
dynamique. Gain principal : uniformité du codebase.

- [ ] À faire au fil de l'eau, pas en bloc — quand on touche un
  fichier pour autre chose, on le migre tant qu'on y est.
- [ ] Critère d'arrêt : si un fichier reste plus lisible en SQL
  brut (CTE complexe, JSON ops avancés), on le laisse en `text()`
  et on documente le choix dans une note locale.

### Phase 4 — Bascule du pool psycopg vers AsyncEngine

Une fois toutes les queries migrées, remplacer définitivement
`AsyncConnectionPool` psycopg par AsyncEngine SQLAlchemy.

- [ ] Brancher l'AsyncEngine dans le lifespan FastAPI (en
  remplacement du pool psycopg async).
- [ ] Côté sync (pipeline) : créer un `Engine` SA sync, en
  remplacement de l'usage actuel de `psycopg.connect()`.
- [ ] Vérifier qu'il ne reste plus aucun `cur.execute(...)` direct
  dans le code applicatif.
- [ ] Supprimer `infrastructure/db/async_connection.py` et toute
  référence au pool psycopg.

### Phase 5 — Décision Alembic

À traiter une fois Phase 4 terminée (avant, c'est prématuré).

- [ ] Évaluer le coût de migration des 21+ migrations existantes
  vers Alembic.
- [ ] Décider : adopter Alembic (auto-génération des diffs MetaData)
  ou conserver `migrate.py` actuel.
- [ ] Si adoption : créer un chantier dédié (`docs/chantiers/`).
- [ ] Si statu quo : retirer la mention « Alembic à explorer » de
  ROADMAP.md.

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
