# Chantier — run_pipeline : réduire à la coquille CLI

Commencé le 2026-07-09 - Terminé le 2026-07-10

`run_pipeline.py` (2340 lignes) porte l'orchestration de chaque phase — séquence des sous-étapes, frontière transactionnelle, logging de progression, assemblage des métriques — alors que cette orchestration relève de la couche applicative. Ce chantier la rapatrie dans `application/pipeline/<phase>/` et réduit `run_pipeline.py` à une coquille de composition : câblage des adapters, graphe des phases, dispatch séquentiel, signaux.

## Contexte

### Ce que porte run_pipeline

16 phases (`phase_*`, dispatchées par `--only`) mais 45 fonctions `_run_*` : ces dernières ne sont pas des phases, ce sont les sous-étapes que chaque phase enchaîne. Chaque `_run_*` répète le même patron : imports de l'orchestrateur applicatif et des adapters `Pg*`, ouverture d'une connexion, appel de l'orchestrateur, `commit`, fermeture, logs `▶`/`✓` chronométrés.

Deux natures s'y mélangent :

- **Câblage** — instancier les `Pg*`, ouvrir la connexion. Légitimement au composition-root : l'architecture est hexagonale (`docs/architecture/01-vue-d-ensemble.md`), `application/` n'importe pas `infrastructure/`, et un script CLI est son propre composition-root (règle 5).
- **Orchestration** — séquence des sous-étapes, frontière transactionnelle, logging de progression, métriques. Du ressort applicatif : c'est la logique du use-case « phase ». Le logging *détaillé* vit d'ailleurs déjà dans les orchestrateurs (`build_authorships` logue ses étapes) ; seules l'enveloppe et la séquence restent échouées au composition-root.

### Deux causes au nombre de sous-étapes

- **Copies par source (~12).** `normalize` se déploie en 7 fonctions (hal, wos, openalex, scanr, theses, crossref, datacite) et `extract` en 5, quasi identiques à trois tokens près (classe, `PgQueries`, nom de source). Même étape répétée par source.
- **Vraies sous-étapes (le reste).** Les phases multi-étapes (countries, authorships, publishers_journals, metadata_correction, affiliations…) enchaînent des opérations distinctes, chacune avec ses adapters et sa transaction.

### Le SQL brut résiduel

La logique métier n'a pas fui vers le composition-root : le SQL brut ne subsiste que dans deux poches (`_run_recompute_address_pub_count`, un fragment de `_run_parallel_extractors`), à déplacer vers `infrastructure/`.

## Décisions

- **Orchestration en application, run_pipeline en coquille.** Chaque phase devient un orchestrateur `application/pipeline/<phase>/` qui séquence ses sous-étapes, ouvre ses transactions, logue sa progression et retourne ses métriques. `run_pipeline.py` se réduit au parsing des arguments, au graphe des phases, au câblage des adapters par phase, au dispatch séquentiel et aux signaux.
- **Frontière transactionnelle injectée.** Pour ouvrir ses transactions sans importer `infrastructure/`, l'orchestrateur de phase reçoit un `OpenTransaction` (`application/ports/pipeline/transaction.py`) : un appelable rendant une transaction gérée (commit-sur-succès / rollback / close), fourni par le composition-root et satisfait par `managed_transaction` (`infrastructure/db/transaction.py`). Ce satisfier **tolère les commits par lots** émis dans le bloc — indispensable aux phases à progression durable (résolution d'adresses, purge par tranches, réconciliation, suggestion de pays) ; `Engine.begin` lève `InvalidRequestError` en sortie de bloc dès qu'un commit précoce a fermé sa transaction. Forme retenue : appelable, pas d'objet `UnitOfWork` réifié — une phase enchaîne des transactions indépendantes hétérogènes qu'un UoW (transaction + registry de repos) épouserait mal, et les gateways de requêtes (`Pg*Queries`, sans état, prenant `conn` par appel) n'y auraient pas leur place ; les adapters d'une phase sont injectés à côté.
- **Opérations infra auxiliaires derrière des ports.** Les opérations qu'une phase enchaîne autour de son étape principale (rematérialisation du périmètre, purge des publications orphelines, refresh des `pub_count`, bilan pays…) deviennent des méthodes de port injectées, au même titre que les gateways de requêtes — jamais un appel direct à une fonction libre `infrastructure/` depuis `application/`. Une opération sans port d'accueil reçoit un petit port neuf (pub_counts, purge) plutôt qu'un appelable ad hoc : chaque dépendance d'un orchestrateur est ainsi un objet nommé et mockable.
- **Convention de nommage.** L'orchestrateur d'une phase multi-étapes vit dans `application/pipeline/<phase>/phase.py` (modèle `persons/phase.py`) ; `phase_<nom>` de `run_pipeline` s'y réduit au câblage.
- **Familles par source collapsées.** `normalize` et `extract` : un registre `source → (classe, queries)` et un orchestrateur paramétré unique par famille, dans `application/pipeline/normalize/` et `application/pipeline/extract/`. Les ~12 copies deviennent 2 orchestrateurs.
- **SQL brut déplacé** vers `infrastructure/`, appelé par l'orchestrateur applicatif concerné.

## Phasage

### Phase 1 — Fabrique de transaction et phase pilote

- [x] Port `application/ports/pipeline/transaction.py` : `OpenTransaction`, appelable rendant une transaction gérée (commit-sur-succès / rollback / close). Satisfait par `managed_transaction` (`infrastructure/db/transaction.py`), qui tolère les commits par lots, fourni par le composition-root — pas d'objet `UnitOfWork` réifié (transactions indépendantes, adapters injectés à côté).
- [x] Phase pilote `relations` migrée : `populate_relations.run(open_tx, queries, log)` possède sa transaction, son logging `▶`/`✓` et l'assemblage de `PhaseMetrics` ; `phase_relations` se réduit au câblage, `_run_populate_relations` supprimé. Validé e2e (`--only relations`) et par les hooks. La durée par phase reste captée par le dispatcher pour l'observabilité.

### Phase 2 — Familles par source

- [x] `normalize` : registre ordonné `source → constructeur` (`_normalize_builders`) + runner unique (`_run_normalize`) ; les 7 copies retirées, `phase_normalize` itère le registre. Validé e2e (`--only normalize`). Le câblage des `Pg*` reste au composition-root (contrainte de couches) — le registre y vit, pas dans `application/`.
- [x] `extract` : registre `source → constructeur d'extracteur` (`_extractors`) + runner unique (`_run_extract`) ; les 5 copies retirées, `phase_extract` construit ses tâches via un helper `task` préservant args par source et parallélisme. Validé par types + tests unitaires ; e2e par la prochaine extraction réelle (APIs externes).

### Phase 3 — Phases multi-étapes DB (fait)

Un orchestrateur `application/pipeline/<phase>/phase.py` par phase : séquence, transactions (`open_tx`), logging `▶`/`✓` et assemblage des métriques rapatriés ; opérations infra auxiliaires passées en ports injectés. Frontières transactionnelles préservées à l'identique (commits par lots des phases à progression durable) ; chaque phase validée e2e. Les phases à interrogation externe sont traitées à part (phase 4).

- [x] `metadata_correction` (`3a8d583b`)
- [x] `affiliations` — port `PerimeterQueries.refresh_perimeter_structures` ajouté (`c133c07d`)
- [x] `countries` — port `CountryQueries.count_address_country_status` ajouté, type `AddressCountryStatus` déplacé vers le port (`10227fbf`)
- [x] `authorships` — ports neufs `PurgeOrphanPublicationsQueries`, `PubCountsQueries`. Le `VACUUM ANALYZE` (maintenance physique, autocommit) sort du périmètre de l'invariant « connexion injectée » : l'adapter de purge ouvre sa propre connexion autocommit, l'orchestrateur ne voit pas l'autocommit (`5b574748`)
- [x] `publications` — port neuf `AddressPubCountQueries` (recompute `addresses.pub_count`), `mark_keys_dirty` ajouté à `PublicationsReconciliationQueries` ; repos injectés en factories (`5cf1514e`)
- [x] `persons` — mono-transaction : `run(open_tx, …)` possède sa transaction, repos en factories, `dry_run` mort retiré. Le test de non-régression « commit avant close » est remplacé par un test de `managed_transaction` (commit-sur-succès / rollback / commits par lots) qui garde la propriété pour toutes les phases (`28c9ef87`)
- [x] `subjects` — deux sous-étapes (ingestion, co-occurrences) sur le port existant `SubjectsQueries`, sans opération orpheline (`fced0c12`)

### Phase 4 — Phases à interrogation externe

Restent les phases qui parlent à une API, encore orchestrées au composition-root : `extract`, `resolve_ra`, `cross_imports`, `refresh_stale`, `refetch_truncated`, `publishers_journals`, `oa_status` — plus l'enveloppe de `normalize` (registre collapsé en phase 2, mais itération, VACUUM et nettoyage des identités orphelines restent au root).

**Pourquoi elles sont restées.** Trois préoccupations d'exécution/infra, absentes des phases DB :

- **Parallélisme** — `ThreadPoolExecutor` + `contextvars.copy_context` (`extract`, `cross_imports`).
- **Circuit-breaker** — `SourceCircuitBreaker` posé dans une `ContextVar` lue par la couche HTTP infra ; l'orchestrateur ne consulte que `breaker.tripped`.
- **Détection de config API** — `_configured_api_targets` ouvre une connexion, lit les credentials, émet les signaux `source_unconfigured`.

**Découpage retenu — descendre l'orchestration en `application/`** (plutôt que la laisser au composition-root sous prétexte qu'elle est mince et intriquée avec l'exécution) : cohérence avec les 8 phases DB, et une frontière hétérogène se paierait à la reprise DSI. `run_pipeline` vise la coquille stricte.

- *Descend en `application/pipeline/<phase>/phase.py`* : la séquence des sous-étapes, l'itération par source/canal, la lecture de la policy de mode (`modes.py`, déjà en application), l'assemblage des métriques et signaux (tables par source, entonnoirs, `source_unconfigured` / `source_unavailable`).
- *Reste au composition-root* : la construction des adapters `Pg*` et leurs registres (`_extractors`, `_make_*_adapter`) — contrainte de couches.
- *Injecté en ports/callables* : (a) `run_parallel` — port `RunParallel`, impl `infrastructure/concurrency.py` (thread pool + copie de `contextvars`), l'application ordonne « lance ces N thunks » sans importer `ThreadPoolExecutor` ; (b) une requête `configured_targets` pour la détection de config ; (c) le circuit-breaker, l'orchestrateur recevant des runners déjà breakerisés (métriques portant l'éventuel `source_unavailable`).

Phases :

- [x] `extract` — orchestrateur `application/pipeline/extract/phase.py` ; injectés : `extract_one` (conn + adapter + breaker), `run_parallel` (port `RunParallel`, impl `infrastructure/concurrency.py`), `get_last_extract_date`. Helpers partagés `timed_metrics` / `signal_source_unconfigured` remontés en `application/pipeline/signals.py`.
- [x] `resolve_ra`, `refetch_truncated`, `oa_status` — mono-étape : l'orchestrateur applicatif existait déjà, on y a remonté l'enveloppe `▶`/`✓`, `phase_*` réduit au câblage. Le signal `source_unavailable` reste au câblage (le port breaker n'expose que `tripped`).
- [x] `refresh_stale` — orchestrateur `run_phase` (boucle par source, fenêtre d'années) ; injectés : `refresh_one`, `credentials_missing`, `get_years_for_window`.
- [x] `cross_imports` — orchestrateur `application/pipeline/cross_imports/phase.py` (canaux HAL séquentiels + DOI parallèle via `RunParallel`).
- [x] `publishers_journals` — orchestrateur `application/pipeline/publishers_journals/phase.py` (3 sous-étapes, gardes de config).
- [x] enveloppe `normalize` — orchestrateur `application/pipeline/normalize/phase.py` (boucle registre, nettoyage identités orphelines, VACUUM encapsulé en infra).
- [x] Détection de config factorisée en `application.pipeline.signals.filter_configured` (boucle `credentials_missing` injectée + signaux) ; `_configured_api_targets` supprimé du root.

### Phase 5 — Coquille

- [x] `run_pipeline.py` réduit à : parsing, graphe des phases, câblage par phase (construction des adapters `Pg*` et injection dans les orchestrateurs applicatifs), dispatch séquentiel, signaux.
- [x] `main()` découpé en helpers (`_build_arg_parser`, `_select_phases_to_run`, `_run_one_phase`, `_execute_phases`…), `# noqa: C901` levé.
