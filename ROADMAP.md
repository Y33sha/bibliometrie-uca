# Roadmap transmission DSI

## Chantier transition DDD

La transition vers une architecture hexagonale est bien avancée : les
4 couches `domain/`, `application/`, `infrastructure/`, `interfaces/`
sont en place, les ports Protocol existent pour les 7 repositories,
le SQL est extrait des services. Ce qui reste :

### 1.1 Sortir le SQL qui traîne encore dans les routers
Plusieurs routers `interfaces/api/routers/` exécutent encore du SQL
direct (existence checks, lectures ad-hoc, construction de facettes).
À extraire vers des repositories read-only ou des query builders
dédiés. Attention aux routers lourds (`publications.py`, `persons.py`)
qui concentrent la construction dynamique des WHERE et des ORDER BY.

### 1.2 Factoriser la logique commune aux sources
Créer des classes abstraites `BaseExtractor` / `BaseNormalizer` dans
`infrastructure/sources/` pour isoler la boilerplate récurrente
(pagination, insertion staging, hash, idempotence). Chaque source
n'implémente plus que ses primitives (`build_query()`, `extract_id()`,
`extract_doi()`, …).

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
- [ ] Quand §1.1 sera faite (SQL hors routers), durcir en un contrat
  `layered` strict (interfaces > infrastructure > application > domain).
- [ ] Quand §1.6 sera faite (DI complète), retirer l'exception permettant
  à `application/` d'importer les factories de `infrastructure.repositories`.

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
- [ ] Couverture `pytest --cov` en CI avec seuil progressif (partir de
  la couverture actuelle, ne pas régresser)

### 2.2 Organisation des tests
- [x] Réorganisation `tests/unit/` + `tests/integration/`, sous-dossiers
  par couche (`domain/`, `application/`, `pipeline/`, `interfaces/`).
  274 unit en ~1.3s, 326 integration en ~26s.
- [x] Conftest splitté : `tests/conftest.py` pour le cross-cutting
  (mock logger, caches), `tests/integration/conftest.py` pour le
  setup BDD + fixture `db`.
- [x] Hook pre-commit `pytest-unit` qui lance uniquement `tests/unit/`.
  CI fait les deux en étapes séparées.
- [ ] Tests de caractérisation complémentaires sur les routers critiques

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
- [ ] **Complexité cyclomatique** : seuil actuel à 20 (ruff C901), faire
  descendre progressivement à 15 puis 10 en cassant les fonctions trop
  denses (typiquement les routers de facettes et `refresh_from_sources`)
- [x] **Mypy** strict : `check_untyped_defs` + `disallow_untyped_defs`
  globalement activés, 0 erreur. Durcissement futur possible : remplacer
  les `Any` pragmatiques par des types plus précis (en particulier sur
  les signatures métier — les `cur: Any` pour psycopg2 peuvent rester).
- [ ] **Dédoublonnage** : audit complet du code dupliqué (`radon` ou manuel)
  — notamment le SQL qui pouvait être factorisé depuis la fusion des
  tables sources, mais qui ne l'a pas été
- [ ] **Magic values** : systématiser les enums pour les constantes métier,
  les settings pour les valeurs de configuration

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
