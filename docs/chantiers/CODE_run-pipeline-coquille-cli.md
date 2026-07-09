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
- **Frontière transactionnelle injectée.** Pour ouvrir ses transactions sans importer `infrastructure/`, l'orchestrateur de phase reçoit de quoi ouvrir une transaction gérée (connect / commit-sur-succès / rollback / close), fourni par le composition-root. La forme — appelable-fabrique ou objet `UnitOfWork` réifié — est tranchée par ce chantier sur ses mérites, sur la phase pilote, en prenant la plus propre. Aucun choix d'un chantier antérieur ne la contraint.
- **Familles par source collapsées.** `normalize` et `extract` : un registre `source → (classe, queries)` et un orchestrateur paramétré unique par famille, dans `application/pipeline/normalize/` et `application/pipeline/extract/`. Les ~12 copies deviennent 2 orchestrateurs.
- **SQL brut déplacé** vers `infrastructure/`, appelé par l'orchestrateur applicatif concerné.

## Phasage

### Phase 1 — Fabrique de transaction et phase pilote

- [ ] Fabrique de transaction injectable (connect / commit-sur-succès / rollback / close, chrono `▶`/`✓`), fournie par le composition-root.
- [ ] Migrer une phase mono-étape (`oa_status` ou `relations`) : l'orchestrateur applicatif reçoit la fabrique et ses adapters, séquence, logue, retourne ses métriques. Valider le format et le e2e.

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
- **Forme du unit of work : fabrique ou objet réifié.** Tranchée par ce chantier sur la phase pilote, au mérite : un appelable-fabrique suffit si l'orchestrateur ne fait qu'ouvrir des transactions indépendantes ; un objet `UnitOfWork` réifié se justifie s'il gagne à porter la connexion et les adapters d'une phase. Si la version propre conduit à un UoW réifié qu'on veut **partager** avec l'API (dont les command handlers exposent déjà un unit of work fonctionnel), cette unification côté `interfaces/api/` fait l'objet d'un **chantier séparé** — question de périmètre, pas de contrainte de conception.
- **Phases à commits multiples.** La fabrique « commit-sur-succès en fin de bloc » couvre le cas simple ; les phases qui committent au fil de l'eau (durabilité, étalement du WAL) doivent garder ce comportement. La fabrique doit passer la `Connection` pour autoriser les commits précoces sans double-commit parasite.
