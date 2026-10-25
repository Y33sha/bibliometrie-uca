# Schéma `sources`

*À jour le 2026-10-21.*

Tables sources : les *records* non dédupliqués, normalisés à partir des payloads des API tierces. Toutes les sources partagent les mêmes tables, discriminées par la colonne `source` (enum `source_type` : hal, openalex, wos, scanr, theses, crossref, datacite).

## Tables

- **`source_records`** : un enregistrement par document par source. Relié à `publications` via `publication_id` (peut être NULL si pas encore rattaché). Contient les métadonnées (doc_type, raw_doc_type, oa_status, abstract, keywords, topics, biblio, source_extras).
- **`source_record_locations`** : localisations d'un enregistrement source, réécrites à chaque normalisation : URL de la page et du PDF, identifiant OAI-PMH, version, licence, open access, plateforme. OpenAlex donne toutes les copies d'un document, Crossref la page vers laquelle résout le DOI, HAL sa notice et le fichier déposé.
- **`source_contributions`** : une contribution source — un auteur sur un document source. `person_id` la relie à la personne, `contributor_information_id` à ses informations du contributeur. `collective` marque une contribution source collective (collaboration, consortium…), sans personne. La contribution qu'elle atteste se déduit de son enregistrement source et de sa personne : celle du couple (publication de l'enregistrement source, personne). Ses adresses passent par `source_contribution_addresses`, d'où la matview `source_contribution_structures` dérive ses structures.
- **`contributor_information`** : le nom normalisé et les identifiants d'une contribution source. Une ligne par combinaison distincte, que `source_contributions.contributor_information_id` référence : toutes les contributions sources aux mêmes informations la partagent.
- **`source_contribution_addresses`** : table de liaison `source_contributions ↔ addresses`. Permet aux normalizers de partager une même chaîne d'adresse normalisée (`addresses.raw_text` → `addresses.normalized_text`) entre plusieurs contributions, et alimente la résolution structure ↔ adresse de la phase `affiliations`.
- **`source_contribution_rors`** : ROR attribués par la source à une contribution source, rattachés à l'adresse de leur affiliation, ou à la seule contribution source quand l'affiliation est sans texte.
- **`candidate_dois`** : vue des DOI des publications du périmètre, lus par le rattrapage par DOI et la résolution des agences d'enregistrement.
- **`staging`** : une ligne par document moissonné. Contient le payload brut de la source, vidé après normalisation, et `disappeared_at` quand la source cesse de rendre le document. Son cycle de vie relève du [moissonnage](../pipeline/02-harvest.md).
- **`failed_lookups`** : identifiants (DOI, hal-id, NNT) cherchés en vain dans une source, et DOI que doi.org ne connaît pas (source `doi_org`), avec la date de l'échec.

## Propriété des tables

| Table | Auteur | Écrit par |
|---|---|---|
| `staging` | pipeline | phases `harvest`, `fetch_missing` et `fetch_stale` (`pipeline/ingestion/common/staging.py`) |
| `failed_lookups` | pipeline | phase `fetch_missing` (`pipeline/ingestion/<source>/fetch_missing.py`) |
| `source_records` | pipeline | `pipeline/ingestion/<source>/normalize.py` |
| `source_record_locations` | pipeline | `pipeline/ingestion/<source>/normalize.py` (via `pipeline/ingestion/common/locations.py`) |
| `contributor_information` | pipeline | `pipeline/ingestion/<source>/normalize.py` (via `pipeline/ingestion/common/source_contributions.py`) |
| `source_contributions` | mixte | `pipeline/ingestion/<source>/normalize.py` ; `in_perimeter` par la phase `affiliations` ; `person_id` par le pipeline ou en admin (orphan-assign) |
| `source_contribution_addresses` | pipeline | `pipeline/ingestion/<source>/normalize.py` (via `pipeline/ingestion/common/source_contributions.py`) |
