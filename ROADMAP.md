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
Aujourd'hui `application/` importe des factories depuis
`infrastructure.repositories`. Pour une inversion canonique, injecter
les repositories via FastAPI `Depends` (et équivalent côté pipeline).
Gain concret : tests unitaires de services sans base. À faire si la
couverture de tests devient un objectif.

### 1.7 Verrouiller les acquis : import-linter
- [x] Contrats initiaux dans `pyproject.toml` (`[tool.importlinter]`),
  vérifiés en pre-commit + CI. 4 contrats `forbidden` qui verrouillent :
  (1) domain = noyau pur, (2) application ↛ interfaces,
  (3) infrastructure ↛ interfaces, (4) infrastructure ↛ application.
- [ ] Durcir en contrat `layered` strict — bloqué par §1.6 (DI complète) :
  63 imports `application → infrastructure.*` à retirer avant. Revisiter
  quand §1.6 avance.

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
Le système de migrations maison (`infrastructure/db/migrate.py`)
fonctionne mais ne gère pas les downgrades, ni la génération automatique
de migration depuis un schéma Python. Alembic est le standard Python
pour ça. Évaluer migration coût/bénéfice.

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

## Items évalués et retirés

*(rien à retirer pour l'instant — cette section sert de cimetière pour
les idées qu'on aura abandonnées en le justifiant)*
