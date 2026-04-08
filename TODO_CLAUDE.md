# Notes techniques et idées (Claude)

## Renommage is_uca → in_perimeter

Renommer pour abstraire le code de l'institution spécifique (réutilisabilité).

**Colonnes à renommer :**
- `is_uca` → `in_perimeter` sur hal_authorships, openalex_authorships, wos_authorships, scanr_authorships, authorships
- Index associés (`idx_*_uca` → `idx_*_perimeter`)

**Scripts à renommer :**
- `utils/uca_perimeter.py` → `utils/perimeter.py` (fonctions `get_uca_structure_ids` → `get_perimeter_ids`)

**Références à mettre à jour :**
- `build_authorships.py` (propagation is_uca → in_perimeter)
- Backend : routers qui filtrent sur is_uca
- Frontend : filtres/facettes UCA

**Note :** `populate_uca_flags.py` → `populate_affiliations.py` et la phase pipeline `uca_flags` → `affiliations` sont déjà faits. Reste le renommage des colonnes et de `uca_perimeter.py`.

## Tests d'idempotence — phases restantes

Les tests d'idempotence couvrent la normalisation (4 sources + inter-sources, 11 tests). Reste à couvrir :
- `create_persons_from_source_authorships.py` (risque de doublons de personnes)
- `build_authorships.py` (risque de doublons d'authorships vérité)
- `populate_affiliations.py` (idempotent par construction, mais à vérifier)

## Uniformisation compatibilité de noms (Python vs SQL)

Les fonctions de compatibilité de noms existent en deux versions :
- Python : `utils/names.py` (`names_compatible`, `first_names_compatible`, etc.)
- SQL : requêtes dans `backend/routers/admin_person_duplicates.py` (`PERSON_DUP_QUERIES`)

Les deux implémentent la même logique mais indépendamment. Idéalement, le backend devrait utiliser les fonctions Python de `utils/names.py` pour la détection de doublons. Mais les requêtes SQL sont plus performantes pour le matching en masse (JOIN direct en base). À réévaluer si la logique diverge.

## Authorships vérité : FK source-agnostiques

Les colonnes `hal_authorship_id`, `openalex_authorship_id`, `wos_authorship_id`, `scanr_authorship_id` sur `authorships` ne sont pas extensibles (ajouter une source = ajouter une colonne). Envisager une inversion des FK (les tables source pointent vers authorships) ou un tableau. Chantier structurel, à planifier.
