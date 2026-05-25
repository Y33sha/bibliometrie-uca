# CrossRef

https://www.crossref.org/

https://www.crossref.org/learning/

Documentation API:
- https://www.crossref.org/documentation/retrieve-metadata/rest-api/
- https://api.crossref.org/swagger-ui/index.html

CrossRef n'est pas une source de périmètre : aucune requête par institution / année. La table `staging` n'est alimentée que pour les DOI absents (DOI-driven), via le mécanisme `fetch_missing_doi`. CrossRef est ensuite placée en 2ᵉ position de `SOURCE_PRIORITY` (juste après theses.fr) pour servir d'autorité sur les métadonnées éditeur déposées au moment de l'enregistrement du DOI.

## API utilisée

**Works API** (`https://api.crossref.org/works/{doi}`) — interrogation unitaire par DOI.

- Polite pool obtenu via `User-Agent: BibliometrieUCA-pipeline/1.0 (mailto:<email>)` (email lu via `polite_pool_email`)
- Limites du polite pool CrossRef : 10 req/s + 3 concurrentes. L'adapter colle exactement à ces limites (`max_concurrent=3`, `request_delay_s=0.1`)
- Les 404 sont matérialisés dans `staging` avec `not_found=TRUE` + `processed=TRUE` pour ne pas être réinterrogés à chaque run

## Données récupérées

- **Publications** : DOI, titre, type, langue, journal (titre, ISSN, eISSN, éditeur), année (extraite via [`extract_crossref_pub_year`](https://github.com/Y33sha/bibliometrie-uca/blob/master/domain/sources/crossref.py)), résumé (nettoyé du JATS XML), mots-clés (depuis `subject`), citations (`is-referenced-by-count`), biblio (volume/numéro/pages/n° d'article), identifiants externes (ISSN, ISBN), métadonnées éditoriales (license, funders, dates `issued`/`published-print`/`published-online`/`created`)
- **Auteurs** : nom complet, ORCID si présent, affiliation textuelle

## Exemple de payload

Document `10.1063/5.0056957` (2 auteurs en mécanique). Champs non consommés retirés : `URL`, `link` (PDF), `score`/`member`/`prefix`/`source` (métadonnées CrossRef internes), `relation` (chantier en pause), `reference` (souvent très volumineux), `indexed`/`deposited`/`issn-type`, `short-title`/`short-container-title`/`original-title`/`subtitle`/`journal-issue`/`update-policy`/`content-domain`, `references-count`/`reference-count`. Abstract tronqué.

```json
{
  "DOI": "10.1063/5.0056957",
  "type": "journal-article",
  "title": ["New methods of isochrone mechanics"],
  "container-title": ["Journal of Mathematical Physics"],
  "ISSN": ["0022-2488", "1089-7658"],
  "publisher": "AIP Publishing",
  "language": "en",
  "author": [
    {
      "given": "Paul",
      "family": "Ramond",
      "ORCID": "https://orcid.org/0000-0001-7123-0039",
      "affiliation": [
        { "name": "Laboratoire Univers et Théories Observatoire de Paris, PSL Research University, CNRS, Paris University, Sorbonne Paris Cité 1 , 92190 Meudon, France" },
        { "name": "Laboratoire de Mathématiques Appliquées UMA, ENSTA Paris, Institut Polytechnique de Paris 2 , 91120 Palaiseau, France" }
      ],
      "sequence": "first"
    },
    {
      "given": "Jérôme",
      "family": "Perez",
      "ORCID": "https://orcid.org/0000-0001-6730-0962",
      "affiliation": [
        { "name": "Laboratoire de Mathématiques Appliquées UMA, ENSTA Paris, Institut Polytechnique de Paris 2 , 91120 Palaiseau, France" }
      ],
      "sequence": "additional"
    }
  ],
  "abstract": "<jats:p>Isochrone potentials are spherically symmetric potentials within which a particle orbits with a radial period that is independent of its angular momentum… (tronqué, JATS XML, nettoyé via strip_jats_tags)",
  "subject": [],
  "issued":           { "date-parts": [[2021, 11, 1]] },
  "published-print":  { "date-parts": [[2021, 11, 1]] },
  "published-online": { "date-parts": [[2021, 11, 5]] },
  "created":          { "date-time": "2021-11-05T09:45:14Z", "date-parts": [[2021, 11, 5]] },
  "is-referenced-by-count": 6,
  "volume": "62",
  "issue": "11"
}
```

## Particularités

### Affiliations textuelles, pas d'address linking

Les affiliations CrossRef sont des chaînes libres et génériques (en général la tutelle, pas de laboratoire ni d'équipe). Stockées dans `source_authorships.source_data` pour traçabilité, **pas** d'insertion dans `addresses` / `source_authorship_addresses` — le matching d'adresses serait sans valeur.

### `doc_type` : `journal-article` indistinct, arbitré contre les sous-types

CrossRef rend `journal-article` pour tous les sous-types d'article (review, data_paper, conference_paper, editorial, letter, erratum, retraction). Le type est stocké tel quel dans `source_publications.doc_type`, et l'arbitrage final ([`arbitrate_doc_type_with_article_subtype`](https://github.com/Y33sha/bibliometrie-uca/blob/master/domain/publications/aggregation.py)) préfère un sous-type plus précis exposé par une source moins prioritaire (HAL, OpenAlex) — cf. `ARTICLE_SUBTYPES`. Sur tous les autres types (book-chapter, posted-content/preprint, monograph, etc.), CrossRef domine en tant que 2ᵉ priorité.

### `oa_status` non dérivé

CrossRef n'expose pas un statut OA fiable. `oa_status` reste NULL côté CrossRef — les autres sources arbitrent via `refresh_from_sources`.

### Année de publication

CrossRef expose plusieurs dates (`issued`, `published-print`, `published-online`, `created`). [`extract_crossref_pub_year`](https://github.com/Y33sha/bibliometrie-uca/blob/master/domain/sources/crossref.py) choisit la plus pertinente avec un plafond `current_year + 1` (les éditeurs déposent parfois des années farfelues).
