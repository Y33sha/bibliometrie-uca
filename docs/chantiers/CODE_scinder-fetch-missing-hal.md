# Scinder fetch_missing_hal_id (hal-id ⊥ NNT)

## Contexte

Le module `fetch_missing_hal_id` récupère les documents HAL absents du staging, repérés par deux pistes distinctes réunies sous un nom qui n'en décrit qu'une :

- **hal-id** — références remontées d'OpenAlex et ScanR, requête Solr `halId_s:<id>` ;
- **NNT** — thèses soutenues sans document HAL (theses.fr), requête Solr `nntId_s:<nnt>`, mode `full` uniquement.

Les deux chemins interrogent des champs Solr différents, découvrent leurs références dans des sources différentes, insèrent différemment (`insert_halid_result → bool` vs `insert_nnt_result → (api_found, inserted)`) et ne tournent pas dans les mêmes modes. Les deux helpers async (`_fetch_by_halid_async`, `_fetch_by_nnt_async`) sont des quasi-duplicatas.

Ce sont donc deux opérations distinctes : le renommage seul masquerait la cause. On scinde.

## Décisions

- Deux orchestrateurs : `fetch_missing_hal_by_id` (OpenAlex/ScanR → `halId_s`) et `fetch_missing_hal_by_nnt` (theses → `nntId_s`, `full` seulement).
- Un runner async générique partagé (liste de refs → fetch concurrent → insert), paramétré par les fonctions de fetch et d'insert, qui supprime la duplication des deux helpers.
- L'adapter HAL reste unique (`HalFetchMissingAdapter` / `PgHalFetchMissingAdapter`), consommé par les deux orchestrateurs — il porte déjà les deux familles de méthodes, et ses noms sont neutres.
- `cross_imports` appelle les deux sous-étapes (le gate « NNT en mode full » remonte au caller) et les rapporte en deux canaux distincts (`hal-id`, `NNT`).
- Renommage des modules `fetch_missing_hal_id` → `fetch_missing_hal` (application, ports, infrastructure, CLI) : le nom n'est plus trompeur.

## Phasage

- [ ] Renommer les 4 modules `fetch_missing_hal_id` → `fetch_missing_hal` (git mv) et mettre à jour les imports.
- [ ] Orchestrateur : runner async générique + `fetch_missing_hal_by_id` / `fetch_missing_hal_by_nnt`.
- [ ] Câblage : `_run_fetch_missing_hal_by_id` / `_run_fetch_missing_hal_by_nnt`, deux canaux dans `cross_imports` ; CLI appelant les deux orchestrateurs.
- [ ] Tests et docstrings : chemins de modules, non-régression sur les deux chemins.
