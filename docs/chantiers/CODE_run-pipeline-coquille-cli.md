# Chantier — run_pipeline : réduire à la coquille CLI

`run_pipeline.py` fait 2340 lignes et porte, inline et répété, tout le câblage de composition de chaque phase. Ce chantier le ramène à une coquille CLI (parsing des arguments, graphe des phases, `main`, signaux) en factorisant le patron transverse commun et en clarifiant où vit la racine de composition.

## Contexte

### Ce qui gonfle le fichier

45 fonctions `_run_*` répètent le même patron (~15-20 lignes chacune, ~800 lignes au total) : imports paresseux de l'orchestrateur applicatif et des adapters `Pg*`, ouverture d'une connexion, appel de l'orchestrateur, `commit`, fermeture, logs `▶`/`✓` chronométrés. Mesuré : 43 `get_sync_engine().connect()`, 45 logs de phase, 61 fonctions au total. Seule ligne utile par fonction : l'appel de l'orchestrateur.

La logique métier n'a pas fui vers l'orchestrateur : le SQL brut ne subsiste que dans deux poches (`_run_recompute_address_pub_count`, un fragment de `_run_parallel_extractors`) ; tout le reste délègue déjà à `infrastructure/`. Le problème est donc du **câblage dupliqué**, pas de la logique égarée.

### La contrainte de couches

Le contrat import-linter « Couches DDD » pose `interfaces > (infrastructure | application) > domain` : `application/` **n'importe pas** `infrastructure`. Or le câblage instancie les `Pg*` (`infrastructure.queries`, `infrastructure.repositories`) et ouvre la connexion via `get_sync_engine` (`infrastructure.db.engine`). Les orchestrateurs applicatifs reçoivent déjà une `Connection` injectée — `application/` n'importe jamais `get_sync_engine`.

Conséquence : l'instanciation des adapters et la frontière transactionnelle ne peuvent pas descendre dans `application/pipeline/<phase>/` sans violer le contrat. Elles appartiennent à la racine de composition, au niveau entrée/`interfaces`. Ce qui peut être factorisé, c'est le patron transverse ; ce qui peut être déplacé, c'est l'emplacement du câblage — pas sa couche.

## Décisions

- **Factoriser le patron transverse.** Un helper unique porte la frontière transactionnelle (connect / commit / rollback / close) et le chrono `▶`/`✓`. Chaque `_run_*` tombe à trois ou quatre lignes ; le patron n'existe plus qu'une fois. Sans effet sur les couches.
- **Extraire le SQL brut résiduel** (`_run_recompute_address_pub_count`, poche de `_run_parallel_extractors`) vers `infrastructure/`, appelé par un orchestrateur applicatif.

### À trancher

- **Emplacement de la racine de composition, une fois dédupliquée.**
  1. *En place* — les `_run_*` allégés restent dans `run_pipeline.py`.
  2. *Module dédié* — les `_run_*` migrent vers `interfaces/cli/pipeline/` (composition-root, autorisé à importer `infrastructure`), laissant `run_pipeline.py` réduit à la coquille CLI.
  3. *Registre déclaratif* — une table `phase → (orchestrateur applicatif, fabriques d'adapters)` pilotée par un runner générique, réduisant les 45 fonctions à de la donnée.
- **Granularité transactionnelle.** Le cas général est une connexion et un `commit` par phase, mais certaines phases committent par lots (purge batchée, `reconcile_components`). Le helper doit accepter les deux : commit final si la phase ne l'a pas fait, ou exposition de la `Connection` pour que la phase gère ses propres commits. À cadrer pour ne pas casser les phases à commits multiples.
- **Objet injecté.** Le helper reçoit-il l'`Engine` (il gère alors l'unit-of-work de bout en bout) ou une `Connection` déjà ouverte en amont (la gestion remonte au dispatcher) ? Le premier concentre la frontière transactionnelle dans le helper ; le second la laisse au point d'appel.

## Phasage

### Phase 1 — Helper transverse

- [ ] Helper d'unit-of-work + timing au composition-root (connect / commit / rollback / close, logs `▶`/`✓`, chrono).
- [ ] Migrer deux ou trois `_run_*` simples en pilote, figer le format et le contrat d'injection.

### Phase 2 — Migration en masse

- [ ] Convertir les 45 `_run_*` au helper.
- [ ] Traiter à part les phases à commits multiples (purge, reconcile) : variante du helper ou passage de la `Connection` nue.

### Phase 3 — SQL brut résiduel

- [ ] Déplacer `_run_recompute_address_pub_count` et la poche SQL de `_run_parallel_extractors` vers `infrastructure/`.

### Phase 4 — Emplacement final et coquille

- [ ] Selon la décision d'emplacement, extraire les runners vers `interfaces/cli/pipeline/` ou les garder allégés en place.
- [ ] Découper `main()` en helpers pour lever son `# noqa: C901`.

## Questions ouvertes

- **Registre déclaratif (option 3).** Concision réelle, ou indirection qui nuit à la lisibilité du graphe des phases ? À évaluer sur un échantillon avant de généraliser.
- **Résumés de phase.** Les assembleurs de dictionnaires de métriques (`_extract_source_summary`, `_normalize_row`, `_summary`) sont de la présentation : les regrouper dans un module de reporting, ou les laisser près de leur phase ?
