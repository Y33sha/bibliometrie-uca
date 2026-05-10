## Chantier qualité du code : maintenabilité, auditabilité, scalabilité

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

### 2.8 Observabilité et robustesse production
- [ ] **Checks automatiques post-pipeline** : comptages, orphelins,
  anomalies (type tests de caractérisation sur les données produites)
- [ ] Dashboard métriques (temps de réponse, pool DB, taux d'erreur) —
  partiellement en place, à consolider

### 2.13 Exploitation psycopg3

#### 2.13.4 `connection.pipeline()` — POC d'abord
Candidat principal : **phase 2 de `build_authorships`**
(`infrastructure/db/queries/authorships_build.py:38`) — 5 UPDATE
séquentielles sans dépendance inter → 1 round-trip au lieu de 5.
- [ ] POC sur `build_authorships` phase 2, benchmark avant/après sur
  sandbox, delta dans le message de commit.
- [ ] Si gain > 20 % : étendre à `populate_affiliations`,
  `merge_pubs_by_*`.

### 2.14 Async des extractions HTTP pipeline

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
