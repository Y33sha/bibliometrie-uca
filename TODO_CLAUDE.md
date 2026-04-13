# Notes techniques (Claude)

## ~~Renommage uca_perimeter → perimeter~~ FAIT

Fichier renommé `utils/perimeter.py`, alias `get_uca_*` supprimés, 8 appelants mis à jour.

Note : les fallbacks dans `perimeter.py` contiennent encore `s.code = 'uca'` (lignes ~109-127). Ce sont des fallbacks de sécurité si la table `perimeters` n'est pas configurée. À supprimer ou rendre configurable dans le cadre du point 1 (valeurs hardcodées).

## Valeurs hardcodées `structure_id = 169`

`budget_structure_id = 169` (UCA) apparaît ~20 fois dans :
- `backend/routers/publications.py` (facettes et listing APC)
- `backend/routers/pub_stats.py` (constante `UCA_STRUCT_ID` + requêtes)

À remplacer par une lecture de la config (périmètre racine) ou un paramètre passé par le frontend.

## Listes de sources hardcodées

`IN ('hal', 'openalex', 'wos')` exclut scanr et theses dans ~11 requêtes :
- `backend/routers/authorships.py` (3 occurrences)
- `backend/routers/persons.py` (5 occurrences)
- `services/persons.py` (1 occurrence)
- `processing/create_persons_from_source_authorships.py` (1 occurrence)
- `scripts/assign_orphans_by_name_form.py` (1 occurrence)

À vérifier au cas par cas : l'exclusion est-elle voulue (pas de raw_affiliations pour scanr/theses) ou accidentelle ?

## Tests d'idempotence — phases restantes

Phases couvertes : normalisation (4 sources + inter-sources, 11+ tests).
Reste à couvrir :
- `create_persons_from_source_authorships.py` (risque de doublons de personnes)
- `build_authorships.py` (risque de doublons d'authorships vérité)
- `populate_affiliations.py` (idempotent par construction, mais à vérifier)

## Uniformisation compatibilité de noms (Python vs SQL)

Les fonctions de compatibilité de noms existent en deux versions :
- Python : `utils/names.py` (`names_compatible`, `first_names_compatible`, etc.)
- SQL : requêtes dans `backend/routers/admin_person_duplicates.py` (`PERSON_DUP_QUERIES`)

Les deux implémentent la même logique mais indépendamment. À réévaluer si la logique diverge.

## Sémantique `publications` → `documents`

Renommage envisagé dans TODO_LAURA. Si décidé, impacte : table, colonnes FK, routes API, frontend. Mieux vaut le faire avant transmission DSI.
