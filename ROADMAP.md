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

### 1.7 Extraction des règles pures `application/` → `domain/`

Les services `application/*.py` contiennent aujourd'hui des règles
métier (constantes de priorité, ordres de classement, prédicats de
fusion) qui ne font aucun I/O et devraient vivre dans `domain/`.
Symptôme : `domain/publication.py` contient les VO et modèles JSONB
mais aucune règle *opérant* sur ces concepts — toute la logique est
remontée dans les orchestrateurs d'application par accident
d'historique. Domaine anémique.

À ne **pas** confondre avec §1.4 (entités riches) : il ne s'agit pas
de transformer `Publication` ou `Person` en objets stateful. Il
s'agit d'extraire des fonctions pures et des constantes de règles
métier vers `domain/`, en gardant `application/` comme couche
d'orchestration (repos, audit, transaction).

Candidats identifiés, regroupés par concept de domaine :
- [x] **`domain/publication.py`** : `SOURCE_PRIORITY` (ordre des sources
  pour l'agrégation), `OA_RANK` + `best_oa_status(statuses)`,
  `resolve_doi_conflict(...)` en fonction pure renvoyant une
  `DoiConflictResolution` (le wrapper `application/` applique l'effet
  de bord `repo.clear_doi` quand la règle le demande).
- [x] **`domain/person.py`** : `check_can_merge_persons(has_distinct_rh,
  target_id, source_id)` (invariant « refus si les deux ont une fiche
  RH distincte »).
- [x] Audit complémentaire — `application/journals.py` et
  `application/authorships.py` : rien à extraire. Les règles sont soit
  déjà côté domain (`source in VALID_SOURCES` via `domain/sources.py`),
  soit du SQL pur côté repo (cascade ISSN/name_form), soit des
  validateurs sur rows renvoyées par une requête dédiée
  (`find_shared_title_journal_pairs`) — pas des règles pures
  réutilisables.

Bénéfices : tests unitaires purs sans plomberie de base, règles
concentrées à un endroit, contrat domaine/application plus lisible
pour la DSI.

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

**Candidats (ROI décroissant)** :
- [ ] **Extracteurs de sources** (~1400 LOC, 5 fichiers) : HAL, OpenAlex,
  WoS, ScanR, theses.fr. Gain attendu ×5 sur le temps d'extraction.
- [ ] Scripts d'enrichissement : `enrich_journal_apc.py`,
  `enrich_oa_status.py`.
- [ ] Scripts cross-import + fetch ciblé : `cross_import_*`,
  `fetch_missing_hal`, `refetch_truncated`, `harvest_hal_identifiers`.

**Dépendances** :
- `httpx` ajouté aux deps prod (il est déjà en dev pour les tests
  FastAPI — juste le déplacer).
- Mock côté tests : `respx` ou `pytest-httpx` (migration depuis les
  mocks `requests` actuels).
- `infrastructure/api_retry.py` dupliqué en variante async (pattern
  §2.12).

**Pas en scope** : les étapes CPU-bound du pipeline (normalisation,
build_authorships, dédup). Async n'aide pas là-dessus.

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
