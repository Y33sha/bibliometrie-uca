# Chantier — Refactorisation : orchestrateur et moissonnage

## Contexte

Relecture du pipeline dans l'ordre d'exécution, selon *A Philosophy of Software Design* (John Ousterhout) : modules profonds, fuites d'information, erreurs masquées, obscurité. La relecture couvre le code, les docstrings et le journal.

## Décisions

- Périmètre de la fiche : orchestrateur (`pipeline/run.py`, `pipeline/graph.py`, `pipeline/task_runner.py`, `pipeline/runtime/`) et phase `harvest`. D'autres fiches couvrent les phases suivantes.

## Phasage

### Phase 1 — Erreurs du moissonnage

- [x] Une année en échec dans `SourceHarvester._harvest_by_year` émet un signal et compte une erreur. La phase passe en avertissement. Test de non-régression. Même traitement pour un lot en échec du moissonnage par personne, et pour les deux échecs d'année journalisés sans exception par WoS.
- [x] Les documents d'une page annulée par le rollback sortent des métriques : `stage_records` compte un lot après son commit.

### Phase 2 — Exécuteur des tâches

- [x] `execute_tasks` sépare l'ordre d'exécution et le rendu de l'arborescence du journal. Un objet garde l'état des sections ouvertes.
- [x] La dernière ligne d'une phase sans section prend `└─` (`harvest`, `harvest_by_person`, `fetch_stale`).
- [x] `Task.progress_bar` disparaît. Toutes les tâches à barre sont sans section, et une ligne sans section va déjà au seul journal : l'attribut ne décidait rien, et le module `progress` n'a rien à signaler.
- [ ] La ligne de bilan d'une tâche se produit d'une seule façon. Il en existe trois : `label` et compteurs, `label` et `PhaseMetrics.report`, tâche sans `label` qui écrit elle-même.
- [x] `PERIMETER_STRUCTURES` passe par l'exécuteur : durée mesurée, exécution enregistrée, échec journalisé avec la commande de reprise. La tâche s'exécute en tête de la première phase du run qui lit ses écritures (`harvest` ou `affiliations`), avant sa condition : sa durée et son échec sont ceux de cette phase.

### Phase 3 — Déclaration des phases

- [x] `Phase.harvesting` disparaît au profit de `block is Block.HARVESTING`, vrai pour les mêmes phases.
- [ ] Les modules de phase exportent leurs étapes et leurs tâches sous un seul nom (`TASKS` ou `STEPS`).
- [x] `Phase.when` et `Task.when` reçoivent le même argument. Le message d'une phase écartée vaut pour toute condition. « Sautée en mode X » suppose une condition sur le mode : la ligne devient « Sautée », le mode figurant dans la bannière du run.

### Phase 4 — Point d'entrée

- [x] `main()` configure le logger racine et le flux console. L'import de `pipeline/run.py` reste sans effet de bord. Même chose pour le logger de `pipeline/runtime/execution.py`.
- [x] Le rendu de la bannière passe de `pipeline/run.py` à `pipeline/runtime/observability/log_format.py`, avec le cadre des phases dont il partage la largeur.

### Phase 5 — Docstrings

- [x] `pipeline/runtime/modes.py` : suppression de la liste des modes dans la docstring du module, incomplète et redondante avec `MODES`. Docstring de `ModePolicy.vacuum_full`.
- [x] `pipeline/ingestion/common/harvester.py` : suppression de « La pagination reste propre à chaque source ». Cinq sources paginent par `stage_pages`.

## Questions ouvertes

- `--sources` et `--include-wos` règlent la même décision. `--sources wos` sans `--include-wos` moissonne zéro source, sans signal. L'option nomme une source, le mécanisme est générique (`SourceProfile.opt_in`). Proposition : `--sources` exclut par défaut les sources sur option et les inclut quand elles sont nommées. `--include-wos` disparaît.
