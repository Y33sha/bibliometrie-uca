# Roadmap transmission DSI

## Chantier transition DDD

La transition vers une architecture hexagonale est bien avancée : les
4 couches `domain/`, `application/`, `infrastructure/`, `interfaces/`
sont en place, les ports Protocol existent pour les 7 repositories,
le SQL est extrait des services. Ce qui reste :

### 1.1 Sortir le SQL qui traîne encore dans les routers
- [x] Nouveau module `infrastructure/db/queries/` : accueille les
  query services extraits (CQRS-lite, SQL = infrastructure).
- [x] `filters.py` SQL (PUB_IS_UCA, apply_*_filter) déplacé de
  `interfaces/api/filters.py` vers `infrastructure/db/queries/filters.py`.
- [x] **pub_stats** : 643 → 175 lignes (`stats.py`)
- [x] **publications** : 1222 → 199 lignes (`publications.py`)
- [x] **persons** : 1807 → 512 lignes (`persons.py` + `persons_admin.py`)
- [x] **addresses** : 487 → 197 lignes (`addresses.py`)
- [x] **laboratories** : 449 → 70 lignes (`laboratories.py`)
- [x] **admin_duplicates + admin_person_duplicates** : 595 → 125 lignes
  (`duplicates.py` consolidé)
- [x] **authorships** : 273 → 51 lignes (`authorships.py`)
- [ ] **Reliquat** (petits routers — existence checks + lookups simples,
  acceptables selon CQRS-lite) : feedback, structures, journals,
  publishers, config, stats. ~30 `cur.execute` au total, la plupart
  étant des `SELECT id WHERE id = %s` (OK en router selon Opus 4.7).

### 1.2 Factoriser la logique commune aux sources
- [x] **SourceNormalizer** (`application/pipeline/normalize/base.py`) :
  capture argparse + cycle connexion + --reset + comptage + boucle +
  commit périodique + summary. Hooks pour variations (USE_DICT_CURSOR,
  USE_SAVEPOINT, FETCH_SUB_BATCH, preload_caches, post_process).
  5 normalizers migrés, chaque `main()` passe de 50-130 lignes à 10.
- [x] **SourceExtractor** (`infrastructure/sources/base.py`) :
  capture argparse + cycle connexion + existing_ids + try/except
  (HTTPError, KeyboardInterrupt) + summary. Chaque source drive sa
  propre itération (cursor / search_after / firstRecord / collections
  × pages) via `extract_all()`. 5 extractors migrés.
- [ ] Ajouter une nouvelle source (CrossRef, ArXiv, PubMed,
  DataCite) : ne nécessite plus qu'un subclass + `load_config()` +
  `extract_all()` côté extractor, `process_work()` côté normalizer.

### 1.3 Module `facets`
La logique de facettes dynamiques est dupliquée entre plusieurs
routers (publications, persons, laboratoires). À factoriser dans un
module dédié — typiquement un specification pattern ou un query
builder spécialisé.

### 1.4 Entités riches dans le domaine
Aujourd'hui le domaine contient des value objects (DOI, ORCID, …) et
des modèles JSONB, mais pas d'entités au sens DDD. Passer à de vraies
entités `Person`, `Publication`, `Structure` avec identité + invariants
devient intéressant quand émergent des règles complexes (ex. un idHAL
ne peut être associé qu'à un seul compte actif). Pas urgent.

### 1.5 Value objects supplémentaires
Ajouter au fur et à mesure : `ROR`, `RNSR` (identifiants de structure),
`ISSN` / `eISSN` (journaux) — dès qu'un besoin de validation ou de
normalisation explicite émerge.

### 1.6 Inversion de dépendance complète
- [x] **Extraction SQL des scripts pipeline vers `infrastructure/db/queries/`**
  (branche `feature/pipeline-di`, 13 commits atomiques). 153 `cur.execute`
  dispersés dans `application/pipeline/*` → 9 restants (tous des SAVEPOINT
  de contrôle de transaction). Nouveaux modules par sous-dossier :
  `countries`, `address_resolution`, `enrich`, `harvest`, `merge`,
  `publications_create` + `persons_create`, `authorships_build` +
  `affiliations` + `name_forms`, `staging` + `normalize_{scanr,theses,
  openalex,wos,hal}`. Même pattern que §1.1 pour les routers : chaque
  orchestrateur pipeline ne contient plus que de la logique Python pure
  (parsing, boucles, conditions métier) et délègue la persistance.
- [x] **Injection canonique via ports (Protocol) côté pipeline**
  (branche `feature/pipeline-ports`, 13 commits atomiques countries →
  normalize/hal). Orchestrateurs `application/pipeline/*` dépendent de
  ports (`application/ports/*`) au lieu d'importer `infrastructure.db.
  queries.*` directement. Adapters PostgreSQL dans `infrastructure/db/
  queries/*` (déjà en place depuis §1.6 partie 1) implémentent ces
  Protocols. Composition roots dans `interfaces/cli/pipeline/*` : chaque
  entry point CLI instancie les `Pg*Queries` et les injecte dans
  l'orchestrateur. `run_pipeline.py` appelle les orchestrateurs via
  imports Python directs. `logger` également threadé en param dans les
  5 `normalize_*` (pattern cohérent, plus aucun `setup_logger` module-
  level dans `application/`). Zéro import `infrastructure.db.queries`
  depuis `application/` : §1.7 peut passer en `layered` strict.
- [ ] Reste côté API : factories FastAPI `Depends` pour injecter les
  query services dans les routers (équivalent unit-of-work). Mécanique
  si la couverture de tests devient un objectif.

### 1.7 Verrouiller les acquis : import-linter
- [x] Contrats initiaux dans `pyproject.toml` (`[tool.importlinter]`),
  vérifiés en pre-commit + CI. 4 contrats `forbidden` qui verrouillent :
  (1) domain = noyau pur, (2) application ↛ interfaces,
  (3) infrastructure ↛ interfaces, (4) infrastructure ↛ application.
- [ ] Durcir en contrat `layered` strict — débloqué par §1.6 (ports
  posés côté pipeline, plus aucun import `infrastructure.db.queries`
  depuis `application/`). Prochain chantier.

### 1.8 Audit périodique
Parcours régulier pour repérer : SQL mal placé, dépendances dans le
mauvais sens, logique métier qui a migré dans infrastructure, code
dupliqué entre agrégats.

---

## Chantier qualité du code : maintenabilité, auditabilité, scalabilité

### 2.1 Tooling & CI
- [x] **Pre-commit hook** : ruff check (+ auto-fix) + ruff format
  + checks basiques (trailing whitespace, EOF, YAML/TOML, merge conflicts)
  + lint-imports (contrats DDD) + pytest unitaires (tests/unit/).
  Config dans `.pre-commit-config.yaml`.
- [x] Mypy strict en CI + pre-commit : `check_untyped_defs` +
  `disallow_untyped_defs` globalement activés. Toutes les fonctions
  sont annotées (domain, application, infrastructure, interfaces,
  run_pipeline) — beaucoup en `Any` pragmatique pour les params DB
  (`cur: Any`, `conn: Any`) et les helpers internes. Les nouveaux
  ajouts seront donc typés par défaut.
- [x] Couverture `pytest --cov` en CI avec seuil à **41%**
  (`fail_under` dans `[tool.coverage.report]`). Baseline actuelle : 42%
  hors `interfaces/cli/*` (scripts one-shot exclus de la mesure, car
  leur logique utile est factorisée dans application/infrastructure et
  testée là). À faire remonter par paliers : +5% quand chantier §1.1
  sera fait (nouveaux tests de caractérisation sur les routers).

### 2.2 Organisation des tests
- [x] Réorganisation `tests/unit/` + `tests/integration/`, sous-dossiers
  par couche (`domain/`, `application/`, `pipeline/`, `interfaces/`).
  274 unit en ~1.3s, 326 integration en ~26s.
- [x] Conftest splitté : `tests/conftest.py` pour le cross-cutting
  (mock logger, caches), `tests/integration/conftest.py` pour le
  setup BDD + fixture `db`.
- [x] Hook pre-commit `pytest-unit` qui lance uniquement `tests/unit/`.
  CI fait les deux en étapes séparées.
- [x] Tests de caractérisation sur les routers critiques (publications,
  persons, pub_stats) avant l'extraction SQL §1.1. 63 tests qui exercent
  les combinaisons de filtres et la construction dynamique des WHERE/ORDER BY.
  Seuil couverture remonté à 44%.

### 2.3 Dette externe / dépendances
- [x] **Source unique des dépendances** : `[project.dependencies]` +
  `[project.optional-dependencies.dev]` dans `pyproject.toml`
  (ex-`requirements.txt` supprimé, installation via `pip install ".[dev]"`)
- [ ] **Lockfile** des dépendances : `uv.lock` ou `poetry.lock` (prochaine étape
  pour figer les versions transitives)
- [x] `deptry` pour repérer les paquets installés mais inutilisés
- [x] `pip-audit` pour les vulnérabilités connues (à ajouter en CI ensuite)
- Version Python supportée documentée et alignée avec prod DSI

### 2.4 Migrations BDD : évaluer Alembic
- [x] **Évaluation** : ne pas migrer. Raisons :
  1. Le système maison (`migrate.py`, 120 lignes) a géré 70+ migrations
     historiques (pré-squashing) + 6 depuis, 0 downgrade utilisé.
  2. La génération auto — vrai gain d'Alembic — nécessite SQLAlchemy,
     qui demanderait un chantier disproportionné (pas sur la roadmap).
  3. Pour la DSI : le système maison est lisible en 2 min. Alembic
     n'apporterait qu'un standard connu, sans gain fonctionnel prouvé.
- [ ] Si downgrades deviennent utiles : convention `NNN_down.sql`
  optionnelle, ~10 lignes à ajouter dans `migrate.py`.

### 2.5 Code hygiene
- [x] **Complexité cyclomatique** : seuil ruff C901 à **15** après
  décomposition de 4 fonctions (`publications_facets` 25→<10 via
  `_PublicationFacetsBuilder`, `_build_list_conditions` 17→<15 via
  3 helpers, `refresh_from_sources` 24→<15 via extraction des helpers
  au module-level, `export_publications_csv` 23→<15 via
  `_build_export_conditions`). Prochaine cible 10 : demande encore
  ~9 fonctions à décomposer, rendement décroissant.
- [x] **Mypy** strict : `check_untyped_defs` + `disallow_untyped_defs`
  globalement activés, 0 erreur. Durcissement futur possible : remplacer
  les `Any` pragmatiques par des types plus précis (en particulier sur
  les signatures métier — les `cur: Any` pour psycopg2 peuvent rester).
- [x] **Dédoublonnage** : audit via pylint `duplicate-code`. Résultats :
  `harvest_hal_orcids.py` supprimé (orphelin, superseded par
  `harvest_hal_identifiers.py`). Les autres duplications détectées
  (forme des dicts `extract_pub_metadata`) sont liées à la logique
  source-spécifique, pas factorisables sans perte.
- [x] **Magic values** : `OA_CLOSED_STATUSES` centralisée aux côtés
  d'`OA_OPEN_STATUSES` dans `filters.py`, +helper `_sql_list()` pour
  injection SQL littérale. 7 occurrences inline remplacées. Les autres
  constantes métier (`doc_types`, `sources`, `authorship_roles`) sont
  déjà factorisées dans `domain/`.

### 2.6 Documentation et DX
- [ ] **README** : permettre à une nouvelle personne (ou toi-dans-2-ans)
  de monter un env de dev en 15 minutes, depuis zéro
- [ ] **CONTRIBUTING.md** (ou équivalent) : "comment ajouter une nouvelle
  source de données", "comment ajouter une phase au pipeline",
  "comment ajouter un endpoint"
- [ ] **Schéma d'architecture versionné** dans `docs/` : diagramme des
  couches, liste des agrégats et de leurs repositories, flux du pipeline
- [ ] **Descriptions OpenAPI** : Pydantic permet de les générer gratuitement
  depuis les modèles — à compléter endpoint par endpoint

### 2.7 Frontend
- [ ] Audit de la séparation stores vs composants (est-ce que la logique
  métier se fait dans les composants ou dans des stores dédiés ?)
- [ ] Centralisation des appels API dans un client dédié (`interfaces/frontend/src/lib/api/`)
- [ ] **Types TypeScript générés depuis OpenAPI** plutôt que réécrits
  manuellement (évite la dérive silencieuse backend/front)

### 2.8 Observabilité et robustesse production
- [ ] **Alerting sur échec pipeline** (email ou webhook)
- [ ] **Checks automatiques post-pipeline** : comptages, orphelins,
  anomalies (type tests de caractérisation sur les données produites)
- [ ] Dashboard métriques (temps de réponse, pool DB, taux d'erreur) —
  partiellement en place, à consolider
- [ ] Structured logs (JSON) prêts pour agrégateur externe (Loki / ELK
  selon ce qu'installera la DSI)

### 2.9 Audits transversaux périodiques
- **12-factor app** : pointeurs dans *Beyond the Twelve-Factor App*
  (Kevin Hoffman, 2016) qui revisite les 12 facteurs originaux et en
  ajoute 3 à l'ère Kubernetes
- **SOLID** sur le code existant : détecter les violations (surtout ISP
  et DIP qui sont les plus courantes quand on vient d'une base procédurale)
- **Revue code dupliqué / uniformisation** : ex. les fonctions de
  compatibilité de noms existent en deux versions (Python dans
  `domain/names.py`, SQL dans `admin_person_duplicates.py`) — à
  unifier (cf. `TODO_CLAUDE.md`)

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
## A explorer:

**SQLAlchemy Core** (pas ORM), pour la construction dynamique de requêtes. SQLAlchemy a deux couches : Core (query builder, paramétrage sûr, abstraction du dialecte) et ORM (mapping objets-tables). Tu peux utiliser Core sans ORM : tu écris des requêtes via son API Python (select(...).where(...).order_by(...)) qui génèrent du SQL sûr et paramétré, mais tu n'introduis pas de couche ORM. C'est particulièrement utile pour les requêtes dynamiques avec filtres variables. Tes requêtes "statiques" peuvent rester en SQL brut pour la clarté.
**Alembic** pour les migrations. Indépendant de l'usage d'ORM. Tu continues à écrire ton schéma en SQL brut si tu veux, mais tu versionnes et orchestres les migrations avec Alembic. Gain de maintenance réel, coût d'adoption modéré.
**psycopg3** avec des curseurs typés, si tu n'y es pas déjà. Psycopg3 supporte bien les Row classes typées et les dict_row, ce qui rend ton SQL brut plus sûr à manipuler côté Python sans introduire un ORM.

## Items évalués et retirés

*(rien à retirer pour l'instant — cette section sert de cimetière pour
les idées qu'on aura abandonnées en le justifiant)*
