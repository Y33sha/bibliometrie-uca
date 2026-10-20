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
- `transformation/` est organisé par entité. Le graphe déclare des nœuds ; une phase regroupe des nœuds pour l'affichage dans les journaux et l'administration.
- Les identifiants du code sont en anglais. Les textes affichés sont en français.
- Une notion, un mot. `authorships` devient `contributions`. La collecte des sources s'appelle *harvest* partout, phases comprises, et « moissonnage » dans les textes affichés.
- L'outillage HTTP quitte `ingestion/` pour un paquet neutre `pipeline/http/`. `parallel.py` et `access_source.py` rejoignent `runtime/`. Des contrats import-linter fixent le sens des dépendances : le noyau (`runtime`, `graph`, `node_runner`) n'importe ni `ingestion` ni `transformation`.
- Le contexte de phase est le seul canal des transactions et du journal.
- Chaque phase par paquet applique les conventions SQL, de nommage et de langue aux modules qu'elle touche. Un module se modifie une seule fois.
- Les constats couverts par [Une source, un adaptateur](CODE_adaptateur-par-source.md), [Accès réseau des sources](CODE_acces-reseau-des-sources.md), [Contrat des métriques de phase](CODE_contrat-des-metriques.md) et [Cycle de vie des publications](CODE_cycle-de-vie-des-publications.md) restent dans ces fiches.

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
- [ ] `staging.py` scindé ; suppression des `source_publications` dans `source_publications.py`.
- [ ] `ror/dump.py` dans `complements/` ; téléchargement des dumps commun.
- [ ] `User-Agent` construit par `polite_pool.py`.
- [ ] Indirections : `SourcePublicationQueries`, `Extracteur`, réexport de `scoped_logger`, fabriques de `BibliographicNormalizer`.
- [ ] Code mort : `BatchInsertCounts`, délais inutilisés, `API_BASE_URLS["doaj"]`.

### Phase 3 — Sources

- [ ] Un `api.py` par source : client, en-têtes, lecture d'un document par identifiant.
- [ ] Règle de placement de la lecture du payload entre `domain/sources/` et `ingestion/<source>/`.
- [ ] Lecture de l'identifiant et du DOI unique par source, même contrat de retour.
- [ ] Paramètre `logger` mort des `process_work`.

### Phase 4 — `persons`

- [ ] `PersonWrites` remplacé par `PgPersonRepository`.
- [ ] Arbitrage des identifiants en un module.
- [ ] SQL de `matching.py` et `name_forms.py` : store des personnes pour l'accès partagé, le reste dans les modules qui l'utilisent.
- [ ] `loading.py` : champs projetés jamais lus.

### Phase 5 — `structures`

- [ ] Reconnaissance des formes de nom de structures hors de `address_resolution.py`.
- [ ] Synchronisation des détections commune aux adresses et à IdRef.
- [ ] Modules du périmètre : `perimeter`, `perimeter_evidence`, `in_perimeter`, port `AffiliationsQueries`.
- [ ] Place de `countries/`.

### Phase 6 — `publications`

- [ ] Modules de `reconciliation/` renommés ; `run` et `ReconcileStats | None` simplifiés.
- [ ] `store.update_sources` vers `consolidation.py`.
- [ ] Rattachement d'orphelines (`assign_orphan_source_authorships_to_person`) vers `PgAuthorshipRepository`.
- [ ] Imports paresseux répétés dans les `build()`.

### Phase 7 — `publishing`

- [ ] SQL de `journals/journals.py` réparti par étape ; stores des revues, monographies et éditeurs.
- [ ] Requalification par revue dans `journals/`, fusion des monographies sur le modèle des revues.
- [ ] Liste des DOI connus tirée d'une vue commune avec `candidate_dois`.
- [ ] Noms : étape DOAJ, `pub_id` d'éditeur.

### Phase 8 — Vocabulaire

- [ ] Glossaire : un mot par notion, abréviations bannies.
- [ ] `authorships` renommé `contributions`.
- [ ] Collecte des sources renommée *harvest* : phases `extract` et `extract_by_person`, modules, identifiants.

### Phase 9 — Documentation

- [ ] Conventions du pipeline dans `docs/architecture/`.

## Questions ouvertes

- Nom du module qui expose `build()`, puisque la phase regroupe des nœuds pour l'affichage.
- Périmètre de la phase 8 : le renommage d'`authorships` touche le schéma, l'API et le frontend ; celui des phases touche la ligne de commande, les runs enregistrés et l'administration.
- Vérification des lectures et écritures que `graph.py` déclare pour chaque nœud. Les tests en tirent l'ordre des phases, mais rien ne les confronte au SQL. Piste : sur un run audité, capturer les requêtes du pipeline par les événements de SQLAlchemy, les attribuer au nœud en cours et les analyser par `sqlglot`, au niveau de la colonne. `sqlglot` se limite aux dépendances de développement.
