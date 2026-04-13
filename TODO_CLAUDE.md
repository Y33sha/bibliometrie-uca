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

## Observabilité

- [x] Health check endpoint (`/api/health`)
- [ ] Rapport de synthèse pipeline : publis ajoutées/modifiées/erreurs par run, consultable côté admin (table `pipeline_runs` ?)

## Refactoring normaliseurs — doc_types et find_publication

Suite du commit 325bd76. Reste à faire :

### 1. Supprimer les DOCTYPE_MAP locaux des normaliseurs (OA, WoS, ScanR)
Les normaliseurs mappent encore le doc_type avant stockage dans source_documents via leur `DOCTYPE_MAP` local. Il faudrait :
- Stocker le doc_type **brut** (valeur source) dans source_documents
- Supprimer les `DOCTYPE_MAP` de normalize_openalex, normalize_wos, normalize_scanr
- Remplacer par `map_doc_type(raw, source)` aux seuls endroits où un type canonique est nécessaire (appels à `find_or_create` / `resolve_doi_conflict`)
- Attention : la base existante a un mélange de valeurs brutes et mappées ; `map_doc_type` gère les deux cas (fallback identity)

### 2. Factoriser find_publication / extract_pub_metadata
Chaque normaliseur a sa propre version de `extract_pub_metadata` + `find_publication` qui font la même chose : extraire DOI/NNT/titre/année et chercher une publication existante. La seule différence est le parsing du format brut de chaque source. Factoriser en un `find_publication(cur, doi, nnt, title_normalized, pub_year, doc_type)` partagé dans services/publications.py, appelé par les normaliseurs après extraction des champs.

### 3. Tests
- Vérifier que les tests existants (test_reprocessing, test_idempotence, test_normalize) passent après ces changements — ils importent les `DOCTYPE_MAP` locaux
- Migrer les tests vers `map_doc_type` de utils/doc_types.py

## Scalabilité

- [ ] Connection pooling DB (remplacer `psycopg2.connect()` par un pool dans `get_cursor()` — changement localisé)

