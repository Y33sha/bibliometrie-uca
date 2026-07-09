# Chantier — run_pipeline : réduire à la coquille CLI

`run_pipeline.py` fait 2340 lignes et porte, inline et répété, tout le câblage de composition de chaque phase. Ce chantier le ramène à une coquille CLI (parsing des arguments, graphe des phases, `main`, signaux) en factorisant le patron transverse commun et en clarifiant où vit la racine de composition.

## Contexte

### Ce qui gonfle le fichier

45 fonctions `_run_*` répètent le même patron (~15-20 lignes chacune, ~800 lignes au total) : imports paresseux de l'orchestrateur applicatif et des adapters `Pg*`, ouverture d'une connexion, appel de l'orchestrateur, `commit`, fermeture, logs `▶`/`✓` chronométrés. Mesuré : 43 `get_sync_engine().connect()`, 45 logs de phase, 61 fonctions au total. Seule ligne utile par fonction : l'appel de l'orchestrateur.

La logique métier n'a pas fui vers l'orchestrateur : le SQL brut ne subsiste que dans deux poches (`_run_recompute_address_pub_count`, un fragment de `_run_parallel_extractors`) ; tout le reste délègue déjà à `infrastructure/`. Le problème est donc du **câblage dupliqué**, pas de la logique égarée.

### La contrainte de couches

L'architecture est hexagonale (`docs/architecture/01-vue-d-ensemble.md`) : le cœur est `application/` (avec `domain/`), entouré de deux bandes d'adapters frères qui ne se connaissent pas — `interfaces/` (entrants) et `infrastructure/` (sortants). Règle 3 : `application/` n'importe pas `infrastructure/` ; c'est `infrastructure/` qui implémente les ports d'`application/ports/`, jamais l'inverse. Vérifié : `application/` n'importe jamais `get_sync_engine`, les orchestrateurs reçoivent une `Connection` injectée.

Or le câblage instancie les `Pg*` (`infrastructure.queries`, `infrastructure.repositories`) et ouvre la connexion via `get_sync_engine` (`infrastructure.db.engine`). Il ne peut donc pas descendre dans `application/pipeline/<phase>/`. Sa place est la racine de composition — et règle 5 : un script CLI est son propre composition root. run_pipeline est donc le composition root du pipeline ; le câblage y reste. Ce qui se factorise, c'est le patron transverse répété.

## Décisions

- **Factoriser le patron transverse.** Un helper unique porte la frontière transactionnelle (connect / commit / rollback / close) et le chrono `▶`/`✓`. Chaque `_run_*` tombe à trois ou quatre lignes ; le patron n'existe plus qu'une fois. Sans effet sur les couches.
- **Extraire le SQL brut résiduel** (`_run_recompute_address_pub_count`, poche de `_run_parallel_extractors`) vers `infrastructure/`, appelé par un orchestrateur applicatif.

### Emplacement : tranché — reste dans run_pipeline

Le câblage n'est pas dupliqué entre run_pipeline et `application/` : l'orchestrateur applicatif reçoit ses adapters déjà instanciés (injection), il ne les assemble pas. Assembler ces outils — choisir les `Pg*` concrets, ouvrir la connexion — est le propre du composition-root, et le contrat de couches l'interdit dans `application/`. run_pipeline étant son propre composition-root, le câblage y reste. La duplication à résoudre est **interne** : le même patron copié 45 fois. On l'écrit donc une fois (un helper) et on le rappelle — sans rien déplacer. (`interfaces/cli/pipeline/` a été supprimé volontairement ; pas de résurrection.)

### Forme de la déduplication : à trancher

- **Helper (recommandé).** Une fonction porte « ouvrir / exécuter le travail de la phase / commit / fermer / chrono `▶`/`✓` ». Chaque phase reste une fonction nommée de trois lignes qui l'appelle. *Pour* : changement minimal ; chaque phase reste trouvable et garde ses particularités (argument en plus, second commit) ; traces d'erreur lisibles ; risque faible. *Contre* : il subsiste ~45 petites fonctions (mais de trois lignes).
- **Registre déclaratif.** Les 45 fonctions deviennent une table `phase → (orchestrateur, fabriques d'adapters)` lue par un runner unique. *Pour* : toute la liste des phases tient en un coup d'œil, concision maximale. *Contre* : suppose les phases uniformes, ce qu'elles ne sont pas (extract parallèle, purge et reconcile à commits par lots, affiliations et publications enchaînant plusieurs sous-étapes, résumés sur mesure). Chaque exception force un échappatoire ; la table se remplit de cas particuliers et le runner de `if`. Débogage plus opaque.

### Frontière transactionnelle

Cas général : une connexion, un `commit` en fin de phase. Quelques phases committent par lots (purge par tranches, `reconcile_components`). Un helper en *context-manager* qui commite en sortie si succès couvre les deux : les phases par lots committent au fil de l'eau, le commit final vide le reliquat. Seul arbitrage résiduel, ergonomique : le helper rend-il la `Connection` (la phase peut committer tôt) ou possède-t-il seul le commit. Recommandé : il ouvre/ferme et fait un commit-sur-succès, tout en passant la `Connection` pour autoriser les commits précoces.

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
