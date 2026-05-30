# Chantier — Dérive `pub_meta` des normalizers

Commencé et terminé le 2026-05-29

## Contexte

Chaque normalizer expose une paire `extract_pub_metadata(record, journal_id) → dict` puis `insert_<source>_document(..., pub_meta)`. L'intention d'origine, trahie par le commentaire fossile répété partout (`# Métadonnées de publication (pour création différée)`), était que `extract_pub_metadata` porte les champs de la publication *canonique* pour sa création différée, et que `insert_*` les consomme.

Cette intention est caduque : la construction du canonique est passée à l'agrégation (`refresh_from_sources` dans `domain/publications/aggregation.py`). `extract_pub_metadata` n'a plus de rôle de porteur du canonique. Résultat, une dérive présente sur 4 sources :

- **theses.fr** : seule source propre. `insert_source_document` consomme `pub_meta` intégralement (`doi`, `title`, `pub_year`, `doc_type`, `journal_id`, `oa_status`, `language`, `container_title`) ; la docstring note que le record brut « ne sert ici » à rien.
- **openalex, hal, wos, scanr** : `extract_pub_metadata` calcule un jeu complet, mais `insert_*_document` n'en consomme que `journal_id`, `oa_status`, `language`, `container_title`, et **recalcule `doi`, `title`, `pub_year`, `doc_type`, `nnt` indépendamment** depuis le record brut. Les autres champs du dict sont calculés puis jetés.

Le symptôme visible était `correct_openalex_doc_type` : `extract_pub_metadata` calculait un `doc_type` *corrigé*, jamais lu par `insert_openalex_document` (qui prenait `work.get("type")` brut). La correction theses.fr/dumas n'a donc jamais tourné. Ce dead code a été supprimé dans le chantier `METIER_metadata-correction` ; ce chantier-ci traite la dérive structurelle dont il était l'affleurement.

Enjeu : double extraction par source (deux fonctions à maintenir, qui peuvent diverger silencieusement comme l'a prouvé le `doc_type`), et un dict à moitié mort qui ment sur ce qu'il sert.

## Décisions

- Direction retenue : aligner les 4 sources sur le patron theses.fr — `extract_pub_metadata` reste le point d'extraction unique, `insert_*_document` consomme tous ses champs, plus aucune ré-extraction depuis le record brut dans l'insert.
- `pub_meta` devient obligatoire dans la signature `insert_*_document` (suppression du default `= None`). Le seul callsite production le passait déjà toujours.
- `source_publications` stocke le brut par source ; `extract_pub_metadata` produit exactement ces valeurs brutes, pas une forme transformée. Toute transformation de cohérence relève de `effective_metadata` (cf. `METIER_metadata-correction`), pas de l'extraction.

## Audit (dérives identifiées)

| Source | Champ | Dérive | Tranchée |
|---|---|---|---|
| OpenAlex | `doc_type` | absent de `extract`, insert lit `work.get("type")` brut | ajouter à `extract`, insert consomme `pub_meta["doc_type"]` |
| OpenAlex | `nnt` | `extract` le retourne, insert ré-extrait dans `location_ids` | insert consomme `pub_meta["nnt"]` et le merge dans `external_ids` |
| HAL | `doc_type` | `extract` retourne dérivé (`derive_hal_doc_type`), insert stocke brut (concat `ART_review-article`) | `extract` retourne le brut concaténé (alignement règle « brut par source ») |
| HAL | `nnt` | `extract` le retourne, insert ré-extrait dans `external_ids` | insert consomme `pub_meta["nnt"]` |
| Scanr | `doc_type` | `extract` a `or "other"` fallback, insert non | `extract` retourne brut sans fallback (la colonne `source_publications.doc_type` est nullable text) |
| Scanr | `language` | absent de `extract`, insert lit `pub_meta.get("language")` → toujours `None` | ajouter `language=None` à `extract` (l'API Scanr n'expose pas le champ) |
| Scanr | `nnt` | `extract` le retourne, insert ré-extrait dans `ext` | insert consomme `pub_meta["nnt"]` |
| WoS | (rien) | `extract` repackage `rec[*]`, insert lit `rec[*]` directement ; mêmes valeurs | insert consomme `pub_meta` pour homogénéité du patron |

## Phasage

- [x] Audit : tableau source × champ confrontant valeur `pub_meta` vs valeur recalculée dans `insert_*` (cf. section Audit ci-dessus).
- [x] Résorption des écarts documentés (chacun tranché dans la colonne « Tranchée » de l'audit).
- [x] Collapse : `insert_*_document` consomme `pub_meta` en entier. Une source par commit.
  - `5fe2957d` — WoS
  - `0390181e` — Scanr
  - `3727d56f` — HAL
  - `0b07b3b7` — OpenAlex
- [x] Tests : non-régression — les tests unitaires des 4 sources passent à l'identique sur ce qui est persisté dans `source_publications`.

## Liens

- [`METIER_metadata-correction.md`](METIER_metadata-correction.md) — origine de la découverte ; la suppression de `correct_openalex_doc_type` y est faite.
