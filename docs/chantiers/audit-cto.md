# Audit "DSI qui reprend le projet"
Commencé le 2026-05-05

Vue extérieure du projet, comme si une DSI d'université le récupérait
sans contexte. Constats classés en 4 sections (confusion, scalabilité,
choix qu'on regrettera, dette cachée), puis transformés en chantiers
phasés.

**Cadre de la transmission** :
- la reprise DSI n'est pas imminente, un chantier "réécriture
  intégrale de la doc" est prévu en dernière étape ;
- le frontend actuel **survivra** comme outil de gestion interne
  (la DSI réécrira un frontend public exposé dans le SID/ENT) ;
- l'app est mono-utilisateur de bout en bout par choix : la couche
  auth/permissions sera réécrite par la DSI, pas étendue à partir de
  l'existant ;
- les trois TODO en parallèle (TODO_LAURA, TODO_CLAUDE, ROADMAP)
  seront fusionnés en un backlog unique avant transmission.

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
  18 routers importent `infrastructure.db.queries.*` et
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
  `infrastructure/db/queries/` mais le couplage à un cursor psycopg3
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
chantiers, à instruire après décisions de Phase 1. Phase 3 = dette en
continu, au fil de l'eau. Phase 4 = avant transmission DSI.

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
  Restent légitimement : `ROADMAP.md`, `docs/chantiers/audit-cto.md`,
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

- [ ] **Pipeline : `subprocess`, imports, ou hybride ?**

  Trois options identifiées après discussion :

  - **A — Statu quo** : `run_pipeline.py` lance les phases via
    `subprocess.run`. Simple à comprendre (1 phase = 1 commande
    shell), isolation mémoire totale entre phases, robuste aux
    crashes. Inconvénient principal : `pipeline_metrics.py` parse
    les logs des subprocess avec des regex pour reconstituer les
    rapports `/admin/pipeline` — un changement de format de log
    casse les rapports silencieusement.

  - **A' — Subprocess + métriques structurées** *(recommandation
    actuelle)* : on garde `subprocess` (donc tous les avantages
    d'isolation et de simplicité d'A), mais chaque phase écrit en
    fin de run un fichier JSON de métriques à un chemin connu de
    l'orchestrateur (ex. `logs/metrics/<phase>.json`). L'orchestrateur
    lit ces JSON au lieu de parser les logs. Helper unique
    `write_metrics({phase, duration_s, inserted, updated, errors})`
    appelé en fin de chaque phase. Si une phase ne produit pas son
    JSON, c'est une erreur explicite. Estimation : ~50 lignes pour
    le helper + 1 appel par phase. Migration incrémentale possible
    (1 phase à la fois).

  - **B — Imports + appels de fonction** : `run_pipeline.py`
    importe les fonctions `run()` des phases et les appelle
    directement, dans un seul process Python. Les CLI dans
    `interfaces/cli/pipeline/*` restent comme entry points fins
    (parse argparse + appelle `run()`), donc lancer une phase
    isolément reste possible. Gains : exceptions Python typées,
    debugging cross-phase au pdb, testabilité directe. Pertes :
    isolation mémoire (un parsing TEI HAL lourd peut grever la
    suite), discipline à tenir (pas de `sys.exit()` dans les
    phases, gestion propre des connexions DB partagées).

  **Pourquoi A' plutôt que B aujourd'hui** : les vrais bénéfices
  de B (perf, transactions cross-phase) sont marginaux pour ce
  pipeline (idempotence par phase déjà acquise, durée totale en
  minutes). Le seul vrai pain point d'A est le parsing fragile
  des logs, et A' le règle sans toucher à la structure
  d'exécution. B reste compatible avec une migration future si
  un besoin émerge (testabilité poussée, debugging récurrent).

  **Indépendance vis-à-vis du chantier sync/async** : oui, les
  deux décisions sont orthogonales. A et A' sont neutres
  vis-à-vis du sync/async. B s'intègre naturellement avec une
  migration async, mais n'en dépend pas.

  **Décision attendue** : confirmer A' et lister les phases à
  migrer (1 par 1), ou rouvrir le débat. Document court à écrire
  dans `docs/chantiers/` quand le chantier sera lancé.
- [ ] **Sync + async dupliqué : industrialiser ou unifier ?**
  - Option A : tout passer en async (le pipeline aussi) → simplifie
    mais alourdit les scripts CLI
  - Option B : unifier via une seule classe générique paramétrée par
    `cur` ou via codegen → garde les deux, supprime la duplication
  - Option C : assumer la duplication, ajouter un test qui vérifie
    le parallélisme des deux familles de repos
  - **Décision attendue** : 1 page comparant les 3 options
- [ ] **Position des "ports"** : `application/ports/` vs
  `domain/ports/`, critère final ? Décider une bonne fois et figer
  la convention dans `docs/architecture.md`.
- [ ] **SQLAlchemy Core : on adopte ou on ferme la porte ?**
  - Si oui : démarrer un chantier de migration des queries (~30
    fichiers) avec un plan de découpage
  - Si non : retirer la mention "à explorer" de la ROADMAP
- [ ] **Règle "routers ⊥ infrastructure" : on l'applique ou on la
  retire ?**
  - Si on l'applique : §1.6 ROADMAP (factories FastAPI `Depends`)
    devient prioritaire et `import-linter` doit être durci pour
    l'imposer
  - Si on la retire : virer la règle 4 de `docs/architecture.md` et
    assumer que les routers sont des composition roots

### Phase 2 — Implémenter les décisions structurantes

À démarrer une fois Phase 1 tranchée. Ce sont les gros chantiers,
chacun mérite son fichier dans `docs/chantiers/`.

- [ ] **Refonte pipeline** selon décision Phase 1 (subprocess vs
  imports)
- [ ] **Convergence sync/async** selon décision Phase 1
- [ ] **§1.6 ROADMAP — DI complète FastAPI** si décision = router ⊥
  infrastructure
- [ ] **Migration SQLAlchemy Core** si décision = adoption

### Phase 3 — Dette technique en continu

Pas un sprint, à traiter au fil de l'eau quand on touche aux
fichiers concernés.

- [ ] **`application/audit.py` doit passer par un repository** :
  créer un `AuditRepository` (port + adapter Pg) au lieu du
  `cur.execute` direct, pour rétablir la règle DDD
- [ ] **Encapsuler les `SAVEPOINT`** : ajouter une méthode
  `with_savepoint(name)` aux ports concernés (ou un context manager
  séparé), supprimer les 7 `cur.execute("SAVEPOINT ...")` inline
  dans `application/pipeline/`
- [ ] **Chasser les `Any`** : par fichier modifié, typer
  progressivement les `cur: Any` (créer un alias `Cursor`/
  `AsyncCursor` à l'entrée des modules)
- [ ] **Pool DB** : porter `db_pool_max` à 20 ou 30 en prod (selon
  benchmark), documenter le ratio max/min recommandé
- [ ] **`prepare_threshold`** : auditer les query builders
  dynamiques (`_PublicationFacetsBuilder`, `filters.py`), passer à
  `prepare_threshold=5` (défaut) si memory leak observé, ou
  désactiver le prepare sur les requêtes dynamiques
- [ ] **Inventaire `interfaces/cli/`** : ajouter en tête de chaque
  script un commentaire `# STATUS: oneshot | recurring | deprecated`
  + date. Déplacer en `interfaces/cli/oneshots/` les `oneshot`,
  garder les `recurring` à la racine, supprimer les `deprecated`
  trimestriellement
- [ ] **Référencer `processing/*` retiré dans `docs/donnees.md`** :
  remplacer par `application/pipeline/normalize/*` (à intégrer dans
  le chantier "réécriture doc" final)
- [ ] **Background tasks pour endpoints longs** (TODO_CLAUDE déjà
  cadré) : implémenter le seuil + 202, prévoir le swap vers une vraie
  queue (pg-boss ?) en notation interne

### Phase 4 — Avant transmission DSI

Dernière passe avant de remettre le dossier. Plusieurs items déjà
prévus hors audit ; rappel ici pour exhaustivité.

- [ ] **Réécriture intégrale de la doc** (déjà prévu) — intégrer
  les corrections de chemins morts (`processing/*`,
  `cross_import_<source>.py`, `harvest_hal_identifiers`,
  `monthly` → `full`, etc.)
- [ ] **Backlog unifié** (déjà prévu par Laura) — fusionner
  TODO_LAURA + TODO_CLAUDE + ROADMAP en un seul fichier catégorisé
  (qualité données / dette technique / DSI-blockers / nice-to-have)
- [ ] **Auth : préparer le terrain pour le CAS DSI** sans
  surinvestir
  - [ ] Documenter dans un fichier dédié l'attendu côté DSI (CAS,
    multi-user, rôles), pour qu'ils sachent quoi remplacer
  - [ ] S'assurer que `audit_log.user_id` accepte une string opaque
    (ce qui sera vrai du `eppn` CAS)
  - [ ] Ne PAS faire de POC mock CAS : Laura est la seule
    utilisatrice, le bcrypt actuel suffit jusqu'à la transmission
- [ ] **README explicite sur le devenir du frontend** : "outil de
  gestion interne, restera maintenu en parallèle du futur frontend
  public DSI"
- [ ] **Tests E2E Playwright** sur 2-3 parcours critiques (déjà dans
  ROADMAP §2.7.5) — utile puisque le frontend est gardé
- [ ] **Owner explicite** : ajouter un fichier `MAINTAINERS.md`
  (ou équivalent) avec le contact unique (Laura) et l'historique de
  reprise prévu côté DSI

---

## Ce qui sort du périmètre

Décisions actées avant cet audit, listées pour mémoire :

- ~~Auth multi-user / mock CAS~~ : rewrite DSI assumé.
- ~~Fusion des trois TODO~~ : Laura le fait dans Phase 4.
- ~~Réécriture doc~~ : chantier dédié en Phase 4, n'agit pas avant.
- ~~"Acter la fin du frontend"~~ : faux problème — le frontend
  survit comme outil interne, on continue d'investir dedans (tests
  composables, accessibilité, Playwright).
- ~~Désigner un owner~~ : c'est Laura.
