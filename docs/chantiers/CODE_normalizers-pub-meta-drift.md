# Chantier — Dérive `pub_meta` des normalizers

## Contexte

Chaque normalizer expose une paire `extract_pub_metadata(record, journal_id) → dict` puis `insert_<source>_document(..., pub_meta)`. L'intention d'origine, trahie par le commentaire fossile répété partout (`# Métadonnées de publication (pour création différée)`), était que `extract_pub_metadata` porte les champs de la publication *canonique* pour sa création différée, et que `insert_*` les consomme.

Cette intention est caduque : la construction du canonique est passée à l'agrégation (`refresh_from_sources` dans `domain/publications/aggregation.py`). `extract_pub_metadata` n'a plus de rôle de porteur du canonique. Résultat, une dérive présente sur 4 sources :

- **theses.fr** : seule source propre. `insert_source_document` consomme `pub_meta` intégralement (`doi`, `title`, `pub_year`, `doc_type`, `journal_id`, `oa_status`, `language`, `container_title`) ; la docstring note que le record brut « ne sert ici » à rien.
- **openalex, hal, wos, scanr** : `extract_pub_metadata` calcule un jeu complet, mais `insert_*_document` n'en consomme que `journal_id`, `oa_status`, `language`, `container_title`, et **recalcule `doi`, `title`, `pub_year`, `doc_type`, `nnt` indépendamment** depuis le record brut. Les autres champs du dict sont calculés puis jetés.

Le symptôme visible était `correct_openalex_doc_type` : `extract_pub_metadata` calculait un `doc_type` *corrigé*, jamais lu par `insert_openalex_document` (qui prenait `work.get("type")` brut). La correction theses.fr/dumas n'a donc jamais tourné. Ce dead code a été supprimé dans le chantier `METIER_metadata-correction` ; ce chantier-ci traite la dérive structurelle dont il était l'affleurement.

Enjeu : double extraction par source (deux fonctions à maintenir, qui peuvent diverger silencieusement comme l'a prouvé le `doc_type`), et un dict à moitié mort qui ment sur ce qu'il sert.

## Décisions

*(à confirmer — section questionnable)*

- Direction pressentie : aligner les 4 sources sur le patron theses.fr — `extract_pub_metadata` reste le point d'extraction unique, `insert_*_document` consomme tous ses champs, plus aucune ré-extraction depuis le record brut dans l'insert.
- Préalable obligatoire avant de collapser : audit champ par champ, source par source, que la valeur de `pub_meta` *égale* celle recalculée par l'insert — sinon documenter et trancher l'écart. Le cas `doc_type` OpenAlex a montré qu'un écart peut exister (corrigé vs brut) ; il faut vérifier qu'il n'en reste pas d'autres (ex. `clean_doi` appliqué d'un côté pas de l'autre, `title` avec fallback `display_name`, `nnt` normalisé différemment).
- `source_publications` stocke le brut par source ; `extract_pub_metadata` doit produire exactement ces valeurs brutes, pas une forme transformée. Toute transformation de cohérence relève de `effective_metadata` (cf. `METIER_metadata-correction`), pas de l'extraction.

## Phasage

*(à confirmer)*

1. Audit : tableau source × champ confrontant valeur `pub_meta` vs valeur recalculée dans `insert_*`. Identifier les écarts réels.
2. Résorption des écarts documentés (chacun tranché explicitement : lequel est correct).
3. Collapse : `insert_*_document` consomme `pub_meta` en entier, suppression de la ré-extraction. Une source par commit.
4. Tests : non-régression sur ce qui est persisté dans `source_publications` pour chaque source.

## Questions ouvertes

- Direction confirmée (consommer `pub_meta` partout) ou l'inverse (supprimer les champs morts du dict en gardant la ré-extraction dans l'insert) ? La première unifie sur la source propre, la seconde est plus locale mais laisse deux extractions.
- Y a-t-il des champs qui *doivent* légitimement différer entre l'extraction et l'insert ? Si oui, le collapse n'est pas total et il faut nommer l'exception.
- Articulation avec `METIER_metadata-correction` : ce dernier retire déjà les corrections à l'ingestion. À faire après que la liquidation `correct_openalex_doc_type` soit posée pour ne pas se marcher dessus.

## Liens

- [`METIER_metadata-correction.md`](METIER_metadata-correction.md) — origine de la découverte ; la suppression de `correct_openalex_doc_type` y est faite.
