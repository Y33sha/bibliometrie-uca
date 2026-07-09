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
- **Frontière transactionnelle injectée.** Pour ouvrir ses transactions sans importer `infrastructure/`, l'orchestrateur de phase reçoit un `OpenTransaction` (`application/ports/pipeline/transaction.py`) : un appelable rendant une transaction gérée (commit-sur-succès / rollback / close), fourni par le composition-root et satisfait par `Engine.begin`. Forme retenue sur la phase pilote : appelable, pas d'objet `UnitOfWork` réifié — les transactions d'une phase sont indépendantes et ses adapters injectés à côté, un registry de repos n'apporterait rien.
- **Familles par source collapsées.** `normalize` et `extract` : un registre `source → (classe, queries)` et un orchestrateur paramétré unique par famille, dans `application/pipeline/normalize/` et `application/pipeline/extract/`. Les ~12 copies deviennent 2 orchestrateurs.
- **SQL brut déplacé** vers `infrastructure/`, appelé par l'orchestrateur applicatif concerné.

## Phasage

### Phase 1 — Fabrique de transaction et phase pilote

- [x] Port `application/ports/pipeline/transaction.py` : `OpenTransaction`, appelable rendant une transaction gérée (commit-sur-succès / rollback / close). Satisfait tel quel par `Engine.begin`, fourni par le composition-root — pas d'objet `UnitOfWork` réifié (transactions indépendantes, adapters injectés à côté).
- [x] Phase pilote `relations` migrée : `populate_relations.run(open_tx, queries, log)` possède sa transaction, son logging `▶`/`✓` et l'assemblage de `PhaseMetrics` ; `phase_relations` se réduit au câblage, `_run_populate_relations` supprimé. Validé e2e (`--only relations`) et par les hooks. La durée par phase reste captée par le dispatcher pour l'observabilité.

### Phase 2 — Familles par source

- [ ] `normalize` : registre `source → (Normalizer, PgQueries)` et orchestrateur paramétré unique dans `application/pipeline/normalize/` ; retirer les 7 copies de `run_pipeline`.
- [ ] `extract` : même geste ; retirer les 5 copies.

### Phase 3 — Phases multi-étapes

- [ ] Rapatrier la séquence, le logging et les métriques de chaque phase multi-étapes (countries, authorships, publishers_journals, metadata_correction, affiliations, publications, cross_imports) dans son orchestrateur applicatif.
- [ ] Préserver à l'identique les frontières transactionnelles existantes, en particulier les phases à commits par lots (purge par tranches, `reconcile_components`) ; test e2e vert avant de passer à la suivante.

### Phase 4 — SQL brut résiduel

- [ ] Déplacer `_run_recompute_address_pub_count` et la poche SQL de `_run_parallel_extractors` vers `infrastructure/`.

### Phase 5 — Coquille

- [ ] `run_pipeline.py` réduit à : parsing, graphe des phases, câblage par phase, dispatch séquentiel, signaux.
- [ ] Découper `main()` pour lever son `# noqa: C901`.

## Questions ouvertes

- **Objet injecté : fabrique de transaction ou `Engine` nu.** L'orchestrateur peut recevoir une fabrique (appelable rendant une connexion gérée, un point d'injection propre) ou directement l'`Engine` sqlalchemy — déjà connu d'`application/` via le type `Connection` — et faire `with engine.begin() as conn`. La fabrique abstrait la frontière ; l'`Engine` est plus direct mais couple davantage à sqlalchemy. À trancher sur la phase pilote.
- **Partage éventuel du unit of work avec l'API.** La forme retenue ici est l'appelable `OpenTransaction`. Si un objet `UnitOfWork` réifié partagé entre le pipeline et l'API (dont les command handlers exposent déjà un unit of work fonctionnel) devenait souhaitable, cette unification côté `interfaces/api/` ferait l'objet d'un **chantier séparé** — question de périmètre, pas de contrainte de conception.
- **Phases à commits multiples.** La fabrique « commit-sur-succès en fin de bloc » couvre le cas simple ; les phases qui committent au fil de l'eau (durabilité, étalement du WAL) doivent garder ce comportement. La fabrique doit passer la `Connection` pour autoriser les commits précoces sans double-commit parasite.
