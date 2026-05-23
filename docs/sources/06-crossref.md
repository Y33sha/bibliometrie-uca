# CrossRef

CrossRef n'est pas une source de périmètre : aucune requête par institution / année. La table `staging` n'est alimentée que pour les DOI absents (DOI-driven), via le mécanisme `fetch_missing_doi`. CrossRef est consultée en aval pour fiabiliser les métadonnées éditeur (journal, ISSN, license) et récupérer les ORCID article-level qui manquent ailleurs.

## API utilisée

**Works API** (`https://api.crossref.org/works/{doi}`) — interrogation unitaire par DOI.

- Polite pool obtenu via `User-Agent: BibliometrieUCA-pipeline/1.0 (mailto:<email>)` (email lu via `get_crossref_email`, fallback `get_polite_pool_email`)
- Limites observées par CrossRef pour le polite pool : 10 req/s + 3 concurrentes. L'adapter colle exactement à ces limites (`max_concurrent=3`, `request_delay_s=0.1`)
- Les 404 sont matérialisés dans `staging` avec `not_found=TRUE` + `processed=TRUE` pour ne pas être réinterrogés à chaque run

## Données récupérées

- **Publications** : DOI, title (liste, on prend le premier non-vide), container-title, ISSN/eISSN, publisher, type, abstract (en JATS XML inline — nettoyé via `strip_jats_tags`), subject (utilisé comme keywords), license, relation
- **Auteurs** : `given` + `family`, `ORCID` (URL), `affiliation` (texte libre, généralement tutelle)

## Particularités

- Pas d'identité d'auteur stable côté API — l'ORCID éventuel va dans `source_authorships.person_identifiers` (JSONB)
- Affiliations CrossRef purement textuelles et génériques (tutelles, pas de structures détaillées) → stockées dans `source_authorships.source_data` pour traçabilité, **pas** d'insertion dans `addresses` / `source_authorship_addresses`
- `doc_type` stocké comme `NULL` à la normalisation ; le mapping taxonomie CrossRef → enum canonique est appliqué plus tard via `_SOURCE_MAPS`
- `oa_status` non dérivé de CrossRef (pas fiable) ; laissé à NULL — les autres sources arbitrent via `refresh_from_sources`
- Année de publication : extraite via `extract_crossref_pub_year` qui choisit entre `issued`, `published-print`, `published-online`, `created` avec un plafond `current_year + 1`
