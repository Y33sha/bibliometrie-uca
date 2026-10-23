# Chantier — Conception du pipeline

## Contexte

Un diagnostic de `pipeline/` (208 modules) relève des problèmes de même nature dans tous les sous-paquets. Chaque sous-paquet suit ses propres conventions.

**SQL.** Au moins six formes coexistent :

- module `*_queries.py` ;
- module de requêtes sans suffixe : `author_grouping/queries.py`, `reconciliation/reconciliation.py`, `persons/matching.py`, `persons/name_forms.py`, `doi_prefixes.py`, `journals/journals.py` ;
- classe de requêtes dans le module de logique : `address_resolution.py`, `perimeter.py` ;
- constantes `text()` de module : `staging.py`, `failed_lookups.py`, `idref_resolution.py`, `hal/fetch_missing.py` ;
- classes sans état et classes qui reçoivent la connexion à la construction ;
- préfixe `Pg` sans port, suffixe `GatewayQueries`, mélange de SQLAlchemy Core et de `text()`.

`staging.py` suit trois formes à lui seul. `journals/journals.py` (842 lignes) contient le SQL de huit étapes distinctes.

**Dépendances.**

- Le noyau d'exécution (`node_runner.py`) importe `ingestion/common/parallel.py`, `ingestion/http/access_source.py` et `circuit_breaker.py`.
- `ingestion/` et `transformation/` s'importent dans les deux sens. L'outillage HTTP, général, est rangé sous `ingestion/`.
- Aucun contrat d'import ne fixe ces sens.
- Huit phases utilisent les globales `open_tx` et `log` au lieu du contexte de phase.

**Placement.** Des modules sont rangés selon leur premier appelant :

- `AddressMatcher` dans `address_resolution.py`, alors que `idref_resolution.py` et des scripts l'utilisent aussi ;
- l'accès API de chaque source, réparti entre `harvest.py`, `person_search.py`, `fetch_missing.py`, `fetch_stale.py` et `api.py` selon la source ;
- la lecture du payload, répartie sans règle entre `domain/sources/<source>.py`, `<source>/normalize.py` et `<source>/fields.py`.

D'autres modules réunissent des connaissances sans rapport :

- `staging.py` ;
- `runtime/config.py`, dont une moitié concerne les sources ;
- `common/normalize.py`, `fetch_missing.py` et `fetch_stale.py`, qui contiennent chacun l'orchestrateur et le contrat que les sources implémentent.

**Indirections.**

- `PersonWrites` relaie `person_repository`, qui relaie lui-même `_core`.
- `BibliographicNormalizer` reçoit des fabriques de passerelles alors que la connexion est connue à la construction.
- Des paramètres traversent sans être lus : `logger` dans six `process_work`, `user_agent` sur quatre niveaux, `run_parallel` dans trois phases.
- Onze phases posent `metrics.resume = ""`.
- Chaque phase réinterprète `RunOptions` : `MODES[options.mode]` est recherché cinq fois.

**Nommage.**

- Le français et l'anglais se mêlent dans les identifiants, jusque dans une même classe (`SourceExtractor._years`, `_extrait_par_annee`).
- Une même notion a plusieurs noms : harvest, extract, extracteur ; signature, authorship, `source_authorship`.
- Le code emploie des abréviations maison : `pub`, `sp`, `sd`.
- Des noms trompent sur ce que fait le code :
  - `persons/matching.py` contient tout le SQL de la phase `persons` ;
  - `upsert_source_authorships_batch` fait un insert ;
  - `NormalizeStats.errors` compte aussi les notices incomplètes ;
  - dans `find_or_create.py`, `pub_id` désigne un éditeur.

**Duplication.**

- Lecture de l'identifiant et du DOI d'un document : jusqu'à cinq copies par source (ScanR, Crossref, WoS).
- Construction de l'en-tête `User-Agent` : dix copies, avec deux politiques.
- Téléchargement des dumps DOAJ et ROR.
- Synchronisation des détections de structures, dans `address_resolution.py` et `idref_resolution.py`.
- Liste des DOI connus, recopiée de la vue `candidate_dois` dans `doi_prefixes.py`.

## Décisions

- Le SQL propre à un module vit dans ce module. Le SQL partagé par plusieurs modules est l'accès à une entité : il vit dans le *store* de l'entité, une classe qui reçoit la connexion à sa construction et rend un agrégat ou des lignes. *Repository* désigne seulement les adaptateurs d'`infrastructure/`. Pas de préfixe `Pg` ni de suffixe `Gateway` ou `Queries`.
- `transformation/` est organisé par entité. Le graphe déclare des tâches ; une phase regroupe des tâches pour l'affichage dans les journaux et l'administration.
- Les identifiants du code sont en anglais. Les textes affichés sont en français.
- Une notion, un mot. Le niveau source décrit une entité telle qu'une source la donne, le niveau consolidé réunit les sources :
  - `source_publications` devient `source_records` (« enregistrement source » dans les textes), `publications` garde son nom ;
  - `source_authorships` devient `source_contributions` (« contribution source » dans les textes), `authorships` devient `contributions` ;
  - `author_identifying_keys` devient `contributor_information` ; « identité » sort du vocabulaire ;
  - « Signature » désigne seulement la chaîne d'adresse, au sens du glossaire ; « notice » sort du vocabulaire.

  Les noms et textes ajoutés avant la phase 8 emploient déjà ces termes. La collecte des sources s'appelle *harvest* partout, phases comprises, et « moissonnage » dans les textes affichés.
- Les alias de table du SQL restent courts : leur portée est la requête qui les déclare.
- Le module d'une phase a le nom de la phase et expose `build()`.
- L'outillage HTTP quitte `ingestion/` pour un paquet neutre `pipeline/http/`. `parallel.py` et `access_source.py` rejoignent `runtime/`. Des contrats import-linter fixent le sens des dépendances : le noyau (`runtime`, `graph`, `node_runner`) n'importe ni `ingestion` ni `transformation`.
- Le contexte de phase est le seul canal des transactions et du journal.
- Chaque phase par paquet applique les conventions SQL, de nommage et de langue aux modules qu'elle touche. Un module se modifie une seule fois.
- Les constats couverts par [Une source, un adaptateur](../CODE_adaptateur-par-source.md), [Accès réseau des sources](../CODE_acces-reseau-des-sources.md), [Contrat des métriques de phase](../CODE_contrat-des-metriques.md) et [Cycle de vie des publications](../CODE_cycle-de-vie-des-publications.md) restent dans ces fiches.

## Phasage

### Phase 1 — Dépendances et noyau d'exécution

- [x] `pipeline/http/` ; `parallel.py` et `access_source.py` sous `runtime/`. `api_params.py`, propre aux sources, sous `ingestion/`. addd583b6
- [x] Contrats import-linter du sens des dépendances. daf45dab6
- [x] Contexte de phase seul canal des transactions et du journal. 08a950ab6
- [x] `RunOptions` résolues une fois : ensemble de sources explicite, politique du mode. fd7d41c5d
- [x] `runtime/config.py` : identifiants d'accès vers `ingestion/`, collections HAL et identifiants d'API vers `infrastructure/read_models/perimeters.py`. `savepoint.py` vers `infrastructure/db/`. Le contexte de phase transmet le contrôle des identifiants à `access_source`. a5061104b
- [x] Interface de `run_nodes` et de `PhaseMetrics` : ligne de clôture optionnelle, `resume`, `add(total=…)`, `Node.group`, `Node.lot`. c5b8b7f43, a40b48acd, a9ff9b186
- [x] Description d'une phase en un seul endroit. 48ebb9f81

### Phase 2 — `ingestion/common` et `complements`

- [x] Contrat des sources séparé de l'orchestrateur, pour `normalize`, `fetch_missing` et `fetch_stale`. 7aa00af58
- [x] `staging.py` scindé ; suppression des `source_publications` dans `source_publications.py`. 626c47b83
- [x] `ror/dump.py` dans `complements/` ; téléchargement des dumps commun. 5ef6d1c7c
- [x] `User-Agent` construit par `polite_pool.py`. ac9fdb98d
- [x] Indirections : `Extracteur`, réexport de `scoped_logger`, fabriques de `BibliographicNormalizer`. d73ed7766
- [x] Code mort : `BatchInsertCounts`, délais inutilisés, `API_BASE_URLS["doaj"]`. 626c47b83, e0caa95b8

### Phase 3 — Sources

- [x] Un `api.py` par source : client, en-têtes, lecture d'un document par identifiant. 94309e621…da94de3f2
- [x] Collecte des sources nommée *harvest* : phases, modules, classes ; fenêtre de moissonnage typée. fc7b3df3c, 44be23e83
- [x] Règle de placement de la lecture du payload entre `domain/sources/` et `ingestion/<source>/`. 28937a229, b9ae81c73
- [x] Paramètre `logger` mort des `process_work`. 4ecfb0f90

### Phase 4 — `persons`

- [x] `PersonWrites` remplacé par `PgPersonRepository`. 8cf288f6a
- [x] Arbitrage des identifiants en un module. 7705ac171
- [x] Renommage et attribution d'un identifiant dans `PgPersonRepository`, pour la phase et l'API. dd383c632
- [x] SQL de `matching.py` et `name_forms.py` : store des personnes pour l'accès partagé, le reste dans les modules qui l'utilisent. 1c5a58429
- [x] `loading.py` : champs projetés jamais lus. d98e79bfa

### Phase 5 — `structures`

- [x] Reconnaissance des formes de nom de structures hors de `address_resolution.py`. 627f38a48
- [x] Synchronisation des détections commune aux adresses et à IdRef. dd8a3218a
- [x] Modules du périmètre : `perimeter`, `perimeter_evidence`, `in_perimeter`, port `AffiliationsQueries`. 2318e868f
- [x] Place de `countries/`. f3c9fc701

### Phase 6 — `publications`

- [x] Modules de `reconciliation/` renommés ; `run` et `ReconcileStats | None` simplifiés. dc67c5e86
- [x] `store.update_sources` vers `consolidation.py`. fcfa6f145
- [x] Rattachement d'orphelines (`assign_orphan_source_authorships_to_person`) vers `PgAuthorshipRepository`. dced4345f
- [x] Imports paresseux répétés dans les `build()`, et imports différés de tout `pipeline/` remontés, sauf ceux qui chargent le code d'une seule source. 04cf1f805

### Phase 7 — `publishing`

- [x] SQL de `journals/journals.py` réparti par étape ; stores des revues, monographies et éditeurs. 23e96abb6, 22217be80, d99f7ecb1
- [x] Requalification par revue dans `journals/`, fusion des monographies sur le modèle des revues. dc0ad9d0f, a4d612b73
- [x] Un inventaire de fusion par entité, celui des étapes (`MergeStep`, avec la nature de sa donnée) ; les inventaires du domaine disparaissent. a4d612b73
- [x] Liste des DOI connus tirée d'une vue commune avec `candidate_dois`. 4e6fb8c35
- [x] Noms : étape DOAJ, `pub_id` d'éditeur. a80930582

### Phase 8 — Vocabulaire

- [x] Vocabulaire : pour chaque notion, le mot des textes et l'identifiant du code, dans `docs/donnees/` et `docs/pipeline/01-vue-d-ensemble.md`. 4053fbda3
- [x] Renommage du schéma, de l'API et du frontend, en une migration. 1f1375f33
  - `source_publications` → `source_records`, `source_authorships` → `source_contributions`, `authorships` → `contributions` ;
  - `author_identifying_keys` → `contributor_information`, sa colonne `person_identifiers` → `identifiers`, `source_authorships.identity_id` → `contributor_information_id` ;
  - tables et vues dérivées : `source_authorship_addresses`, `_rors`, `_hal_structures`, `_structures` → `source_contribution_*`, `authorship_structures` → `contribution_structures`, `publications.authorships_dirty` → `contributions_dirty` ;
  - `source_authorship_groups` → `source_contribution_groups`, `grouped_source_authorships` → `source_contribution_group_members` ;
  - `confirmed_authorships` → `confirmed_source_contributions`, `rejected_authorships` → `rejected_contributions`, `publication_author_alignment.matched_signatures` → `matched_source_contributions` ;
  - `pub_count` → `publication_count`, `pub_year` → `publication_year`, `persons_rh` → `hr_records`, `structure_tutelles` → `structure_parents`, valeur `perimeter_evidence = 'rh_identity'` → `'hr_record'`.
- [x] Identifiants Python renommés vers les mots du vocabulaire, abréviations comprises (`pub`, `sp`, `sa`, `sd`, `nf`). Un test sur l'AST refuse `pub`, `sp`, `sd` et `nf` ; `sa` reste l'alias de SQLAlchemy. 45f167d1d, abda4adf4, 137f915ad
- [x] Alias de table du SQL aux initiales des noms cibles (`sr`, `sc`, `ci`), fragments de `sql_fragments.py` compris. 7bf39771a
- [x] Textes alignés : « signature », « notice », « identité » et « authorship » remplacés. a92d7ada1, e2006712a, 9c6bf8287, fc6b3bb5f, 5ce09278d, 6f8a4051b, 0a1c8f1ee

### Phase 9 — Conventions restantes

- [x] Identifiants en anglais : `runtime/observability/` (`log_format.py`, `progress.py`) et ses appelants. 4851f94a8
- [x] Identifiants en anglais : `run.py`, `graph.py`, constantes `LABEL` de `publishing/`. f74620b25
- [x] Identifiants en anglais : `ingestion/`. 2094f2732
- [x] Identifiants en anglais : `transformation/`. 528b8fbf3
- [x] Classes à suffixe `Queries` ou préfixe `Pg` : store d'entité ou SQL du module qui l'utilise. Les stores reçoivent leur connexion à la construction ; les fonctions qui relayaient `conn` sans s'en servir le perdent.
  - stores de l'ingestion et normaliseurs : 87c3cf1af, 1d05adc8f, 1fce9b731 ;
  - stores de la transformation : fcbd1d410, d5cef9a80, 80809f2df, 9d3f9c11d, e182cece1, ddb446a50 ;
  - SQL d'un seul module en fonctions : 5e0eee5b3, 1d75f0f3b, 30f01b13b.

## Questions ouvertes

- Vérification des lectures et écritures que `graph.py` déclare pour chaque tâche. Les tests en tirent l'ordre des phases, mais rien ne les confronte au SQL. Piste : sur un run audité, capturer les requêtes du pipeline par les événements de SQLAlchemy, les attribuer à la tâche en cours et les analyser par `sqlglot`, au niveau de la colonne. `sqlglot` se limite aux dépendances de développement.
