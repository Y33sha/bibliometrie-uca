# Roadmap

## Chantier transition DDD

Architecture hexagonale en place : 4 couches `domain/`, `application/`,
`infrastructure/`, `interfaces/` ; ports Protocol pour les 7
repositories ; SQL extrait des services et des orchestrateurs pipeline.

**Position volontaire : DDD-lite.** On a pris le DDD tactique côté
technique (layering, ports/adapters, DI, value objects sur les
identifiants clés, fonctions pures et mappings dans `domain/`). On
ne pousse **pas** vers le DDD complet — entités riches avec
invariants protégés, aggregate roots, domain events, bounded
contexts formels — parce que le rapport coût/bénéfice ne le
justifie pas à ce stade.

Critère de déclenchement pour faire évoluer ce choix : une règle
métier devient **dispersée et fragile** (plusieurs sites
l'appliquent avec des drifts) → l'extraire en entité ou
aggregate root à **ce moment-là**, pas avant.

### 1.1 Sortir le SQL qui traîne encore dans les routers
Extraction faite sur les 7 routers critiques (pub_stats, publications,
persons, addresses, laboratories, duplicates, authorships) — SQL
centralisé dans `infrastructure/db/queries/`.
- [ ] **Reliquat** (petits routers — existence checks + lookups simples,
  acceptables selon CQRS-lite) : feedback, structures, journals,
  publishers, config, stats. ~30 `cur.execute` au total, la plupart
  étant des `SELECT id WHERE id = %s`.

### 1.3 Module `facets`
Audit fait : la duplication réelle inter-entités est marginale (~30-50
lignes, essentiellement un helper `_where_sql`). Les 3 routers
(publications, persons, laboratories) ont chacun une logique "skip
filter" déjà factorisée **en interne** — publications via classe
`_PublicationFacetsBuilder` (bien découpée en méthodes `_facet_*`),
persons et laboratories via fonctions locales `base_filters(skip=...)`
/ `facet_base(skip=...)`. Le SQL de chaque facette est intrinsèquement
spécifique à son entité (année vs département vs RH) et ne se
factorise pas sans perdre en lisibilité.

Pas de mini-framework maison : si on introduit un query builder
dynamique (SQLAlchemy Core, cf. "À explorer"), il remplacera
naturellement cette surface — autant éviter d'inventer une
abstraction intermédiaire à jeter ensuite.

### 1.4 Entités riches dans le domaine — opportuniste
Cohérent avec la position DDD-lite : on ne fait **pas** de
refactor proactif pour passer `Person`, `Publication`, `Structure`
en entités stateful avec méthodes + invariants. Les services
(`application/persons.py`, etc.) orchestrent les règles via les
repositories ; le domain layer fournit les value objects et les
fonctions pures.

Quand déclencher une extraction en entité riche :
- une règle devient complexe (workflow d'approbation, permissions,
  chaîne d'invariants inter-champs) ;
- la règle est **dispersée** dans plusieurs services et drift ;
- ajouter un test unitaire pur sur cette règle demande aujourd'hui
  trop de plomberie.

Exemples de candidats plausibles si le besoin émerge : fusion
`Person`, assignation d'identifiants (ORCID/idHAL) avec statuts
pending/confirmed/rejected.

### 1.5 Value objects supplémentaires — opportuniste
Ajouter au fur et à mesure quand un besoin de validation ou de
normalisation explicite émerge : `ROR`, `RNSR` (identifiants de
structure), `ISSN` / `eISSN` (journaux). Pas de plan à dérouler,
juste la règle « quand on écrit la 3ᵉ fonction de parsing d'un
même identifiant, on extrait en VO ».

### 1.6 Inversion de dépendance
Extraction SQL pipeline → `infrastructure/db/queries/` faite.
Orchestrateurs `application/pipeline/*` dépendent de ports
(`application/ports/*`) ; adapters PostgreSQL injectés via les
composition roots (`interfaces/cli/pipeline/*`, `run_pipeline.py`).
- [ ] Reste côté API : factories FastAPI `Depends` pour injecter les
  query services dans les routers (équivalent unit-of-work). Mécanique
  si la couverture de tests devient un objectif.

### 1.8 Audit périodique
- [ ] Parcours régulier pour repérer : SQL mal placé, dépendances dans le
  mauvais sens, logique métier qui a migré dans infrastructure, code
  dupliqué entre agrégats.

---

## Chantier qualité du code : maintenabilité, auditabilité, scalabilité

### 2.4 Migrations BDD
- [x] **Évaluation Alembic** : ne pas migrer. Système maison
  `migrate.py` (~120 lignes) lisible en 2 min, 70+ migrations gérées
  sans downgrade utilisé. Alembic nécessiterait SQLAlchemy (chantier
  disproportionné). Décision à revisiter si downgrades deviennent
  récurrents ou si la DSI l'exige.
- [ ] Si downgrades deviennent utiles : convention `NNN_down.sql`
  optionnelle, ~10 lignes à ajouter dans `migrate.py`.

### 2.7 Frontend

#### 2.7.1 Séparation logique métier / composants — partiel
Audit initial : 0 store Svelte formel, 4 composables existants
(`usePaginatedFetch`, `useFacets`, `useColumnVisibility`,
`useUrlFilters`), routes à 500-650 LOC qui mêlent UI + état + appels
API + logique métier.
- [x] Nouveau composable `useDebouncedSearch` (search API avec
  debounce, annulation des requêtes obsolètes, compteur `seq`).
  Appliqué aux 4 routes concernées (admin/journals, admin/publishers,
  admin/orphan-authorships, admin/persons) ; les dicts keyés par id
  ont été simplifiés en « 1 instance + 1 activeKey » puisqu'ils ne
  supportaient qu'une entrée ouverte à la fois.
- [ ] Les routes restantes (admin/structures, admin/addresses,
  admin/countries, laboratories/[id]) utilisent un debounce-filter
  différent (pas de results dropdown) — pattern différent,
  extraction optionnelle via un futur `useDebouncedEffect` si le
  gain devient sensible.
- [ ] Extraction de logique métier spécifique (identifier form,
  detach modal, edit modals dans les gros composants admin) — à
  faire au fil des prochaines touches sur ces composants, pas en
  bulk.

#### 2.7.5 Tests frontend — nouveau
Audit : 0 test frontend (ni unit ni e2e). `svelte-check` couvre les
types mais pas le comportement. Un bug régressif sur un composant admin
n'est détecté qu'en UI manuel.
- [ ] Installer **Vitest** + `@testing-library/svelte` pour tester les
  composables (`useDebouncedSearch`, `useFacets`, `useUrlFilters`,
  `usePaginatedFetch`, `useColumnVisibility`) — ce sont les zones
  métier et les plus réutilisées.
- [ ] Installer **Playwright** pour 2-3 parcours e2e critiques :
  login admin, recherche publication, fusion de personnes.
- [ ] Ajouter au pre-commit + CI une fois une baseline établie.

### 2.8 Observabilité et robustesse production
- [ ] ~~**Alerting sur échec pipeline**~~ — **délégué à la DSI après
  transmission**. La DSI a sans doute ses propres outils et il ne sert
  à rien de déployer une solution dev qui sera remplacée. En dev local,
  monitoring manuel des lancements.
- [ ] **Checks automatiques post-pipeline** : comptages, orphelins,
  anomalies (type tests de caractérisation sur les données produites)
- [ ] Dashboard métriques (temps de réponse, pool DB, taux d'erreur) —
  partiellement en place, à consolider

### 2.9 Audits transversaux périodiques
À faire passer périodiquement — non commencés à ce jour.
- [ ] **12-factor app** : confronter le projet aux pointeurs de
  *Beyond the Twelve-Factor App* (Kevin Hoffman, 2016) qui revisite
  les 12 facteurs originaux et en ajoute 3 à l'ère Kubernetes.
- [ ] **SOLID** sur le code existant : détecter les violations
  (surtout ISP et DIP, les plus courantes quand on vient d'une base
  procédurale).
- [ ] **Revue code dupliqué / uniformisation** : ex. les fonctions de
  compatibilité de noms existent en deux versions (Python dans
  `domain/names.py`, SQL dans `admin_person_duplicates.py`) — à
  unifier si la logique diverge.

### 2.12 Migration async API — clôturé

**Motivation** : les routers déclarés `async def` utilisaient psycopg3
en mode sync → chaque `cur.execute()` bloquait l'event loop uvicorn.
Sous charge concurrente, un endpoint lent gelait tous les autres. Cible
atteinte : stack 100 % async jusqu'à la DB sur la surface FastAPI.

**Scope retenu** : **API seule** passe en async, pipeline et CLI
restent sync. Raison : pipeline mono-processus one-shot, aucun gain de
concurrence, et on évite de polluer `run_pipeline.py` avec des
`asyncio.run()`. Quand une fonction ou un repository est partagé
pipeline/API, la variante sync est conservée en parallèle de l'async ;
les fonctions/ports uniquement consommés par l'API ont été supprimés.

**Phases** :
- [x] **Phase 1** — Infra async parallèle : `infrastructure/db/async_connection.py`,
  `interfaces/api/async_deps.py`, lifespan dans `interfaces/api/app.py`.
- [x] **Phase 2** — Ports async + repositories async : 7 ports exposent
  `Async<Nom>Repository(Protocol)`, 7 implémentations `PgAsync*`,
  factories `async_*_repository` dans
  `infrastructure/repositories/__init__.py`.
- [x] **Phase 3** — `tests/integration/interfaces/conftest.py` supporte
  async parallèle au sync.
- [x] **Phase 4** — Migration verticale des 18 routers (16 slices 4.a→4.p),
  chacune en un commit autosuffisant {queries, services, router, tests}.
  Queries remplacées en place (aucune partagée avec le pipeline) ;
  services partagés dédoublés (sync pour pipeline, async pour API).
- [x] **Phase 5** — Nettoyage :
  - [x] **5.a** : suppression des 3 repos sync orphelins (address,
    config, structure — API-only).
  - [x] **5.b** : retrait de `_get_pool` sync + `get_cursor` de
    `deps.py` ; `get_root_structure_id` migré dans `async_deps.py` ;
    `/api/health` + `/api/metrics` passent par le pool async.
  - [x] **5.c** : activation de la famille ruff `ASYNC` (verrouille les
    I/O bloquantes dans une async def). RUF029 reste en preview chez
    ruff et sera ajoutée quand elle stabilise.
  - [x] **5.d** : authorships — suppression des sync `exclude_authorship`,
    `set_source_authorship_excluded`, `detach_source` (tests migrés async).
  - [x] **5.e** : persons — suppression des 10 sync `set_rejected`,
    `update_name`, `remove_identifier`, `update_identifier_status`,
    `reassign_identifier`, `assign_orphan_authorship`,
    `batch_assign_orphan_authorships`, `detach_authorships`,
    `detach_name_form`, `mark_distinct` (tests migrés async).
  - [x] **5.f** : publications — suppression du sync `mark_distinct`
    (tests migrés async).

**Résultat** : 1026 tests verts. Les fonctions et ports sync qui
subsistent le sont explicitement pour le pipeline/CLI ; plus aucun sync
n'existe "pour l'API". La famille `ASYNC` de ruff empêche la
réintroduction d'I/O bloquantes dans les async def.


### 2.13 Exploitation psycopg3 — séquence après §2.12

Fonctionnalités spécifiques non exploitées aujourd'hui. Certains items
dépendent d'async (§2.12), d'autres peuvent être menés en parallèle
(COPY, prepare_threshold).

#### 2.13.1 `row_factory=class_row(...)` sur les repositories critiques
Candidats par ordre d'impact :
- [ ] `PgPublicationRepository` (22 exec, beaucoup de mapping via `_val`)
- [ ] `PgPersonRepository/_core.py` (16 exec)
- [ ] `infrastructure/db/queries/publications/list.py` + `detail.py`
- [ ] `infrastructure/db/queries/persons/list.py` + `detail.py`
- [ ] `infrastructure/db/queries/stats/*`

~50 call sites au total, ~8-10 commits. **Ne pas** appliquer au pool
global (casse les queries `dict_row` existantes) — appliquer au cursor
à chaque call site. Choix Pydantic vs dataclass à trancher en début de
chantier (préférence dataclass pour la perf, cohérent avec
`domain/publication.py`).

#### 2.13.2 `COPY FROM STDIN` sur les imports massifs
Hotspots par ordre d'impact :
- [ ] `infrastructure/db/queries/normalize_wos.py` (4 `executemany`,
  appelé sur tout le corpus à chaque normalize)
- [ ] `infrastructure/sources/openalex/extract_openalex.py` (batch par
  page API)
- [ ] `infrastructure/sources/wos/extract_wos.py`
- [ ] `infrastructure/repositories/address_repository.py:81`
- [ ] `interfaces/cli/import_apc.py` — ROI faible, laisser si chantier
  complet

Stratégie upsert : `COPY INTO temp table` + `INSERT … ON CONFLICT …
SELECT FROM temp`. ~4-6 commits, benchmark avant/après dans chaque
message de commit. Indépendant de §2.12 (le pipeline reste sync).

#### 2.13.3 `cursor.stream()` sur gros SELECT — à investiguer d'abord
`build_authorships` **n'est pas** candidat (UPDATE massifs, pas de
`fetchall` côté Python). Vrais candidats possibles : normalizers qui
itèrent sur `PgStagingQueries.fetch_*`, `harvest_hal_identifiers`.
- [ ] Grep ciblé `cur.fetchall()` dans `application/pipeline/` avant
  d'engager. Si aucun gros fetchall, skip.

#### 2.13.4 `connection.pipeline()` — POC d'abord
Candidat principal : **phase 2 de `build_authorships`**
(`infrastructure/db/queries/authorships_build.py:38`) — 5 UPDATE
séquentielles sans dépendance inter → 1 round-trip au lieu de 5.
- [ ] POC sur `build_authorships` phase 2, benchmark avant/après sur
  sandbox, delta dans le message de commit.
- [ ] Si gain > 20 % : étendre à `populate_affiliations`,
  `merge_pubs_by_*`.

#### 2.13.5 `prepare_threshold` sur le pool API
Aujourd'hui non configuré → défaut psycopg3 = 5. Pour l'API, régler à
**1** sur le pool async (queries répétées type `find_by_doi`, `list
publications` préparées dès le 1er appel).
- [ ] 1 commit dans `infrastructure/db/async_connection.py` (après
  phase 1 de §2.12).

#### 2.13.6 Adaptateurs de types custom — à skipper sauf besoin
Enums PostgreSQL (doc_type, oa_status, roles) pourraient avoir un
`TypeInfo.fetch()` + `EnumInfo`. Gain marginal, bug de typage jamais
remonté. Skip par défaut ; revisiter si un cast pose un problème
concret.

---

## Chantier fonctionnalités

Le détail est dans `TODO_LAURA.md`. Grands axes :

- **Pipeline** : déduplications avancées, phase de nettoyage des
  hal-id erronés, stockage JSON brut externalisé, robustesse long terme
- **Nouvelles sources** : CrossRef, ArXiv, PubMed, DataCite, brevets, etc.
- **Qualité des données** : détection de publications disparues,
  thèses hors-établissement, méga-authorships, chantier des types de
  documents, chantier journals/publishers
- **Interface admin** : audit trail, adresses, personnes, publishers/journals
- **Interface publique** : dashboards, filtres, relations entre
  publications, accessibilité, responsivité
- **Cas particuliers** et bizarreries à élucider

---
## A explorer

**SQLAlchemy Core** (pas ORM), pour la construction dynamique de requêtes. SQLAlchemy a deux couches : Core (query builder, paramétrage sûr, abstraction du dialecte) et ORM (mapping objets-tables). Tu peux utiliser Core sans ORM : tu écris des requêtes via son API Python (select(...).where(...).order_by(...)) qui génèrent du SQL sûr et paramétré, mais tu n'introduis pas de couche ORM. C'est particulièrement utile pour les requêtes dynamiques avec filtres variables. Tes requêtes "statiques" peuvent rester en SQL brut pour la clarté.

**Alembic** pour les migrations. Indépendant de l'usage d'ORM. Tu continues à écrire ton schéma en SQL brut si tu veux, mais tu versionnes et orchestres les migrations avec Alembic. Gain de maintenance réel, coût d'adoption modéré.

**environnement virtuel**?
