# DataCite

*À jour le 2026-10-21.*

https://datacite.org/

Documentation API :
- https://support.datacite.org/docs/api
- https://api.datacite.org/

DataCite est l'agence d'enregistrement des DOI des données de la recherche : jeux de données, logiciels, *preprints*, thèses, et plus largement tout ce que déposent les entrepôts institutionnels et disciplinaires (Zenodo, figshare, recherche-data-gouv, theses.fr, NAKALA…). Chaque préfixe DOI est rattaché à un *provider* (l'organisation déposante) et à un *client* (l'entrepôt précis).

Le pipeline interroge DataCite de trois façons :
- [moissonnage](../pipeline/02-harvest.md#moissonnage-par-affiliation-harvest), en mode `full` : par année, les DOI dont une affiliation de créateur contient l'un des mots-clés saisis pour les structures du périmètre (champ DataCite des identifiants de structure) ;
- [`fetch_missing_doi`](../pipeline/02-harvest.md#documents-absents-dune-source-fetch_missing) : les DOI rattachés à DataCite et trouvés seulement dans les autres sources ;
- [moissonnage par personne](../pipeline/02-harvest.md#moissonnage-par-personne-harvest_by_person) : les DOI dont un créateur a l'ORCID d'une personne RH (`creators.nameIdentifiers.nameIdentifier`).

Les DOI d'un entrepôt sans affiliation renseignée (NAKALA, notamment) entrent par les deux dernières voies.

## API utilisée

**DOIs API** — réponse au format JSON:API (les métadonnées sont dans `data.attributes`) :
- `https://api.datacite.org/dois?query=…` : recherche paginée par curseur (moissonnages, `fetch_missing_doi`) ;
- `https://api.datacite.org/dois/{doi}` : interrogation unitaire (`fetch_stale`).

- Adresse électronique de contact dans le `User-Agent` (`POLITE_POOL_EMAIL`)
- Pas de quota contractuel. Le pipeline s'en tient à 3 req/s (`MAX_PER_SECOND`, `pipeline/ingestion/api_params.py`) et à 3 requêtes simultanées (`max_concurrent=3`)

**Prefixes API** (`https://api.datacite.org/prefixes/{prefix}`) — identifie l'organisation déposante (*provider*) et l'entrepôt (*client*) d'un préfixe DOI, pour la phase [`publishing`](../pipeline/05-publishing.md) (`resolve_datacite_publishers`), une fois connue l'agence d'enregistrement du préfixe ([`resolve_ra`](../pipeline/05-publishing.md#agences-denregistrement-doi-resolve_ra)).

## Données récupérées

- **Publications** : DOI, titre, type (voir Particularités), langue, année (`publicationYear`), résumé (`descriptions` de type `Abstract`), mots-clés (`subjects`), citations (`citationCount`), revue/série hôte (`container` : titre et ISSN, voir Particularités), éditeur ou entrepôt déposant (`publisher`), licences (`rightsList`), financeurs (`fundingReferences`), DOI liés (`relatedIdentifiers`, voir Particularités), ISBN (`relatedIdentifiers` de type ISBN, ou identifiant du `container` quand il en est un)
- **Auteurs** : nom (`creators`), ORCID si présent (`nameIdentifiers`), affiliation textuelle

## Exemple de payload

*Preprint* `10.17181/b5jnp-h2c36` (déposé sur l'entrepôt du CERN). Réduit aux champs que le pipeline lit ; résumé tronqué.

```json
{
  "doi": "10.17181/b5jnp-h2c36",
  "types": {
    "resourceTypeGeneral": "Preprint",
    "resourceType": ""
  },
  "titles": [{ "title": "Measuring $R_c$ with exclusive $c$-hadron decays at FCC-ee…" }],
  "publisher": "CERN",
  "publicationYear": 2024,
  "language": null,
  "creators": [
    {
      "name": "Monteil, Stéphane",
      "givenName": "Stéphane",
      "familyName": "Monteil",
      "nameType": "Personal",
      "affiliation": ["Université Clermont-Auvergne, CNRS, LPCA, 63000 Clermont-Ferrand, France"],
      "nameIdentifiers": [
        { "nameIdentifier": "0000-0001-5015-3353", "nameIdentifierScheme": "ORCID" }
      ]
    },
    {
      "name": "Roehrig, Lars",
      "givenName": "Lars",
      "familyName": "Roehrig",
      "nameType": "Personal",
      "affiliation": ["Department of Physics, TU Dortmund University, Dortmund, Germany"],
      "nameIdentifiers": [
        { "nameIdentifier": "0000-0003-1040-2938", "nameIdentifierScheme": "ORCID" }
      ]
    }
  ],
  "subjects": [],
  "descriptions": [
    { "description": "This analysis note assesses the precision reachable at FCC-ee… (tronqué)", "descriptionType": "Abstract" }
  ],
  "relatedIdentifiers": [
    { "relationType": "IsVersionOf", "relatedIdentifier": "10.17181/5gd08-dmd71", "relatedIdentifierType": "DOI" }
  ],
  "rightsList": [
    { "rights": "Creative Commons Attribution 4.0 International", "rightsIdentifier": "cc-by-4.0" }
  ],
  "container": {},
  "citationCount": 0
}
```

## Particularités

### Relations entre publications

DataCite déclare ses relations dans `relatedIdentifiers[].relationType`, sous des valeurs comme `IsSupplementTo` ou `IsPartOf`. La phase [relations](../pipeline/11-enrichissements.md#relations-entre-publications-relations) les traduit vers son vocabulaire, et écarte celles qui désignent la même œuvre, une citation ou une évaluation.

### Type de document

DataCite déclare le type dans deux champs : `resourceTypeGeneral`, au vocabulaire contrôlé (`JournalArticle`, `Preprint`, `Dataset`, `Text`…), et `resourceType`, en texte libre. Le type retenu est `resourceTypeGeneral` quand il est spécifique, sinon `resourceType` : les valeurs génériques `Text` et `Other` cachent souvent un type précis (« Journal article », « Working Paper »). La conversion vers le vocabulaire du référentiel se fait dans le mapping `datacite` de [`doc_types`](https://github.com/Y33sha/bibliometrie-uca/blob/master/domain/source_records/doc_types.py).

### Revue hôte

DataCite déduit `container` des éléments liés ou de la description `SeriesInformation`, en texte libre. Le conteneur est retenu comme revue, collection ou recueil d'actes pour un type publié dans une revue ou un livre (article, communication, chapitre…), et quand il ne vient pas d'une citation en texte libre, que DataCite découpe mal (`container_names_a_journal`). Le titre d'un conteneur écarté reste dans `container_title`.

### Affiliations textuelles

Les affiliations des créateurs sont du texte, parfois avec un ROR. Elles deviennent des adresses, que la phase [`affiliations`](../pipeline/04-affiliations.md) examine.

### DOI liés et concept/version

Un entrepôt comme Zenodo attribue un DOI distinct à chaque version d'un dépôt, plus un **DOI concept** stable couvrant toutes les versions. Le champ `relatedIdentifiers` expose ces liens, et la relation `IsVersionOf` pointe d'une version vers son concept. La phase [`metadata_correction`](../pipeline/06-metadata-correction.md) s'en sert pour faire converger versions et concept vers une seule publication.

Les DOI apparentés (versions, formes, parties, suppléments) deviennent des identifiants liés, que la phase `fetch_missing` cherche.

### Statut open access

DataCite ne donne pas de statut open access : celui de la publication vient des autres sources.
