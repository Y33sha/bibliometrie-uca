# Audit "DSI qui reprend le projet"

Commencé le 2026-05-05 - Terminé le 2026-05-17

Vue extérieure du projet, comme si une DSI d'université le récupérait sans contexte. Constats classés en 4 sections (confusion, scalabilité, choix qu'on regrettera, dette cachée), puis transformés en chantiers phasés.

**Cadre de la transmission** :
- la reprise DSI n'est pas imminente, un chantier "réécriture intégrale de la doc" est prévu en dernière étape ;
- le frontend actuel **survivra** comme outil de gestion interne (la DSI réécrira un frontend public exposé dans le SID/ENT) ;
- l'app est mono-utilisateur de bout en bout par choix : la couche auth/permissions sera réécrite par la DSI, pas étendue à partir de l'existant.

Ces points sortent donc du périmètre des chantiers ci-dessous.

---

## Constats

### 1. Ce qui est confus ou non justifié

- **Doc qui contredit le code** : `README.md` dit `psycopg2` alors
  que c'est `psycopg3` partout (cf. `pyproject.toml`). Couverture
  annoncée à 49 % dans le README vs 62 % dans `pyproject.toml`. Le
  README mentionne `pg_restore -U lalecoz` en dur — username perso
  qui n'a rien à faire dans la doc utilisateur (ni en default de
  `infrastructure/settings.py`).
- **Architecture aspirationnelle** : `docs/architecture.md` énonce la
  règle 4 (« les routers ne doivent pas importer `infrastructure/`
  directement »), puis admet aussitôt que c'est non atteint. Tous les
  18 routers importent `infrastructure.queries.*` et
  `infrastructure.repositories.*`. Lecteur trompé. Soit on l'applique,
  soit on l'enlève — l'entre-deux est pire que pas de règle.
- **Mode `weekly` exclut WoS** (`run_pipeline.py`) sans qu'aucun
  commentaire n'explique pourquoi (limite contractuelle ? coût ?
  volume ?). Aucune trace dans `domain/pipeline_modes.py`.
- **Périmètre des "ports" ambigu** : TODO_LAURA dit "vérifier si
  certains ports ne seraient pas mieux placés dans application/" —
  question d'architecture qui aurait dû être tranchée avant de créer
  7 repositories × 2 (sync + async).

### 2. L'architecture tient-elle à l'échelle ?

- **Pipeline orchestré par `subprocess`** (`run_pipeline.py`,
  `run_python(...)`). Les phases sont déjà des modules importables
  dans `application/pipeline/*`, mais `run_pipeline.py` les lance en
  sous-processus séparés. Coûts : ~500 ms de cold-start × ~15 phases ×
  N sources, pas de transaction transverse, pas d'état partagé, pas
  de gestion d'erreur typée, logs scindés sur N processus,
  traçabilité fragile (le rapport pipeline lit la stdout). 37 Ko de
  job control reproduit en Python. **L'élément le plus inhabituel du
  projet** — la DSI ne va pas comprendre pourquoi.
- **Sync ET async dupliqués partout** : 7 repositories × 2 = 14
  fichiers quasi identiques (1425 lignes pour le seul agrégat
  Person). Décision défendable (pipeline sync, API async), mais
  chaque évolution du modèle = double modif, double risque de drift.
- **Pool DB `min=2 max=10`** : trop étroit dès que la SPA admin
  chargera plusieurs facettes en parallèle. Si un appel sync se
  cache dans un endpoint async, saturation immédiate (TODO_CLAUDE
  s'en inquiète déjà).
- **`schema.sql` régénéré par `pg_dump`** à chaque migration. Le
  fichier versionné dépend de la version locale de `pg_dump` du dev :
  diffs énormes sans changement réel + commits "schema.sql" pollués
  + conflits de merge inutiles.
- **Fuite du curseur partout** : toutes les fonctions de
  `application/` ont `cur: Any` en premier paramètre. Le DDD
  documenté est cosmétique — on a déplacé le SQL dans
  `infrastructure/queries/` mais le couplage à un cursor psycopg3
  persiste partout dans la couche métier. Vraie isolation =
  `repo.find_by_doi(doi)`, pas `repo.find_by_doi(cur, doi)`.

### 3. Choix qu'on regrettera dans 18 mois

- **Pas de queue de jobs** : TODO_CLAUDE prévoit `BackgroundTasks`
  FastAPI pour les opérations longues — in-process, perdu au
  restart, sans retry, sans visibilité. À la 2ème panne =
  installation de Celery / dramatiq / pg-boss. Mieux vaut anticiper.
- **40 scripts CLI dans `interfaces/cli/`** sans marqueur de durée
  de vie. Lesquels sont obsolètes ? Sans inventaire daté + flag
  "obsolète" + suppression au bout de N mois, ça devient un cimetière
  qu'aucun nouveau dev n'osera nettoyer. Exclu de la couverture, donc
  on ne sait même pas si ça compile.
- **SQLAlchemy Core "à explorer"** dans la ROADMAP : soit on tranche
  maintenant, soit jamais. Si on l'introduit dans 6 mois, c'est ~30
  fichiers de queries + 14 repositories à migrer.
- **Schéma figé sur 5 sources mais TODO_LAURA en envisage 5 de plus**
  (ArXiv, Pubmed, INPI, ORCID, Sudoc, IdRef). L'enum `source_type`
  PostgreSQL impose une migration `ALTER TYPE ADD VALUE` à chaque
  ajout, et chaque source = 1 module hardcodé partout
  (`normalize_<src>.py`, `extract_<src>.py`, branches dans le
  pipeline). À 10 sources, le projet devient viscoélastique.

### 4. Où est la dette cachée

- **`application/audit.py` viole la règle DDD documentée** : il
  exécute du SQL direct (`cur.execute("INSERT INTO audit_log...")`)
  au cœur de la couche application. Le linter ne contrôle pas ce
  niveau. C'est *l'audit* — la fonction qui doit tracer toutes les
  opérations sensibles. Si elle déroge, tout le reste peut.
- **`cur.execute("SAVEPOINT ...")` dans `application/pipeline/`**
  (7 occurrences) : les ports ne savent pas gérer les transactions ;
  on retombe sur du SQL inline.
- **`Any` partout** : `disallow_untyped_defs = true` est neutralisé
  par `cur: Any`, `**kw: Any`, `-> Any`. mypy en strict ne vérifie
  quasiment rien dans les couches haute. Décoration de discipline.
- **`prepare_threshold=1`** côté pool async : prépare *toutes* les
  requêtes dès le 1er appel. Avec des query builders dynamiques
  (`_PublicationFacetsBuilder`), accumulation de prepared statements
  qui ne se réutilisent jamais → memory leak progressif côté
  PostgreSQL.
- **JSONB partout** (`raw_data`, `source_ids`, `payload audit`,
  `api_ids`, `meta`) : schéma faible, queries fragiles dès qu'une
  API source modifie sa structure. Pas de validation à l'entrée.
- **Commentaires `# §X.Y de la ROADMAP` dans le code** : couplage
  entre code et ROADMAP. Quand la ROADMAP sera réécrite, ces refs
  deviennent du bruit. Mémoire prise mais consigne pas appliquée.
- **`interfaces/cli/` racine vs `interfaces/cli/pipeline/`** :
  composition roots et scripts éphémères mélangés. Pas de
  séparation `cli/oneshots/` vs `cli/recurring/`.

### 5. Ce qui est solide

- Couches DDD vérifiées par `import-linter` sur les règles 1-3.
- `domain/` pur (DOI, ORCID, IdRef avec parsing/validation),
  fonctions testables sans I/O.
- Migrations SQL versionnées dans `schema_migrations`, simple et
  lisible.
- Audit log avec `ContextVar` async-local — propre.
- Exception handlers FastAPI qui mappent `domain.errors` → HTTP : la
  couche métier ne connaît pas HTTP.
- Pre-commit hooks (ruff, mypy, lint-imports, pytest unit).
- Pydantic Settings pour la config.
- Idempotence des phases pipeline documentée.

---

## Phasage des chantiers

Phasage pensé pour un seul dev (Laura). Phase 0 et 1 = priorités
hautes, à faire avant de toucher à la dette. Phase 2 = gros
chantiers, à instruire après décisions de Phase 1. Phase 3 = items
hétérogènes (quick-wins ciblés ou exports vers chantiers dédiés ;
pas de catégorie fourre-tout « en continu »). Phase 4 = avant
transmission DSI.

---

### Phase 0 — Hygiène immédiate (peu coûteux)

À caser entre deux chantiers de fond. Coût faible, gain de cohérence
immédiat.

- [x] **Aligner README et code**
  - [x] `README.md` : `psycopg2` → `psycopg3`
  - [x] `README.md` : couverture 49 % → 62 %
  - [x] `README.md` : retirer `lalecoz` des exemples `pg_restore`
    (remplacé par `$POSTGRES_USER` / `$DB_USER`)
  - [x] `infrastructure/settings.py` : `db_user` rendu obligatoire
    (sans default), cohérent avec `db_password`
- [x] **Reliquats `lalecoz` nettoyés**
  - [x] `docs/exploitation.md` : `pg_restore`/`pg_dump` →
    `$DB_USER` / `$POSTGRES_USER`, crontab user → "utilisateur de
    service dédié au pipeline"
  - [x] `tests/integration/conftest.py`,
    `tests/integration/interfaces/conftest.py` et 5 fichiers de
    tests : fallback `os.environ.get("DB_USER", "lalecoz")` →
    `os.environ["DB_USER"]` (KeyError explicite si manquant,
    cohérent avec `settings.py`)
- [x] **Documenter l'exclusion WoS du mode `weekly`** : commentaire
  dans `domain/pipeline_modes.py` (crédit API contractuel 50 000 full
  records/an) + note dans `docs/exploitation.md` (sous le tableau cron)
- [x] **Nettoyer les `# §X.Y` du code** : toutes les références à la
  ROADMAP / aux phases de migration retirées des docstrings et
  commentaires Python + `pyproject.toml`. Reformulations intemporelles
  (« Variante async de X » au lieu de « Variante async de X (§2.12) »,
  « principe ISP » au lieu de « depuis §2.9.ISP », etc.).
  Restent légitimement : `docs/chantiers/audit-cto.md`,
  `docs/architecture.md` (réécrit en Phase 4).
- [x] **Décorréler `schema.sql` du flow de migration** : `migrate.py`
  ne régénère plus automatiquement `schema.sql` à chaque migration. Le
  fichier reste versionné comme snapshot descriptif (lecture humaine),
  pas comme source de vérité ni pour bootstrap. Sur une base vide,
  `migrate.py` applique toutes les migrations dans l'ordre. Nouvelle
  commande `--dump-schema` pour rafraîchir le snapshot manuellement
  (à faire après une série de migrations significatives ou au moment
  d'un squash). README et docs/exploitation.md adaptés.

### Phase 1 — Décisions structurantes (à trancher avant de coder)

Ces choix dimensionnent les chantiers suivants. Tant qu'ils ne sont
pas tranchés, toute évolution amplifie la dette.

- [x] **Pipeline : sweep `subprocess` → imports + retour direct** — décision actée 2026-05-16. État de départ hybride : 12 phases déjà en import direct dans `run_pipeline.py` (via les helpers `_run_*`), 10 invocations encore en `subprocess.run` (les 5 extracteurs + `refetch_truncated`, `fetch_missing_hal_id`, `fetch_missing_doi`, `detect_address_countries`, `suggest_address_countries`). Cible : chaque script restant expose `run(...) -> Metrics` importable, l'orchestrateur appelle des fonctions et reçoit les métriques typées directement (pas de JSON intermédiaire ni de parsing de logs). Sweep rapatrié comme phase préalable du chantier observabilité, dont il est de toute façon le pré-requis. Voir [`CODE_observabilite-robustesse-pipeline.md`](CODE_observabilite-robustesse-pipeline.md).

- [x] **Sync + async dupliqué : décision actée** — option D retenue
  (tout sync + threadpool FastAPI), implémentation reportée au
  chantier dédié. Voir
  [`docs/chantiers/sync-async-deduplication.md`](sync-async-deduplication.md)
  pour le raisonnement complet (4 options évaluées, profil d'usage
  cadré, plan d'implémentation en 4 phases, points de vigilance,
  réversibilité). À planifier après les autres décisions Phase 1
  pour ne pas mélanger les chantiers.

- [x] **Position des "ports" : décision actée et exécutée
  (2026-05-06)** — règle des 3 critères figée dans
  `docs/architecture.md` (section "Règle de placement des ports").
  Chantier `docs/chantiers/ports-cleanup.md` terminé :
  `structure_repository` ne fuite plus de fragments SQL dans son
  contrat (refactor `update_*_fields` → `fields: dict`), et
  `config_repository` a été scindé en `application/ports/repositories/perimeter_repository`
  (agrégat) + `application/ports/config` (port AsyncConfigStore pour
  la table clé/valeur).

- [x] **SQLAlchemy Core : décision actée (adoption), chantier
  démarré le 2026-05-06** — adoption retenue après reformulation
  « si on partait de zéro aujourd'hui, est-ce qu'on l'adopterait ? ».
  Voir [`docs/chantiers/sqlalchemy-core-adoption.md`](sqlalchemy-core-adoption.md)
  pour le périmètre, le phasage (5 phases, démarrer par un POC sur
  un module pilote) et les décisions de cadrage (Core only, pas
  d'ORM ; AsyncEngine de bout en bout ; MetaData explicite à
  valider en phase 0). La porte vers Alembic reste ouverte et sera
  réévaluée à la fin du chantier en coût-bénéfice.

- [x] **Règle "routers ⊥ infrastructure" : on l'applique** —
  décision actée le 2026-05-06. Voir
  [`docs/chantiers/routers-di.md`](routers-di.md) pour le phasage
  (factories `Depends`, migration router par router, durcissement
  `import-linter` à la fin).

### Phase 2 — Implémenter les décisions structurantes

À démarrer une fois Phase 1 tranchée. Ce sont les gros chantiers,
chacun mérite son fichier dans `docs/chantiers/`.

- [x] **Refonte pipeline** — rapatriée dans [`CODE_observabilite-robustesse-pipeline.md`](CODE_observabilite-robustesse-pipeline.md) (Volet 0).
- [x] **Convergence sync/async** selon décision Phase 1
- [x] **§1.6 ROADMAP — DI complète FastAPI** : chantier
  [`routers-di.md`](routers-di.md) bouclé. Tous les routers admin
  reçoivent leurs dépendances via `Depends(...)` (factories dans
  `interfaces.api.async_deps`). Contract `import-linter` "Routers :
  pas d'import direct de infrastructure" verrouille la règle 4 côté
  API. Exceptions documentées : `auth` (settings), `admin_pipeline`
  (status filesystem), `docs` (PROJECT_ROOT) — pas de query/repo.
- [x] **Migration SQLAlchemy Core** si décision = adoption

### Phase 3 — Dette technique

Items hétérogènes : certains sont des quick-wins (typer un module,
mettre à jour une doc), d'autres méritent un chantier dédié (typage
généralisé, background tasks).

- [x] **`application/audit.py` doit passer par un repository** :
  port `AuditRepository`/`AsyncAuditRepository` dans
  `application/ports/repositories/audit_repository.py` (méthode `record_event`),
  adapters `infrastructure/repositories/audit_repository.py` et
  `async_audit_repository.py` (dispatch cur | Connection / AsyncConnection),
  factories dans `infrastructure/repositories/__init__.py`. Les 7
  services applicatifs émetteurs (`authorships`, `config`, `journals`,
  `persons`, `publishers`, `structures`, `publications`) reçoivent
  désormais un kwarg `audit_repo` optionnel (défaut `None`, no-op
  pour pipeline/CLI où `user_id` est absent de toute façon). Les
  routers admin câblent un vrai repo via `Depends(audit_repo)` dans
  `interfaces/api/async_deps.py`. `application/audit.py` n'a plus
  aucun SQL direct — règle DDD `application ⊥ infrastructure`
  rétablie.
- [x] **Encapsuler les `SAVEPOINT`** : context manager
  `application.pipeline._savepoint.savepoint(cur, name, *, on_rollback_failure=None)`.
  Appliqué aux 3 sites : `pipeline/normalize/base.py` (passe
  `self.conn.rollback` en fallback), `merge_pubs_by_hal_id.py`,
  `merge_pubs_by_nnt.py`. Les 7 `cur.execute("SAVEPOINT ...")` /
  RELEASE / ROLLBACK inline ont disparu. Helper côté application
  (pas infrastructure) pour respecter `application ⊥ infrastructure`.
- [x] **Chasser les `Any`** — chantier dédié à créer. `cur: Any`,
  `**kw: Any`, `-> Any` neutralisent mypy strict sur ~40-50 fichiers
  applicatifs. Touche : couches application + infrastructure +
  interfaces. Nécessite un alias `Cursor`/`AsyncCursor` central et
  passage par module.
- [x] **Pool DB** : `db_pool_max` passé à 30 (default `settings.py` +
  `.env.example`). Note opérationnelle ajoutée (ratio recommandé ~1:15,
  bumper à 50+ si TimeoutError côté pool, surveiller `pg_stat_activity`
  Postgres en parallèle). Pas de benchmark préalable — usage mono-utilisateur
  en dev, le 30 est défensif (cf. TODO_CLAUDE : « max=10 trop étroit dès
  que la SPA admin chargera plusieurs facettes en parallèle »).
- [x] **`prepare_threshold`** : retiré la valeur explicite `1` du
  pool async (`infrastructure/db/async_connection.py`) et de la
  fixture test (`tests/integration/interfaces/conftest.py`), retombé
  sur le défaut psycopg3 (= 5). Les builders dynamiques
  (`_PublicationFacetsBuilder`, `filters.py`) génèrent du SQL à
  haute cardinalité — chaque combinaison de filtres = entry
  prepared distincte côté Postgres, jamais évincée tant que la
  connexion vit, croissance non bornée. À 5, seules les requêtes
  vraiment répétées entrent dans le cache : hot paths (`find_by_doi`,
  `list publications`) atteignent 5 appels en quelques secondes,
  les variantes rares ne s'accumulent pas. Risque non observé en
  dev mono-utilisateur, fix défensif avant prod.
- [x] **Inventaire `interfaces/cli/`** : audit script par script
  réalisé le 2026-05-08. Racine vidée, 4 sous-dossiers organisés :
  `pipeline/` (phases pipeline), `dev/` (outils dev — `dump_openapi`,
  `generate_seed`, `refresh_hal_domain_labels`), `imports/` (RH +
  APC + Open APC), `maintenance/` (outils ad-hoc — fusions
  publications, merges manuels). Marqueur `# STATUS:` ajouté sur les
  scripts conservés (`recurring (dev)` / `recurring (imports)` /
  `oneshot` pour les ad-hoc). Une vingtaine de scripts deprecated
  supprimés (rattrapages historiques couverts par la pipeline ou les
  chantiers achevés). Migration SA Core des scripts conservés
  effectuée pour ceux qui ne dépendent pas des repos sync (les autres
  reportés au Lot 3.A du chantier sqla).

### Phase 4 — Avant transmission DSI

Dernière passe avant de remettre le dossier.

- [x] **Réécriture intégrale de la doc** (déjà prévu) — intégrer
  les corrections de chemins morts (`processing/*`,
  `cross_import_<source>.py`, `harvest_hal_identifiers`,
  `monthly` → `full`, etc.)
- [x] **Backlog unifié** — ROADMAP dissoute en fiches chantiers
  thématiques dans `docs/chantiers/` (préfixes METIER/DATA/CODE).
  TODO_CLAUDE résorbé ; TODO_LAURA conservé comme TODO personnel.

---

## Ce qui sort du périmètre

Décisions actées avant cet audit, listées pour mémoire :

- ~~Auth multi-user / mock CAS~~ : rewrite DSI assumé.
- ~~Réécriture doc~~ : chantier dédié en Phase 4, n'agit pas avant.
- ~~"Acter la fin du frontend"~~ : faux problème — le frontend
  survit comme outil interne, on continue d'investir dedans (tests
  composables, accessibilité, Playwright).
