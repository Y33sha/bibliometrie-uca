# Chantier — run_pipeline : réduire à la coquille CLI

`run_pipeline.py` fait 2340 lignes et porte, inline et répété, tout le câblage de composition de chaque phase. Ce chantier le ramène à une coquille CLI (parsing des arguments, graphe des phases, `main`, signaux) en factorisant le patron transverse commun et en clarifiant où vit la racine de composition.

## Contexte

### Ce qui gonfle le fichier

Le fichier compte 16 phases (`phase_*`, dispatchées par `--only`) mais **45 fonctions `_run_*`** : ces dernières ne sont pas des phases, ce sont les sous-étapes que chaque phase enchaîne. Toutes répètent le même patron (~15-20 lignes) : imports paresseux de l'orchestrateur applicatif et des adapters `Pg*`, ouverture d'une connexion, appel de l'orchestrateur, `commit`, fermeture, logs `▶`/`✓` chronométrés. Seule ligne utile par fonction : l'appel de l'orchestrateur.

Deux causes distinctes à ce nombre :

- **Copies par source (~12).** `normalize` se déploie en 7 fonctions (hal, wos, openalex, scanr, theses, crossref, datacite) et `extract` en 5 — quasi identiques, ne différant que par trois tokens : la classe `XxxNormalizer`/extracteur, le `PgXxx…Queries`, le nom de source. Ce ne sont pas des étapes distinctes mais la **même** étape répétée par source.
- **Vraies sous-étapes (~le reste).** Les phases multi-étapes (countries 4, authorships 3, publishers_journals 3, metadata_correction 3…) enchaînent des opérations réellement distinctes, chacune avec ses adapters et sa transaction. Pas de duplication de logique, seulement le patron transverse.

La logique métier n'a pas fui vers l'orchestrateur : le SQL brut ne subsiste que dans deux poches (`_run_recompute_address_pub_count`, un fragment de `_run_parallel_extractors`) ; tout le reste délègue déjà à `infrastructure/`. Le problème est donc du **câblage dupliqué** — par source, et transversalement.

### La contrainte de couches

L'architecture est hexagonale (`docs/architecture/01-vue-d-ensemble.md`) : le cœur est `application/` (avec `domain/`), entouré de deux bandes d'adapters frères qui ne se connaissent pas — `interfaces/` (entrants) et `infrastructure/` (sortants). Règle 3 : `application/` n'importe pas `infrastructure/` ; c'est `infrastructure/` qui implémente les ports d'`application/ports/`, jamais l'inverse. Vérifié : `application/` n'importe jamais `get_sync_engine`, les orchestrateurs reçoivent une `Connection` injectée.

Or le câblage instancie les `Pg*` (`infrastructure.queries`, `infrastructure.repositories`) et ouvre la connexion via `get_sync_engine` (`infrastructure.db.engine`). Il ne peut donc pas descendre dans `application/pipeline/<phase>/`. Sa place est la racine de composition — et règle 5 : un script CLI est son propre composition root. run_pipeline est donc le composition root du pipeline ; le câblage y reste. Ce qui se factorise, c'est le patron transverse répété.

## Décisions

- **Factoriser le patron transverse.** Un helper unique porte la frontière transactionnelle (connect / commit / rollback / close) et le chrono `▶`/`✓`. Chaque `_run_*` tombe à trois ou quatre lignes ; le patron n'existe plus qu'une fois. Sans effet sur les couches.
- **Extraire le SQL brut résiduel** (`_run_recompute_address_pub_count`, poche de `_run_parallel_extractors`) vers `infrastructure/`, appelé par un orchestrateur applicatif.

### Emplacement : tranché — reste dans run_pipeline

Le câblage n'est pas dupliqué entre run_pipeline et `application/` : l'orchestrateur applicatif reçoit ses adapters déjà instanciés (injection), il ne les assemble pas. Assembler ces outils — choisir les `Pg*` concrets, ouvrir la connexion — est le propre du composition-root, et le contrat de couches l'interdit dans `application/`. run_pipeline étant son propre composition-root, le câblage y reste. La duplication à résoudre est **interne** ; on l'écrit une fois et on la rappelle, sans rien déplacer. (`interfaces/cli/pipeline/` a été supprimé volontairement ; pas de résurrection.)

### Forme de la déduplication : hybride

Les deux causes de gonflement appellent deux gestes **complémentaires**, pas un choix exclusif.

- **Registre par source pour les familles homogènes.** `normalize` et `extract` : une table `source → (classe, queries)` et une fonction paramétrée unique par famille (`_run_normalize(source)`, `_run_extract(source)`). ~12 fonctions → 2, avec deux petits registres ; ~180 lignes de copier-coller supprimées. Le registre est pertinent **ici** parce que les étapes sont réellement uniformes.
- **Helper transverse pour les sous-étapes hétérogènes.** Le reste (build_authorships, reconcile, purge, countries…) garde une fonction nommée par étape, réduite à trois lignes appelant un helper d'unit-of-work + chrono `▶`/`✓`. Chaque étape reste trouvable, garde ses particularités, et les traces d'erreur restent lisibles.

À éviter : un registre déclaratif **global** couvrant toutes les phases — elles ne sont pas uniformes (extract parallèle, commits par lots, sous-étapes chaînées, résumés sur mesure), et chaque exception forcerait un échappatoire qui ruinerait la table.

### Frontière transactionnelle

Cas général : une connexion, un `commit` en fin de phase. Quelques phases committent par lots (purge par tranches, `reconcile_components`). Un helper en *context-manager* qui commite en sortie si succès couvre les deux : les phases par lots committent au fil de l'eau, le commit final vide le reliquat. Seul arbitrage résiduel, ergonomique : le helper rend-il la `Connection` (la phase peut committer tôt) ou possède-t-il seul le commit. Recommandé : il ouvre/ferme et fait un commit-sur-succès, tout en passant la `Connection` pour autoriser les commits précoces.

## Phasage

### Phase 1 — Helper transverse

- [ ] Helper d'unit-of-work + timing au composition-root (connect / commit / rollback / close, logs `▶`/`✓`, chrono).
- [ ] Migrer deux ou trois `_run_*` simples en pilote, figer le format et le contrat d'injection.

### Phase 2 — Familles par source

- [ ] `normalize` : registre `source → (Normalizer, PgQueries)` + `_run_normalize(source)` unique ; supprimer les 7 copies.
- [ ] `extract` : même geste ; supprimer les 5 copies.

### Phase 3 — Sous-étapes hétérogènes

- [ ] Convertir les `_run_*` restants (one-off) au helper.
- [ ] Traiter à part les étapes à commits multiples (purge, reconcile) : variante du helper ou passage de la `Connection` nue.

### Phase 4 — SQL brut résiduel

- [ ] Déplacer `_run_recompute_address_pub_count` et la poche SQL de `_run_parallel_extractors` vers `infrastructure/`.

### Phase 5 — Coquille CLI

- [ ] Découper `main()` en helpers pour lever son `# noqa: C901`.
- [ ] `run_pipeline.py` réduit à : parsing, graphe des phases, dispatch, signaux.

## Questions ouvertes

- **Registre déclaratif (option 3).** Concision réelle, ou indirection qui nuit à la lisibilité du graphe des phases ? À évaluer sur un échantillon avant de généraliser.
- **Résumés de phase.** Les assembleurs de dictionnaires de métriques (`_extract_source_summary`, `_normalize_row`, `_summary`) sont de la présentation : les regrouper dans un module de reporting, ou les laisser près de leur phase ?
