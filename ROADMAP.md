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
- [x] **Reliquat** : `admin_feedback`, `structures`, `journals`,
  `publishers`, `config`. 21 `cur.execute` migrés vers les modules
  `infrastructure/db/queries/` correspondants. `stats.py` n'avait
  déjà plus de SQL inline.

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
