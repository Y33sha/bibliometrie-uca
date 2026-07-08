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
- Chaque orchestrateur extrait est une fonction `run(...)`, par uniformité avec les orchestrateurs de phase récents.
- Les deux étapes de détection détectent le pays d'une adresse ; leur signal les distingue. Renommage en conséquence, par symétrie avec `refresh_publication_countries.py::refresh` (un module d'orchestration par étape) : détection par **nom de pays** (segment final de l'adresse) → `application/pipeline/countries/detect_by_country_name.py`, détection par **nom de lieu** (institution ou ville, dans le corps de l'adresse) → `detect_by_place_name.py`. L'orchestration de suggestion est ajoutée au module existant `suggest_countries.py`, à côté de `CountrySuggester`.
- Le dossier `interfaces/cli/oneshot/` (remédiations ponctuelles) est hors périmètre : ce ne sont pas des phases du pipeline.

## Phasage

### Phase 1 — Extraction de l'orchestration countries

- [x] Détection par nom de pays : orchestration déplacée vers `application/pipeline/countries/detect_by_country_name.py::run` (dépend du port `CountryQueries`) ; les `select()` inline deviennent des méthodes du port (`load_country_forms`, `fetch_addresses_missing_country_raw`, `write_countries`). Wrapper `run_pipeline` renommé `_run_detect_by_country_name` (commit au caller). Module CLI supprimé.
- [x] Détection par nom de lieu : orchestration déplacée vers `application/pipeline/countries/detect_by_place_name.py::run` (réutilise `PlaceNameDetector`) ; `load_place_forms` et `fetch_addresses_missing_country_normalized` passent par le port. Wrapper renommé `_run_detect_by_place_name` (commit au caller). Module CLI supprimé.
- [x] Suggestion : orchestrateur `run` ajouté à `suggest_countries.py` (à côté de `CountrySuggester`), commit par batch conservé (progression durable). `count_suggest_eligible`, `fetch_suggest_targets_chunk`, `load_country_pool` passent par le port ; `SuggestEligibleCounts` déplacé dans le module du port. Import redirigé. Module CLI supprimé.
- [ ] Vérifier que la phase `countries` de `run_pipeline` tourne à l'identique (mêmes compteurs, mêmes écritures) : câblage et non-régression des tests infra/algorithme validés ; le run complet reste à confirmer sur base réelle.

### Phase 2 — Suppression du dossier

- [ ] Supprimer les 30 modules et `__init__.py` de `interfaces/cli/pipeline/`.
- [ ] Retirer de `tests/unit/test_imports.py` les entrées `interfaces.cli.pipeline.extract_hal` et `interfaces.cli.pipeline.fetch_missing_doi`.
- [ ] Vérifier qu'aucun import résiduel ne pointe vers `interfaces.cli.pipeline` (hors fiches archivées).

### Phase 3 — Documentation

- [ ] `docs/architecture/06-composition-roots.md` : le composition root d'une phase est le wrapper `_run_*` de `run_pipeline`, pas un script CLI.
- [ ] `CONTRIBUTING.md` : réécrire les sections « ajouter une source / une phase » qui prennent les CLI comme modèle.
- [ ] `docs/pipeline/11-enrichissements.md` : chemins des modules countries pointant vers `application/pipeline/countries/`.
- [ ] `docs/exploitation/04-pipeline.md` : arborescence des logs sans `logs/interfaces/cli/pipeline/`.
