# ScanR

## API utilisée

**Elasticsearch DataESR** (`https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search`) — moissonnage des publications du périmètre français de la recherche.

- Authentification HTTP Basic (`scanr_username` / `scanr_password` en config)
- Requête `bool` combinant un filtre `year` et un `should` sur `affiliations.id.keyword` (SIREN des structures déclarées dans le périmètre)
- Pagination par `search_after` sur `id.keyword`, taille `SCANR_PER_PAGE`, délai `SCANR_DELAY` entre requêtes
- Affiliation IDs dérivés du périmètre d'extraction (`structures.api_ids->'scanr'`)

## Données récupérées

- **Publications** : id ScanR, title (dict multilingue `default`/`en`/`fr` ou string), year, type, isOa + oaEvidence, summary (multilingue), keywords (multilingue, liste ou CSV), topics/domains, cited_by_counts_by_year, URLs (landingPage, doiUrl, pdfUrl), externalIds (doi, hal, nnt, pmid)
- **Source** (journal/éditeur) : `source.title`, `source.issn`, `source.eissn`, `source.publisher`
- **Auteurs** : `fullName`, `role`, `affiliations`, `denormalized.orcid`, `denormalized.idref`
- **Affiliations auteur** : arbre de structures (tutelle → laboratoire), filtré par `select_leaf_affiliations` pour ne garder que les feuilles

## Particularités

- L'`id` ScanR contient le NNT pour les thèses (pattern `nnt:<ppn>`) — extrait via `extract_nnt_from_scanr_id`, ce qui permet la reconciliation avec theses.fr
- Champs multilingues : la priorité est `default` > `en` > `fr` (même règle pour title / summary / keywords)
- `oa_status` dérivé via `derive_scanr_oa_status(isOa, oaEvidence)` plutôt que pris brut
- L'idref éventuel (ou l'ORCID seul) est porté par `source_authorships.person_identifiers` (JSONB)
- Adresses : les feuilles d'affiliation portent un `name` libre — passées à l'`AddressLinker` comme pour OpenAlex/WoS
