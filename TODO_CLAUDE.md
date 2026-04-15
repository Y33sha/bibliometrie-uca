# Notes techniques (Claude)

## ~~Renommage uca_perimeter → perimeter~~ FAIT

## ~~Valeurs hardcodées `structure_id = 169`~~ FAIT

Plus aucune occurrence en dur. Toutes les lectures passent par `get_root_structure_id()` (DB config + périmètres).

## ~~Listes de sources hardcodées~~ QUASI TERMINÉ

Les routeurs et services utilisent `ALL_SOURCES_SET` ou `AUTHOR_SOURCES_SQL` de `utils/sources.py`.

Restent des listes intentionnelles (sources avec adresses vs structures HAL) :
- `refresh_publication_countries.py:87` — `('openalex', 'wos', 'scanr')` : sources avec adresses (pas HAL)
- `merge_pubs_by_hal_id.py:44` — `('openalex', 'scanr')` : sources non-HAL à fusionner
- `services/authorships.py:208` — `('openalex', 'wos', 'scanr')` : sources avec adresses

Pourrait bénéficier d'une constante `SOURCES_WITH_ADDRESSES` dans `utils/sources.py` si le pattern se répand.

## ~~Tests d'idempotence~~ FAIT

## Uniformisation compatibilité de noms (Python vs SQL)

Les fonctions de compatibilité de noms existent en deux versions :
- Python : `utils/names.py` (`names_compatible`, `first_names_compatible`, etc.)
- SQL : requêtes dans `backend/routers/admin_person_duplicates.py` (`PERSON_DUP_QUERIES`)

Les deux implémentent la même logique mais indépendamment. À réévaluer si la logique diverge.

## Sémantique `publications` → `documents`

Renommage envisagé dans TODO_LAURA. Si décidé, impacte : table, colonnes FK, routes API, frontend. Mieux vaut le faire avant transmission DSI.
