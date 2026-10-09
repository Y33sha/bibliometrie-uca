# Chantier — Duplications dans les tests

## Contexte

Chaque fichier de test définit ses propres fonctions de semis (`_create_pub`, `_create_person`…). Les mêmes fonctions se retrouvent ainsi recopiées d'un fichier à l'autre, avec de petites variantes : colonnes renseignées, valeurs par défaut, ordre des paramètres.

Familles recensées, hors tests d'API :

| Fonction | Copies | Variantes |
|---|---|---|
| `_create_pub` | 12 | 9 |
| `_create_person` | 12 | 10 |
| `_person` | 6 | 4 |
| `_create_structure` | 5 | 5 |
| `_create_address` | 5 | 5 |
| `_create_sd` (notice) | 5 | 4 |
| `_insert_publication` | 5 | 5 |
| `_pub` | 5 | 5 |
| `_set_config` | 5 | 4 |
| `_create_sa` (signature) | 4 | 4 |
| `_ensure_country` | 4 | 2 |
| `_signature` | 4 | 4 |
| `_structure` | 4 | 4 |
| `_perimeter` | 3 | 3 |

S'y ajoutent les fonctions communes aux tests des extracteurs (`_config`, `_avancement`, `_page`, `_extracteur`) et la fixture `_cleanup_after_module` des tests d'API, dont seule la liste des tables à vider change.

Certains noms couvrent des fonctions sans rapport d'un fichier à l'autre : `_run`, `_row`, `_adapter`, `_args`, `_record`.

## Décisions

- Les fonctions de semis vivent dans `tests/integration/helpers/`, un module par famille d'entités.
- Deux accès : connexion SQLAlchemy (`sa_sync_conn`) pour les tests de requêtes et de services, curseur du pool propriétaire (`owner_pool`) pour les tests d'API (`helpers/seeds.py`).
- Une fonction commune accepte, en paramètres nommés, les colonnes que les variantes renseignent. Seul le premier paramètre métier reste positionnel.

## Phasage

### Phase 1 — Tests d'API

- [x] `helpers/seeds.py` : `uniq`, structure, forme de nom de structure, adresse, périmètre, éditeur, revue, personne, publication, notice, signature. Identité d'auteur partagée avec `helpers/authorships.py`.
- [ ] Fixture de nettoyage commune, paramétrée par la liste des tables.

### Phase 2 — Tests de requêtes et de services

- [ ] Publications : `_create_pub`, `_pub`, `_insert_publication`.
- [ ] Personnes : `_create_person`, `_person`.
- [ ] Notices et signatures : `_create_sd`, `_create_sa`, `_signature`.
- [ ] Structures, adresses, périmètres et pays : `_create_structure`, `_structure`, `_create_address`, `_perimeter`, `_ensure_country`.
- [ ] Configuration : `_set_config`, à aligner sur `helpers/config.insert_config`.

### Phase 3 — Tests des extracteurs

- [ ] `_config`, `_avancement`, `_page`, `_extracteur`.

## Questions ouvertes

- `_run`, `_row`, `_adapter`, `_args`, `_record` : homonymes seulement, ou duplications partielles ?
