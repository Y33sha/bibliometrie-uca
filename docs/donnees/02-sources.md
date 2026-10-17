# Schéma `sources`

*À jour le 2026-10-12.*

Tables sources : les *records* non dédupliqués, normalisés à partir des payloads des API tierces. Toutes les sources partagent les mêmes tables, discriminées par la colonne `source` (enum `source_type` : hal, openalex, wos, scanr, theses, crossref, datacite).

## Tables

- **`source_publications`** : un enregistrement par document par source. Relié à `publications` via `publication_id` (peut être NULL si pas encore rattaché). Contient les métadonnées (doc_type non mappé, oa_status, abstract, keywords, topics, biblio, meta).
- **`source_authorships`** : une signature — un auteur sur un document source. `person_id` la relie à la personne, `identity_id` à son identité d'auteur. `collective` marque une signature collective (collaboration, consortium…), sans personne. L'authorship qu'elle atteste se déduit de sa notice et de sa personne : celle du couple (publication de la notice, personne). Ses adresses passent par `source_authorship_addresses`, d'où la matview `source_authorship_structures` dérive ses structures.
- **`author_identifying_keys`** : les attributs d'identité d'une signature — nom normalisé et identifiants. Une ligne par identité distincte, que `source_authorships.identity_id` référence : toutes les signatures de même identité la partagent.
- **`source_authorship_addresses`** : table de liaison `source_authorships ↔ addresses`. Permet aux normalizers de partager une même chaîne d'adresse normalisée (`addresses.raw_text` → `addresses.normalized_text`) entre plusieurs authorships, et alimente la résolution structure ↔ adresse de la phase `affiliations`.
- **`source_authorship_rors`** : ROR attribués par la source à une signature, rattachés à l'adresse de leur affiliation, ou à la seule signature quand l'affiliation est sans texte.
- **`candidate_dois`** : vue des DOI des publications du périmètre, lus par le rattrapage par DOI et la résolution des agences d'enregistrement.
- **`staging`** : une ligne par document moissonné. Contient le payload brut de la source, vidé après normalisation, et `disappeared_at` quand la source cesse de rendre le document. Son cycle de vie relève du [moissonnage](../pipeline/02-extract.md).
- **`failed_lookups`** : identifiants (DOI, hal-id, NNT) cherchés en vain dans une source, et DOI que doi.org ne connaît pas (source `doi_org`), avec la date de l'échec.

## Propriété des tables

| Table | Auteur | Écrit par |
|---|---|---|
| `staging` | pipeline | phases `extract`, `fetch_missing` et `fetch_stale` (`pipeline/ingestion/common/staging.py`) |
| `failed_lookups` | pipeline | phase `fetch_missing` (`pipeline/ingestion/<source>/fetch_missing.py`) |
| `source_publications` | pipeline | `pipeline/ingestion/<source>/normalize.py` |
| `author_identifying_keys` | pipeline | `pipeline/ingestion/<source>/normalize.py` (via `pipeline/ingestion/common/signatures.py`) |
| `source_authorships` | mixte | `pipeline/ingestion/<source>/normalize.py` ; `in_perimeter` par la phase `affiliations` ; `person_id` par le pipeline ou en admin (orphan-assign) |
| `source_authorship_addresses` | pipeline | `pipeline/ingestion/<source>/normalize.py` (via `pipeline/ingestion/common/signatures.py`) |
