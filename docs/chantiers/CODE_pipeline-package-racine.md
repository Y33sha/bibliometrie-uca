# Chantier — Le pipeline en paquet racine

## Contexte

Le pipeline tient sur quatre couches de l'architecture hexagonale : orchestrateurs dans `application/pipeline`, ports dans `application/ports/pipeline`, adaptateurs SQL dans `infrastructure/pipeline`, câblage dans `interfaces/cli/phases`. Pour une suite de transformations de tables en tables, la séparation entre logique et SQL est artificielle : la logique est souvent le SQL. Les opérations du pipeline (« trouver ou créer » une revue, créer une publication, rattacher une signature) vivent dans `application/services`, que seul le pipeline appelle.

La cible est posée par la question 5 de la fiche [Architecture cible du pipeline](CODE_architecture-cible-pipeline.md).

## Décisions

- **Un paquet racine `pipeline/`**, hors des couches hexagonales, sans ports : chaque nœud contient son SQL. Les règles pures restent dans `domain/`.
- **Découpage par domaine** : `pipeline/sources/<source>`, `pipeline/structures`, `pipeline/containers`, `pipeline/publications`, `pipeline/persons` ; `graph.py` et l'orchestrateur à la racine. Chaque nœud rejoint le domaine des tables qu'il écrit : les relations, les sujets et le statut d'accès ouvert vont dans `pipeline/publications`, les pays dans `pipeline/structures`.
- **Règles d'import** vérifiées par `import-linter` : `pipeline/` importe `domain/` et les modules techniques d'`infrastructure/` (connexion, réglages, journalisation, fragments SQL), jamais `application/` ni `interfaces/`. `application/` et `infrastructure/` n'importent pas `pipeline/`. Seule l'API (`interfaces/api/deps.py`) importe l'interface publique du pipeline : recalculs ciblés, ordre des phases.
- **Régime de transition** : pendant la migration, `pipeline/` et le code du pipeline encore dans les couches (`application/pipeline`, `application/ports/pipeline`, `infrastructure/pipeline`, `infrastructure/sources`) s'importent dans les deux sens. Les exceptions sont listées dans `pyproject.toml` et disparaissent avec la dernière phase.
- **Une phase à la fois, dans l'ordre du pipeline.** Chaque phase migrée confronte la cible aux situations concrètes qui la concernent ; ce qui ne tient pas sort de la cible.
- **Le câblage `interfaces/cli/phases` disparaît** avec les ports. Le point d'entrée `run_pipeline` passe dans `pipeline/`.
- **Une fonction par nœud du graphe**, nommée comme lui. Une phase est la liste de ses nœuds, appelés dans l'ordre. Un exécuteur piloté par le graphe pourra les appeler directement.
- **SQL dans le module Python**, en constantes à côté du code qui l'exécute : les requêtes y composent les constantes du domaine et les fragments SQL partagés.
- **Journalisation** : la configuration et les sorties restent dans `infrastructure/observability/log.py`, module technique que le pipeline importe. La mise en forme du journal d'un run (`libelles`, `logging_scope`) appartient au pipeline.

## Phasage

Dans l'ordre du pipeline.

### Phase 1 — Socle

- [x] Créer `pipeline/` et ses contrats d'import.
- [x] Y déplacer les modules d'exécution communs : contexte et phase, métriques, journal (`libelles`, `logging_scope`), progression, modes, signaux, ordre des phases, graphe. Les types d'une exécution de phase, partagés avec l'observabilité et l'API, rejoignent `domain/pipeline_runs.py`.

### Phase 2 — Acquisition

- [x] `extract`, une source à la fois, en commençant par HAL, avec le client HTTP de chaque source. 5f65bcee2, fb71aebab
- [x] `fetch_missing`, `fetch_stale`, `fetch_truncated`. 697691729

### Phase 3 — Normalisation et structures

- [x] `normalize`, `affiliations`. a11d8eab5, efde18c6c

### Phase 4 — Référentiels

- [x] `resolve_ra`, `publishers_journals`, `metadata_correction`. a207d4730, 844aef4cd, d9d542139

### Phase 5 — Résolution

- [x] `publications`, `persons`, `authorships`. 9a96b677c, 3efd34841, e7ce48f68

### Phase 6 — Enrichissements

- [ ] `relations`, `subjects`, `countries`, `oa_status`. Les écritures d'administration du port des pays (ajout par lot, recopie sur les adresses jumelles) rejoignent le dépôt des adresses ; le pipeline expose le recalcul des pays des notices et publications d'un lot d'adresses.

### Phase 7 — Fin

- [ ] `run_pipeline` dans `pipeline/` ; suppression de `interfaces/cli/phases`, des ports et des adaptateurs du pipeline.
- [ ] Les opérations du pipeline quittent `application/services`.

## Questions ouvertes

- Recalculs ciblés appelés par l'API : lesquels garder, lesquels laisser au run suivant ?
- Scripts `imports/` et `maintenance/` : nœuds manuels du pipeline, ou outils à part ? Tri des scripts `oneshot/` déjà joués.
