# Roadmap transmission DSI

## Priorisation (ordre d'attaque)

Synthèse de l'audit DSI (avril 2026) — ROI décroissant (impact / effort) :

1. [x] **§1.7b** — Lever les 14 `ignore_imports` pipeline. Effort faible, débloque la testabilité unitaire des `normalize_*` et fige la cohérence DDD avant transmission. *Clôturé le 2026-04-20.*
2. [x] **§2.10** — Découper les 4 fichiers backend monolithiques (`queries/publications.py` 1140 LOC, `queries/persons.py` 711, `repositories/person_repository.py` 665, `queries/stats.py` 630). Effort moyen, impact maintenabilité + testabilité. *Clôturé le 2026-04-20.*
3. [~] **§2.1 +§2.2** — Remonter `fail_under` de 49 → 60+ en ciblant `infrastructure/db/queries/*`. Effort moyen, réduit le risque de régression en prod. *Partiel au 2026-04-20 : phases A→C faites, couverture 50.27 % → 56.34 %, `fail_under = 55`. Pour franchir 60 il faudrait élargir aux routers API (phase D non faite).*
4. [x] **§2.7.4** — Découper les 3 routes Svelte > 1000 LOC. *Fait 2026-04-20 : `publications/[id]` 1132 → 206, `admin/persons` 1263 → 642, `admin/structures` 1572 → 797. 14 composants extraits, 0 erreur svelte-check.*
5. [x] **§2.7.3** — Généraliser les types OpenAPI aux endpoints restants. *Clôturé le 2026-04-20 : 14 routers couverts (stats, publications, laboratories, addresses, hal_problems, admin_person_duplicates, admin_pipeline, admin_feedback, perimeters, publishers, auth, config, authorships, admin_duplicates) ; ~63 endpoints supplémentaires annotés `response_model` ; ~62 interfaces TS locales remplacées par les types générés.*
6. [ ] **§2.6** — `CONTRIBUTING.md` + descriptions OpenAPI. Effort faible, impact onboarding DSI.
7. [ ] **§2.7.5** — Amorcer des tests frontend (Vitest composables + Playwright parcours critiques). Nouveau.
8. [ ] **§2.4** — Convention `NNN_down.sql` pour rollbacks d'urgence. Effort très faible, résilience prod.
9. [x] **§2.11** — Migration psycopg2 → psycopg3. *Clôturé le 2026-04-20 : `psycopg2-binary` retiré, `psycopg[binary]==3.3.3` + `psycopg-pool==3.3.0` en place. Pool `ConnectionPool` avec `row_factory=dict_row` global. 24 sites `Json(...)` migrés vers `psycopg.types.json.Jsonb`. 10 appels `execute_values` migrés vers `cur.executemany` (perf préservée par le pipeline mode psycopg3). Adaptations psycopg3 strict typing : casts `%s::int`/`%s::text[]` sur les `IS NULL`, `IN %s` → `= ANY(%s)`, `ARRAY[%s::int]`. Tests 910/910 verts.*

Les chantiers `§1.1`, `§1.2`, `§1.6`, `§1.8`, `§2.3`, `§2.5`, `§2.9`, ainsi que le **Chantier fonctionnalités**, restent en fil rouge et ne figurent pas dans cette priorisation.

---

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
justifie pas à ce stade :

- Équipe solo + transmission DSI, pas de collaboration pluri-domaine
  qui bénéficierait d'une ubiquitous language ancrée dans le code.
- Règles métier modérées ; les invariants existants (ex. un ORCID =
  une personne confirmée, pas de fusion entre deux personnes RH)
  sont protégés au niveau des services, sans casser.
- Les `domain/publication.py`, `domain/person.py`, etc. contiennent
  déjà la logique pure (DOI, normalisation, formes de noms,
  extraction HAL-ID) — les passer en classes stateful ne
  changerait pas les garanties.

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

### 1.2 Factoriser la logique commune aux sources
`SourceNormalizer` et `SourceExtractor` factorisent le boilerplate
(argparse, cycle connexion, try/except, summary). Ajouter une nouvelle
source (CrossRef, ArXiv, PubMed, DataCite) = un subclass +
`load_config()` + `extract_all()` côté extractor, `process_work()`
côté normalizer.

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

### 1.7 Verrouiller les acquis : import-linter
Contrat `layers` unique actif : `interfaces > infrastructure |
application > domain` (siblings au même niveau — ni l'un ni l'autre
ne peut importer l'autre ; les deux peuvent importer domain ;
interfaces peut tout importer). Vérifié en pre-commit + CI.

### 1.8 Audit périodique
- [x] Parcours régulier pour repérer : SQL mal placé, dépendances dans le
  mauvais sens, logique métier qui a migré dans infrastructure, code
  dupliqué entre agrégats.

---

## Chantier qualité du code : maintenabilité, auditabilité, scalabilité

### 2.1 Tooling & CI
Pre-commit hook (ruff + ruff format + checks basiques + lint-imports +
pytest-unit). Mypy strict (`check_untyped_defs` + `disallow_untyped_defs`)
en CI et pre-commit, 0 erreur. Toutes les fonctions annotées (souvent
`Any` pragmatique pour les params DB).
- [x] **Couverture** : `pytest --cov` en CI. Seuil actuel
  `fail_under = 56`, baseline réelle ~57.3 %. `interfaces/cli/*`
  exclu (scripts one-shot, logique utile testée via
  application/infrastructure). Remontée de 49 → 56 dans le chantier
  §2.1 (phases A→C : tests ajoutés sur 14 modules `queries/*` ; phase D
  partielle : router `addresses` 0 → 99 %). 3 bugs latents exposés et
  corrigés en chemin (`PgAddressLinker` fallback RealDictCursor,
  `authorships_stats` scope `sa.source`, `harvest.fill_source_person_*_if_null`
  colonne `updated_at` inexistante). Pour dépasser 60, finir phase D
  sur `persons`, `publishers`, `structures`, `admin_feedback`.

### 2.2 Organisation des tests
`tests/unit/` + `tests/integration/` (sous-dossiers `domain/`,
`application/`, `pipeline/`, `interfaces/`). Conftest splitté
(cross-cutting vs setup BDD). Hook pre-commit `pytest-unit` sur
`tests/unit/` seulement ; CI fait les deux.
- [x] Tests de caractérisation sur les routers critiques à maintenir
  quand on touche aux combinaisons de filtres / construction dynamique
  de WHERE/ORDER BY.

### 2.3 Dette externe / dépendances
`pyproject.toml` source unique (PEP 621) + `uv.lock` committé.
`deptry` et `pip-audit` en place.
- [ ] Version Python supportée documentée et alignée avec prod DSI.

### 2.4 Migrations BDD
- [x] **Évaluation Alembic** : ne pas migrer. Système maison
  `migrate.py` (~120 lignes) lisible en 2 min, 70+ migrations gérées
  sans downgrade utilisé. Alembic nécessiterait SQLAlchemy (chantier
  disproportionné). Décision à revisiter si downgrades deviennent
  récurrents ou si la DSI l'exige.
- [ ] Si downgrades deviennent utiles : convention `NNN_down.sql`
  optionnelle, ~10 lignes à ajouter dans `migrate.py`.

### 2.5 Code hygiene
Seuil ruff C901 (complexité cyclomatique) à 15. Mypy strict sans erreur.
Dédoublonnage via pylint `duplicate-code` fait. Magic values métier
centralisées dans `domain/` + `filters.py`.
- [x] À auditer périodiquement : nouvelles fonctions > C901=15,
  nouvelles duplications, nouvelles magic values inline.

### 2.6 Documentation et DX
- [x] **README** refait : quickstart Docker + sans Docker, arborescence
  DDD à jour, commandes pipeline / tests / coverage. Démarrage en
  15 min depuis zéro.
- [x] **Schéma d'architecture** : `docs/architecture.md` (archi
  logicielle — 4 couches DDD, règles d'import, patterns d'injection,
  composition roots) et `docs/donnees.md` (modèle de données, tables,
  domaines fonctionnels).
- [ ] **CONTRIBUTING.md** (ou équivalent) : "comment ajouter une nouvelle
  source de données", "comment ajouter une phase au pipeline",
  "comment ajouter un endpoint"
- [ ] **Descriptions OpenAPI** : Pydantic permet de les générer
  gratuitement depuis les modèles — à compléter endpoint par endpoint.
  Pilote fait sur `/api/journals` (§2.7.3) ; à généraliser aux ~29
  autres endpoints.

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

#### 2.7.2 Centralisation des appels API — fait
- [x] `src/lib/api/` : client étendu avec `post`/`put`/`patch`/`del`
  et `ApiError` typé, 13 modules d'endpoints par domaine (auth,
  persons, publications, authorships, journals, publishers,
  structures, perimeters, config, nameForms, addresses,
  orphanAuthorships, duplicates). Migration des 57 `fetch()` directs
  dans `src/routes/*` → 0 restant hors de `lib/api/`.

#### 2.7.3 Types TypeScript générés depuis OpenAPI — pilote
- [x] **Pilote `/api/journals`** : `JournalOut` + `JournalListResponse`
  Pydantic côté backend, `response_model` exposé dans le schéma
  OpenAPI ; `openapi-typescript` en devDep ; script
  `interfaces/cli/dump_openapi.py` qui dumpe le schéma offline ;
  `npm run types:gen` enchaîne dump + génération + cleanup ;
  `src/lib/api/schema.ts` committé comme source de vérité ;
  interface `Journal` locale du composant admin/journals remplacée
  par le type généré.
- [x] **Généraliser aux autres endpoints**. Audit 2026-04-20 : 115
  endpoints au total, 130 interfaces TS locales. Couverture finale
  (clôturé le 2026-04-20) :
  - [x] `/api/journals` (4 endpoints — pilote d'origine).
  - [x] `/api/persons` (26 endpoints) : 14 GET + 12 mutations annotés ;
    ~30 modèles Pydantic Out ajoutés ; interfaces locales remplacées
    dans admin/persons, persons/, persons/[id], admin/orphan-authorships.
  - [x] `/api/structures` (11 endpoints) : CRUD structure / relations /
    name-forms ; bugfix latent `struct_type → type` sur les enfants
    de /api/structures/{id}.
  - [x] `/api/stats` (7 endpoints) : router renommé `pub_stats → stats`
    en chemin ; modèles OaCounts, *StatsRow, *StatsResponse, StatsSummary,
    StatsFacetsResponse + 4 facets génériques (YearFacet, OaFacet,
    LabFacet, ApcFacet).
  - [x] `/api/publications` (6 endpoints) : PublicationListItem +
    PublicationDetailResponse + facets génériques (IntValueFacet,
    StrValueFacet, LabeledIntFacet, TextStrFacet) ; types.ts de
    publications/[id] migré vers schema.ts (8 interfaces aliasées).
  - [x] `/api/laboratories` (5 endpoints) : Lab*ListItem / Detail /
    PersonsResponse / AddressesResponse / DashboardResponse.
  - [x] `/api/addresses/*` + `/api/countries` + `/api/admin/address-stats`
    (12 endpoints) : Address*, CountryOut, BatchCountryResponse, etc.
  - [x] `/api/hal-problems/*` (6 endpoints) : HalPubDetail (commun aux
    doublons), HalCollectionLab, HalAffiliationConflict*,
    HalDuplicateAccount*.
  - [x] `/api/admin/person-duplicates/*` (5 endpoints) : PersonDedupDetail
    partagé /next + /conflicts/next ; TotalCountResponse générique.
  - [x] `/api/admin/pipeline/*` (4 endpoints) : PipelineStatus,
    PipelineLogsResponse, PipelineReportItem/Content.
  - [x] `/api/admin/feedback/*` (3/4 endpoints — /rerun reste en SSE
    StreamingResponse) : FeedbackStats, FeedbackLabDetected,
    FeedbackMatchedForm, FeedbackAddressItem.
  - [x] `/api/perimeters/*` (6 endpoints) : PerimeterOut, génériques
    CreatedIdResponse, StatusResponse.
  - [x] `/api/publishers/*` (4 endpoints) : PublisherListItem,
    PublisherBasic, MergeResponse réutilisé.
  - [x] `/api/auth/*` (3 endpoints) : AuthCheckResponse, OkResponse.
  - [x] `/api/config/*` (3 endpoints) : ConfigItem, HalCollectionsResponse.
  - [x] `/api/authorships/*` (3 endpoints) : AuthorshipsStats / Facets /
    ListResponse.
  - [x] `/api/admin/duplicates/*` (3 endpoints, doublons publications) :
    PubDedupDetail, PubDuplicateNextResponse, PubMergeResponse.

  En chemin : 4 fixes annexes commités séparément (rename pub_stats,
  Windows path bugs dans test_log + test_pipeline_metrics, Unicode
  dump_openapi.py, pool de connexions stale dans le conftest
  intégration). Réutilisation systématique des modèles déjà présents
  (OkResponse, MergeResponse, DeletedResponse) plutôt que duplications.

#### 2.7.4 Découpe des routes monolithiques — fait 2026-04-20
Audit initial : 3 routes dépassaient 1000 LOC et mêlaient UI + état +
appels API + logique métier.
- [x] `publications/[id]/+page.svelte` : 1132 → 206 LOC. Extraits :
  `types.ts`, `PublicationHeader`, `ThesisBlock`, `TruthAuthorshipsTable`,
  `SourceComparison`.
- [x] `admin/persons/+page.svelte` : 1263 → 642 LOC. Extraits :
  `types.ts`, `PersonsToolbar`, `EditNameModal`, `DetachNameFormModal`,
  `IdentifiersCell`, `MergeSearchCell`.
- [x] `admin/structures/+page.svelte` : 1572 → 797 LOC. Extraits :
  `types.ts`, `StructureList`, `RelationsSection`, `NameFormsSection`,
  `EditFormModal`, `StructureFormModal`.

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
- [x] **Structured logs JSON** : `infrastructure/log.py` émet en JSON
  par défaut (un record = une ligne), prêts pour Loki/ELK/fluentd.
  Format texte en dev via `LOG_FORMAT=text`. Tous les `.log` et
  `status.json` consolidés sous `logs/`.
- [ ] ~~**Alerting sur échec pipeline**~~ — **délégué à la DSI après
  transmission**. La DSI a ses propres outils et il ne sert à rien de
  déployer une solution dev qui sera remplacée. En dev local,
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

### 2.10 Découpe des modules backend monolithiques — clôturé
- [x] `infrastructure/db/queries/publications.py` (1140 LOC) →
  package `publications/` : `list.py`, `facets.py`, `detail.py` +
  `create.py` absorbé depuis `publications_create.py`.
- [x] `infrastructure/db/queries/persons.py` (711 LOC) → package
  `persons/` : `list.py`, `facets.py`, `detail.py`, `admin.py`
  (orphan authorships + HAL duplicate accounts) + `create.py` absorbé
  depuis `persons_create.py`. La partie qualité HAL au niveau des
  publications (initialement dans `persons_admin.py`) a été extraite
  dans le nouveau `hal_problems.py`, miroir du router du même nom.
- [x] `infrastructure/repositories/person_repository.py` (665 LOC) →
  package `person_repository/` : `_core.py`, `_identifiers.py`,
  `_authorships.py`, `_name_forms.py`. La classe
  `PgPersonRepository` dans `__init__.py` délègue aux fonctions
  libres de chaque sous-module, elle ne contient plus de SQL.
- [x] `infrastructure/db/queries/stats.py` (630 LOC) → package
  `stats/` : `publishers.py`, `journals.py`, `labs.py`, `summary.py`
  (by_year + summary + facets + available_years) + `_shared.py`
  (filtre APC + pagination).
- Règle future : quand un fichier `queries/*` ou `repositories/*`
  dépasse 500 LOC, scinder dans le même chantier.

### 2.11 Migration psycopg2 → psycopg3 — clôturé 2026-04-20
`psycopg2-binary` était en fin de support (upstream a déclaré psycopg3
comme successeur, maintenance minimale sur psycopg2). Migration
réalisée en 3 commits sur la branche `feature/psycopg3-migration`
(merge `1700ced`+1) :
- [x] **Étape A — deps** : ajout de `psycopg[binary]==3.3.3` +
  `psycopg-pool==3.3.0`, cohabitation transitoire avec `psycopg2-binary`.
- [x] **Étape B — migration core** (un commit, indissociable car les
  sous-étapes cassaient les tests si séparées) :
  - Pool `ThreadedConnectionPool` → `psycopg_pool.ConnectionPool` avec
    `kwargs={"row_factory": dict_row}` global.
  - 14 CLIs + base `SourceNormalizer` + repositories : suppression de
    `cursor(cursor_factory=RealDictCursor)` (la connexion porte déjà
    `row_factory=dict_row`).
  - 24 sites `Json(...)` : import `from psycopg.types.json import Jsonb as Json`
    (API compatible, aucun call site touché).
  - 8 fichiers, 10 appels `execute_values` → `cur.executemany` avec
    template inliné dans `VALUES (...)`. Perf préservée par le
    pipeline mode psycopg3.
  - Adaptations psycopg3 strict typing : `cur.fetchone()[0]` → alias
    SQL + accès dict, `WHERE id IN %s` → `= ANY(%s)`, `%s IS NULL` →
    `%s::int IS NULL` / `%s::text[] IS NULL` (l'IndeterminateDatatype
    n'est plus toléré), `ARRAY[%s]` → `ARRAY[%s::int]`.
  - Tests pipeline qui voulaient explicitement un cursor tuple :
    `cursor()` → `cursor(row_factory=tuple_row)`.
  - `psycopg2.errors.UniqueViolation` → `psycopg.errors.UniqueViolation`.
- [x] **Étape C — drop psycopg2** : retrait de `psycopg2-binary` du
  pyproject + uv.lock, dernières docstrings actualisées, mypy clean.
- [ ] **Pas fait dans ce chantier** : `row_factory=class_row(...)` pour
  un mapping direct rows → Pydantic Out (sucre sympa pour les
  repositories critiques, mais hors scope strict). À faire si une
  régression de typage le justifie.

Tests : 336 unit + 574 intégration verts avec psycopg2 désinstallé du venv.

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
