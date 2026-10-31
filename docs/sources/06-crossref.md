# Crossref

*À jour le 2026-10-21.*

https://www.crossref.org/

Documentation API:
- https://www.crossref.org/documentation/retrieve-metadata/rest-api/
- https://api.crossref.org/swagger-ui/index.html

Le pipeline interroge Crossref par DOI, pour les documents découverts par les autres sources ([`fetch_missing_doi`](../pipeline/02-harvest.md#documents-absents-dune-source-fetch_missing)), et par l'ORCID des personnes RH ([moissonnage par personne](../pipeline/02-harvest.md#moissonnage-par-personne-harvest_by_person)). Crossref fait autorité, après theses.fr, sur les métadonnées des DOI Crossref.

## API utilisée

**Works API** :
- `https://api.crossref.org/works/{doi}` : interrogation unitaire par DOI ;
- `https://api.crossref.org/works?filter=orcid:…` : œuvres d'un lot d'ORCID, paginées par curseur (moissonnage par personne).

- Adresse électronique de contact dans le `User-Agent` (`POLITE_POOL_EMAIL`)
- Limites du polite pool Crossref : 10 req/s et 3 requêtes simultanées. Le pipeline s'en tient à 5 req/s (`MAX_PER_SECOND`, `pipeline/ingestion/api_params.py`) et à 3 requêtes simultanées (`max_concurrent=3`)

**Prefixes API** (`https://api.crossref.org/prefixes/{prefix}`) — identifie l'éditeur (membre Crossref) d'un préfixe DOI, pour la phase [`publishing`](../pipeline/05-publishing.md) (`resolve_crossref_publishers`), une fois connue l'agence d'enregistrement du préfixe ([`resolve_ra`](../pipeline/05-publishing.md#agences-denregistrement-doi-resolve_ra)).

## Données récupérées

- **Publications** : DOI, titre, type, langue, revue (titre, ISSN, eISSN, éditeur), date de publication, résumé (nettoyé du JATS XML), mots-clés (depuis `subject`), citations (`is-referenced-by-count`), biblio (volume/numéro/pages/n° d'article), identifiants externes (ISBN et eISBN, `isbn-type` donnant le support), champs propres à Crossref gardés dans `source_extras` (licence, financeurs, relations, congrès)
- **Date de publication** : la première date d'année plausible (de 1500 à l'année suivante) parmi `published`, `issued`, `published-online`, `published-print` et `approved`. `published` est la plus ancienne des dates en ligne et papier. `approved` est la date de soutenance d'une thèse.
- **Auteurs** : nom complet, ORCID si présent, affiliation textuelle
- **Localisation** (`source_record_locations`) : la page vers laquelle résout le DOI (`resource.primary.URL`), avec la licence de la version éditeur. Les URL de `link` mènent à des points d'accès pour la fouille de texte : elles sont ignorées.

## Exemple de payload

Document `10.1063/5.0056957` (2 auteurs en mécanique). Réduit aux champs lus par le pipeline ; résumé tronqué.

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

### Relations entre publications

Crossref déclare ses relations dans `source_extras.relation`, sous des clés comme `is-preprint-of` ou `erratum`. La phase [relations](../pipeline/11-enrichissements.md#relations-entre-publications-relations) les traduit vers son vocabulaire, et écarte celles qui désignent la même œuvre, une citation ou une évaluation.

### Affiliations mal renseignées

Crossref donne une affiliation pour 29 % des auteurs (sondage sur 1 000 payloads), souvent la seule tutelle. Ces affiliations deviennent des adresses, examinées par la phase `affiliations`. Leur pauvreté exclut le moissonnage par affiliation.

### Type de document

Crossref donne `journal-article` pour tous les sous-types d'article (synthèse, data paper, éditorial…). L'agrégation retient le sous-type donné par une autre source ([`arbitrate_doc_type_with_article_subtype`](https://github.com/Y33sha/bibliometrie-uca/blob/master/domain/publications/aggregation.py)).
