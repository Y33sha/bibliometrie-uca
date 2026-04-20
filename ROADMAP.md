# Roadmap transmission DSI

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
- [ ] **Généraliser aux ~29 autres endpoints** (publishers, persons,
  publications, laboratories, structures, addresses…) : pour chaque
  endpoint, (A) ajouter un `XxxOut` Pydantic + `response_model`, (B)
  régénérer le schema, (C) remplacer l'interface locale dans le ou
  les composants qui la consomment. ~88 interfaces locales à
  éliminer progressivement.

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
