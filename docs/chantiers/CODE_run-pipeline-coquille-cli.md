# Chantier — run_pipeline : réduire à la coquille CLI

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

### Phase 3 — Phases multi-étapes

Un orchestrateur `application/pipeline/<phase>/phase.py` par phase : séquence, transactions (`open_tx`), logging `▶`/`✓` et assemblage des métriques rapatriés ; opérations infra auxiliaires passées en ports injectés. Frontières transactionnelles préservées à l'identique (commits par lots des phases à progression durable) ; test e2e vert avant la phase suivante. Du plus simple au plus dur :

- [x] `metadata_correction` (`3a8d583b`)
- [x] `affiliations` — port `PerimeterQueries.refresh_perimeter_structures` ajouté (`c133c07d`)
- [x] `countries` — port `CountryQueries.count_address_country_status` ajouté, type `AddressCountryStatus` déplacé vers le port (`10227fbf`)
- [x] `authorships` — ports neufs `PurgeOrphanPublicationsQueries`, `PubCountsQueries`. Le `VACUUM ANALYZE` (maintenance physique, autocommit) sort du périmètre de l'invariant « connexion injectée » : l'adapter de purge ouvre sa propre connexion autocommit, l'orchestrateur ne voit pas l'autocommit (`5b574748`)
- [x] `publications` — port neuf `AddressPubCountQueries` (recompute `addresses.pub_count`), `mark_keys_dirty` ajouté à `PublicationsReconciliationQueries` ; repos injectés en factories (`5cf1514e`)
- [x] `persons` — mono-transaction : `run(open_tx, …)` possède sa transaction, repos en factories, `dry_run` mort retiré. Le test de non-régression « commit avant close » est remplacé par un test de `managed_transaction` (commit-sur-succès / rollback / commits par lots) qui garde la propriété pour toutes les phases (`28c9ef87`)
- [x] `subjects` — deux sous-étapes (ingestion, co-occurrences) sur le port existant `SubjectsQueries`, sans opération orpheline
- [ ] `cross_imports`, `publishers_journals` — cas durs (parallélisme, circuit-breaker par `ContextVar`, détection de config API) traités en dernier, gabarit rodé

### Phase 4 — SQL brut résiduel

- [ ] Déplacer la poche SQL de `_run_parallel_extractors` vers `infrastructure/`. (Le recompute de `addresses.pub_count` est déjà injecté via `AddressPubCountQueries`, traité avec `publications`.)

### Phase 5 — Coquille

- [ ] `run_pipeline.py` réduit à : parsing, graphe des phases, câblage par phase, dispatch séquentiel, signaux.
- [ ] Découper `main()` pour lever son `# noqa: C901`.

## Questions ouvertes

- **Partage éventuel du unit of work avec l'API.** Le pilote retient l'appelable `OpenTransaction`. Un objet `UnitOfWork` réifié partagé entre le pipeline et l'API — dont les command handlers exposent déjà un unit of work fonctionnel — relèverait, s'il devenait souhaitable, d'un chantier séparé touchant `interfaces/api/`.
- **`dry_run` mort dans les orchestrateurs de phase.** `run_pipeline` ne passe jamais `dry_run` (son `--dry-run` court-circuite en tête de `main()` sans exécuter les phases), et aucune CLI n'appelle `reconcile_components.run` ni `correct_unary.run` avec `dry_run` : ces paramètres sont vestigiaux. Retrait prévu dans un chantier de nettoyage final (celui de `persons` est déjà retiré, incompatible avec le commit-sur-succès).
