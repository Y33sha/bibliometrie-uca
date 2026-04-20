# Roadmap transmission DSI

## Chantier transition DDD

Architecture hexagonale en place : 4 couches `domain/`, `application/`,
`infrastructure/`, `interfaces/` ; ports Protocol pour les 7
repositories ; SQL extrait des services et des orchestrateurs pipeline.

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
- [ ] La logique de facettes dynamiques est dupliquée entre plusieurs
  routers (publications, persons, laboratoires). À factoriser dans un
  module dédié — typiquement un specification pattern ou un query
  builder spécialisé.

### 1.4 Entités riches dans le domaine
- [ ] Aujourd'hui le domaine contient des value objects (DOI, ORCID, …) et
  des modèles JSONB, mais pas d'entités au sens DDD. Passer à de vraies
  entités `Person`, `Publication`, `Structure` avec identité + invariants
  devient intéressant quand émergent des règles complexes (ex. un idHAL
  ne peut être associé qu'à un seul compte actif).

### 1.5 Value objects supplémentaires
Ajouter au fur et à mesure : `ROR`, `RNSR` (identifiants de structure),
`ISSN` / `eISSN` (journaux) — dès qu'un besoin de validation ou de
normalisation explicite émerge.

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

#### §1.7b — Lever les `ignore_imports` (grandfather clause)
Services applicatifs → ports/adapters : 7/7 repositories faits
(config, authorships, addresses, structures, journals, persons,
publications). Chaque nettoyage restant = une ligne retirée de
`ignore_imports` dans `pyproject.toml`.
- [ ] Pipeline normalize_* → déplacer ou porter les helpers infrastructure :
  `link_addresses` (4), `mark_staging_done` (5), `StepTimer` (2),
  `resolve_zenodo_doi`/`is_zenodo_doi` (2), `extract_nnt_from_openalex`/
  `is_theses_fr_source` (1).
- [ ] `application.authorships → infrastructure.perimeter.
  get_persons_structure_ids_list` (1) — cas isolé.

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
  `fail_under = 49`, baseline réelle ~49.7%. `interfaces/cli/*`
  exclu (scripts one-shot, logique utile testée via
  application/infrastructure). À faire remonter par paliers quand un
  chantier touche un module 0% (enrich, merge, harvest, queries/*).

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
- [x] **12-factor app** : pointeurs dans *Beyond the Twelve-Factor App*
  (Kevin Hoffman, 2016) qui revisite les 12 facteurs originaux et en
  ajoute 3 à l'ère Kubernetes
- [x] **SOLID** sur le code existant : détecter les violations (surtout ISP
  et DIP qui sont les plus courantes quand on vient d'une base procédurale)
- [x] **Revue code dupliqué / uniformisation** : ex. les fonctions de
  compatibilité de noms existent en deux versions (Python dans
  `domain/names.py`, SQL dans `admin_person_duplicates.py`) — à
  unifier si la logique diverge.

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

**psycopg3** avec des curseurs typés, si tu n'y es pas déjà. Psycopg3 supporte bien les Row classes typées et les dict_row, ce qui rend ton SQL brut plus sûr à manipuler côté Python sans introduire un ORM.

**environnement virtuel**?
