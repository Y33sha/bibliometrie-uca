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

### 1.6 Inversion de dépendance
Extraction SQL pipeline → `infrastructure/db/queries/` faite.
Orchestrateurs `application/pipeline/*` dépendent de ports
(`application/ports/*`) ; adapters PostgreSQL injectés via les
composition roots (`interfaces/cli/pipeline/*`, `run_pipeline.py`).
Côté API : factories FastAPI `Depends` câblent query services et
repos dans tous les routers (chantier `docs/chantiers/routers-di.md`,
terminé). Le contract `import-linter` "Routers : pas d'import direct
de infrastructure" verrouille la règle.


## Chantier qualité du code : maintenabilité, auditabilité, scalabilité

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

#### 2.7.5 Tests frontend
- [x] Vitest configuré, **5 composables testés** (`useDebouncedSearch`,
  `useColumnVisibility`, `useUrlFilters`, `useFacets`,
  `usePaginatedFetch`) — 52 tests couvrant timers, race conditions,
  persistance `localStorage`, sérialisation URL, mappings de facettes,
  pagination. `happy-dom` pour les tests qui touchent `localStorage`/
  `window`. `@testing-library/svelte` non nécessaire (composables
  non-DOM). 24 tests utils existants sur `src/lib/utils.ts`.
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
- [ ] **Revue code dupliqué / uniformisation** : ex. les fonctions de
  compatibilité de noms existent en deux versions (Python dans
  `domain/names.py`, SQL dans `admin_person_duplicates.py`) — à
  unifier si la logique diverge.

### 2.13 Exploitation psycopg3

Audit terminé sur la majorité des fonctionnalités (`class_row`,
`COPY FROM STDIN`, `cursor.stream()`, `prepare_threshold`, adaptateurs
de types custom). Seule subsiste la piste `connection.pipeline()`.

#### 2.13.4 `connection.pipeline()` — POC d'abord
Candidat principal : **phase 2 de `build_authorships`**
(`infrastructure/db/queries/authorships_build.py:38`) — 5 UPDATE
séquentielles sans dépendance inter → 1 round-trip au lieu de 5.
- [ ] POC sur `build_authorships` phase 2, benchmark avant/après sur
  sandbox, delta dans le message de commit.
- [ ] Si gain > 20 % : étendre à `populate_affiliations`,
  `merge_pubs_by_*`.

### 2.14 Async des extractions HTTP pipeline

Différent du chantier §2.12 qui ciblait la concurrence **entre requêtes
entrantes** sur l'API. Ici l'objectif est de paralléliser les **appels
HTTP sortants** dans un pipeline mono-processus, pour maximiser le
débit autorisé par les rate-limits des APIs sources.

**Constat** : extractions actuelles séquentielles (latence ~500 ms par
requête paginée × N pages). On sature ~20 % du débit permis. HAL ≈ 2h,
OpenAlex corpus complet ≈ 20 min, etc.

**Approche** : migrer `requests` → `httpx.AsyncClient` + `asyncio.Semaphore`
par source (borné au QPS documenté). Backoff exponentiel sur 429. Îlot
async encapsulé via `asyncio.run()` en début d'étape pipeline ; le
reste du pipeline reste sync.

**Candidats (ROI décroissant, révisé après exploration)** :
- [x] **`fetch_missing_doi` — 4 adapters** (OpenAlex, HAL, WoS, ScanR) :
  boucle embarrassingly parallel (1 requête HTTP par lot, zéro
  dépendance entre lots). Gain mesuré sur OpenAlex : 18 req/s vs
  ~5 req/s plafond sync (×3.6). `max_concurrent` par source calibré
  sous le rate-limit documenté (OA=3, WoS=3, HAL=5, ScanR=5).
- [ ] Scripts d'enrichissement : `enrich_journal_apc.py`,
  `enrich_oa_status.py` — même pattern, ROI élevé.
- [ ] Scripts fetch ciblé : `fetch_missing_hal_id`, `refetch_truncated`.
- [ ] Extracteurs de sources (~1400 LOC, 5 fichiers) : HAL, OpenAlex,
  WoS, ScanR, theses.fr. Gain attendu plus modéré côté OpenAlex
  (pagination cursor-based → séquentielle intra-année,
  parallélisation inter-années limitée à ×2-×3) ; plus élevé côté
  HAL/theses.fr (pagination offset, parallélisme page par page).

**Dépendances** :
- `httpx` déplacé des deps dev aux deps prod (fait).
- Mock côté tests : `respx` ajouté en dev (pilote §2.14).
- `infrastructure/api_retry_async.py` : variante async de
  `api_retry.py` créée dans le pilote ; factorisation sync↔async à
  envisager après 2-3 migrations supplémentaires.

**Pas en scope** : les étapes CPU-bound du pipeline (normalisation,
build_authorships, dédup). Async n'aide pas là-dessus.
