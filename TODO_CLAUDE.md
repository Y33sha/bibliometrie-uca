# Notes techniques (Claude)


## ~~Listes de sources hardcodées~~ QUASI TERMINÉ

Les routeurs et services utilisent `ALL_SOURCES_SET` ou `AUTHOR_SOURCES_SQL` de `utils/sources.py`.

Restent des listes intentionnelles (sources avec adresses vs structures HAL) :
- `refresh_publication_countries.py:87` — `('openalex', 'wos', 'scanr')` : sources avec adresses (pas HAL)
- `merge_pubs_by_hal_id.py:44` — `('openalex', 'scanr')` : sources non-HAL à fusionner
- `services/authorships.py:208` — `('openalex', 'wos', 'scanr')` : sources avec adresses

Pourrait bénéficier d'une constante `SOURCES_WITH_ADDRESSES` dans `utils/sources.py` si le pattern se répand.

## Uniformisation compatibilité de noms (Python vs SQL)

Les fonctions de compatibilité de noms existent en deux versions :
- Python : `utils/names.py` (`names_compatible`, `first_names_compatible`, etc.)
- SQL : requêtes dans `backend/routers/admin_person_duplicates.py` (`PERSON_DUP_QUERIES`)

Les deux implémentent la même logique mais indépendamment. À réévaluer si la logique diverge.
