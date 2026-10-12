# Chantier — Le pipeline en paquet racine

## Contexte

Le pipeline tient sur quatre couches de l'architecture hexagonale : orchestrateurs dans `application/pipeline`, ports dans `application/ports/pipeline`, adaptateurs SQL dans `infrastructure/pipeline`, câblage dans `interfaces/cli/phases`. Pour une suite de transformations de tables en tables, la séparation entre logique et SQL est artificielle : la logique est souvent le SQL. Les opérations du pipeline (« trouver ou créer » une revue, créer une publication, rattacher une signature) vivent dans `application/services`, que seul le pipeline appelle.

La cible est posée par la question 5 de la fiche [Architecture cible du pipeline](CODE_architecture-cible-pipeline.md).

## Décisions

- **Un paquet racine `pipeline/`**, hors des couches hexagonales, sans ports : chaque nœud contient son SQL. Les règles pures restent dans `domain/`.
- **Découpage par domaine** : `pipeline/sources/<source>`, `pipeline/structures`, `pipeline/containers`, `pipeline/publications`, `pipeline/persons` ; `graph.py` et l'orchestrateur à la racine. Chaque nœud rejoint le domaine des tables qu'il écrit : les relations, les sujets et le statut open access vont dans `pipeline/publications`, les pays dans `pipeline/structures`.
- **Règles d'import** vérifiées par `import-linter` : `pipeline/` importe `domain/` et les modules techniques d'`infrastructure/` (connexion, réglages, journalisation, fragments SQL), jamais `application/` ni `interfaces/`. `application/` et `infrastructure/` n'importent pas `pipeline/`. Le pipeline possède les fonctions qu'il partage avec l'API.
- **Interface publique `pipeline/public.py`** : seul module du pipeline que l'API importe. Il exporte l'ordre des phases et les recalculs ciblés. `application/` les déclare comme ports, et `deps.py` les remplit depuis `public.py`.
- **Régime de transition** : pendant la migration, des exceptions aux règles d'import couvrent le code du pipeline encore dans les couches. Elles sont listées dans `pyproject.toml`, module par module, et disparaissent avec la phase 7.
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

- [x] `relations`, `subjects`, `countries`, `oa_status`. Les écritures d'administration du port des pays (ajout par lot, recopie sur les adresses jumelles) rejoignent le dépôt des adresses ; le pipeline expose le recalcul des pays des notices et publications d'un lot d'adresses. dca9cbcec, db4425ba5, 1038f22b0, afaa9712d

### Phase 7 — Fin

- [x] `run_pipeline` dans `pipeline/run.py` ; le câblage de chaque phase (`build`) rejoint le module de la phase ; suppression de `interfaces/cli/phases` et des ports techniques (issues de requête, circuit-breaker, dumps, empreinte, parallélisme), repliés dans l'infrastructure. 01d7da467, 6fbbccdab
- [x] Les implémentations des ports que l'API appelle (clôture des périmètres, `in_perimeter` ciblé, construction des authorships) rejoignent `pipeline/` ; `deps.py` les injecte. 028c1cc33
- [x] `pipeline/public.py`, seul module du pipeline que l'API importe.
- [x] Les opérations « trouver ou créer » (revues, monographies, éditeurs) passent dans `pipeline/containers`, sans les ports `containers`, `journals`, `monographs`, `publishers`.
- [x] La création et le recalcul d'une publication, la requalification des publications d'une revue et la fusion de deux revues passent dans `pipeline/`. `public.py` les exporte. Le service des revues garde le contrôle de la paire et l'audit.
- [ ] Les types des corrections de métadonnées, de la construction des authorships et des périmètres passent dans `pipeline/`.
- [ ] Import du dump ROR dans `pipeline/structures`.
- [ ] Opérations du pipeline sur les personnes (création, nom, identifiants, rattachement d'une signature) dans `pipeline/persons`, sans `PersonRepository` ni `AuthorshipRepository`.
- [ ] Suppression des exceptions aux règles d'import dans `pyproject.toml`.
- [ ] Les recalculs que les dépôts appellent directement (`publications.in_perimeter` depuis le dépôt des personnes, `pub_count` depuis les fusions de revues et d'éditeurs) restent dans `infrastructure/pipeline/authorships`, selon la réponse à la question des recalculs ciblés.

## Questions ouvertes

- Recalculs ciblés appelés par l'API : lesquels garder, lesquels laisser au run suivant ? Concerne la clôture des périmètres et `in_perimeter`, la reconstruction d'une authorship et les `pub_count`, les corrections de métadonnées après l'édition d'une revue, les pays d'un lot d'adresses, la création et le nom d'une personne, le recalcul d'une publication.
- Scripts `imports/` et `maintenance/` : nœuds manuels du pipeline, ou outils à part ? Tri des scripts `oneshot/` déjà joués.
