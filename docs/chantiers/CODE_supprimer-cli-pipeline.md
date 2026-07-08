# Supprimer le dossier `interfaces/cli/pipeline/`

## Contexte

Les modules de `interfaces/cli/pipeline/` sont des points d'entrée en ligne de commande, un par phase ou par sous-étape du pipeline. Chacun ouvre une connexion, construit les adapters (queries, repos), appelle un orchestrateur de `application/pipeline/…`, puis commite. Ils dupliquent le rôle des wrappers `_run_*` de `run_pipeline.py`, qui font exactement le même câblage : ce sont deux composition roots parallèles pour les mêmes orchestrateurs. Le pipeline se lance en pratique via `run_pipeline` (`--only`, `--from`), jamais par ces CLI.

Inventaire des 30 modules (hors `__init__.py`) :

- **27 coquilles pures** : elles n'appellent qu'un orchestrateur applicatif existant et ne sont importées par aucun code Python, ni invoquées par aucun script shell ou tâche planifiée. Directement supprimables.
- **3 modules countries** portent de la logique d'orchestration (boucles de matching, résolution de conflits, pagination par batch, métriques) que `run_pipeline` importe : `detect_address_countries.py` (`detect_countries`, importé ligne 1978), `detect_place_countries.py` (`detect_place_countries`, ligne 2018), `suggest_address_countries.py` (`suggest_countries`, ligne 2037). Tant que cette logique vit dans la CLI, `run_pipeline` en dépend et le dossier ne peut pas disparaître.

Le package cible `application/pipeline/countries/` existe déjà et héberge les algorithmes purs (`PlaceNameDetector`, `CountrySuggester`) ainsi que l'orchestrateur `refresh` de `refresh_publication_countries.py` — ce dernier étant le modèle de référence : `run_pipeline._run_refresh_publication_countries` l'importe déjà depuis `application/`, sans passer par la CLI. Le SQL brut de la détection countries vit déjà en `infrastructure/queries/pipeline/countries.py`. Il ne reste donc à déplacer que la logique Python d'orchestration des trois étapes de détection.

La documentation décrit ces CLI comme un pattern délibéré (composition roots one-shot) : `docs/architecture/06-composition-roots.md`, `CONTRIBUTING.md` (modèle pour ajouter une source ou une phase), `docs/pipeline/11-enrichissements.md` (chemins des modules countries), `docs/exploitation/04-pipeline.md` (arborescence des logs). Ces pages sont à réviser une fois le dossier supprimé.

## Décisions

- Extraire les trois fonctions d'orchestration countries vers `application/pipeline/countries/`, rediriger les imports de `run_pipeline`, puis supprimer l'intégralité de `interfaces/cli/pipeline/`.
- `run_pipeline` (ses wrappers `_run_*`) devient le composition root unique des phases du pipeline. La révision de `06-composition-roots.md` acte ce déplacement : le composition root d'une phase n'est plus un script CLI mais le wrapper `_run_*` correspondant.
- Placement des orchestrateurs extraits, par symétrie avec `refresh_publication_countries.py::refresh` (un module d'orchestration par étape) : `application/pipeline/countries/detect_address_countries.py`, `application/pipeline/countries/detect_place_countries.py`, et l'orchestrateur de suggestion ajouté dans le module existant `suggest_countries.py`, à côté de `CountrySuggester`.
- Le dossier `interfaces/cli/oneshot/` (remédiations ponctuelles) est hors périmètre : ce ne sont pas des phases du pipeline.

## Phasage

### Phase 1 — Extraction de l'orchestration countries

- [ ] `detect_address_countries` : déplacer la fonction et ses helpers (`load_country_forms`, `extract_last_segment`, `show_stats`, les `select()` inline) vers `application/pipeline/countries/detect_address_countries.py`. Rediriger l'import de `run_pipeline` (ligne 1978) vers `application/`.
- [ ] `detect_place_countries` : déplacer l'orchestration (chargement des formes, boucle, décision de conflit) vers `application/pipeline/countries/detect_place_countries.py`, en réutilisant `PlaceNameDetector`. Rediriger l'import (ligne 2018).
- [ ] `suggest_address_countries` : déplacer la boucle de batch/pagination et les métriques dans `suggest_countries.py`, en réutilisant `CountrySuggester`. Rediriger l'import (ligne 2037).
- [ ] Vérifier que la phase `countries` de `run_pipeline` tourne à l'identique (mêmes compteurs, mêmes écritures) après redirection.

### Phase 2 — Suppression du dossier

- [ ] Supprimer les 30 modules et `__init__.py` de `interfaces/cli/pipeline/`.
- [ ] Retirer de `tests/unit/test_imports.py` les entrées `interfaces.cli.pipeline.extract_hal` et `interfaces.cli.pipeline.fetch_missing_doi`.
- [ ] Vérifier qu'aucun import résiduel ne pointe vers `interfaces.cli.pipeline` (hors fiches archivées).

### Phase 3 — Documentation

- [ ] `docs/architecture/06-composition-roots.md` : le composition root d'une phase est le wrapper `_run_*` de `run_pipeline`, pas un script CLI.
- [ ] `CONTRIBUTING.md` : réécrire les sections « ajouter une source / une phase » qui prennent les CLI comme modèle.
- [ ] `docs/pipeline/11-enrichissements.md` : chemins des modules countries pointant vers `application/pipeline/countries/`.
- [ ] `docs/exploitation/04-pipeline.md` : arborescence des logs sans `logs/interfaces/cli/pipeline/`.

## Questions ouvertes

- Noms des fonctions extraites : uniformiser en `run(...)` (comme les orchestrateurs de phase récents) ou garder des noms descriptifs proches de l'existant (`detect_countries`, etc.) ? Le module `refresh_publication_countries.py` utilise le nom court `refresh`.
- `detect_address_countries` et `detect_place_countries` : deux modules distincts (proposé) ou un seul module `detect.py` regroupant les deux étapes de détection ?
