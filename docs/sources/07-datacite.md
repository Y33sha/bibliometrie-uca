# DataCite

https://datacite.org/

Documentation API :
- https://support.datacite.org/docs/api
- https://api.datacite.org/

DataCite est l'agence d'enregistrement des DOI des données de la recherche : jeux de données, logiciels, *preprints*, thèses, et plus largement tout ce que déposent les entrepôts institutionnels et disciplinaires (Zenodo, figshare, recherche-data-gouv, theses.fr, NAKALA…). Chaque préfixe DOI est rattaché à un *provider* (l'organisation déposante) et à un *client* (l'entrepôt précis).

Le pipeline interroge DataCite pour les DOI déjà découverts par les autres sources, via [`fetch_missing_doi`](../pipeline/02-extract.md#cross-imports) (pas de moissonnage par institution+année comme pour HAL/OpenAlex/WoS/ScanR). Le pool de DOI candidats est filtré par agence d'enregistrement : seuls les DOI rattachés à DataCite sont soumis, ce qui évite les requêtes sans réponse sur des DOI Crossref. DataCite sert d'autorité sur les métadonnées déposées au moment de l'enregistrement du DOI.

## API utilisée

**DOIs API** (`https://api.datacite.org/dois/{doi}`) — interrogation unitaire par DOI, réponse au format JSON:API (les métadonnées sont dans `data.attributes`).

- *polite pool* obtenu via `User-Agent: BibliometrieUCA-pipeline/1.0 (mailto:<email>)` (email lu via `polite_pool_email`)
- Pas de quota contractuel. L'adapter reste conservateur (`max_concurrent=3`, `request_delay_s=0.2`) pour ne pas se faire limiter
- Les 404 sont matérialisés dans `staging` avec `not_found=TRUE` + `processed=TRUE` pour ne pas être réinterrogés à chaque run

**Prefixes API** (`https://api.datacite.org/prefixes/{prefix}`) — identification du *provider* et du *client* (l'entrepôt) rattachés à un préfixe DOI. Consommée par le sub-step `resolve_publishers` de la phase [`publishers_journals`](../pipeline/05-publishers-journals.md), qui complète la table `doi_prefixes` (préfixe → entrepôt + provider) une fois sa Registration Agency résolue en amont par [`resolve_ra`](../pipeline/02-extract.md#resolve-ra).

## Données récupérées

- **Publications** : DOI, titre, type (voir Particularités), langue, année (`publicationYear`), résumé (`descriptions` de type `Abstract`), mots-clés (`subjects`), citations (`citationCount`), revue/série hôte (`container` : titre et ISSN), éditeur ou entrepôt déposant (`publisher`), licences (`rightsList`), financeurs (`fundingReferences`), DOI liés (`relatedIdentifiers`, voir Particularités)
- **Auteurs** : nom (`creators`), ORCID si présent (`nameIdentifiers`), affiliation textuelle

## Exemple de payload

*Preprint* `10.17181/b5jnp-h2c36` (déposé sur l'entrepôt du CERN, un auteur UCA). Champs non consommés retirés : `url`, `contentUrl`, `formats`, `sizes`, `identifiers`/`alternateIdentifiers`, `geoLocations`, `dates`/`created`/`registered`/`updated`, `schemaVersion`/`metadataVersion`/`source`/`state`/`xml` et les compteurs de vues/téléchargements (métadonnées DataCite internes). Résumé tronqué.

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

*TODO: à remplir*

### `doc_type` à deux niveaux

DataCite porte le type sur deux champs : `resourceTypeGeneral` (vocabulaire contrôlé : `JournalArticle`, `Preprint`, `ConferencePaper`, `Dataset`, `Software`, `Text`…) et `resourceType` (texte libre déposé par l'entrepôt). Un seul jeton est retenu et stocké dans `source_publications.doc_type` : le `resourceTypeGeneral` quand il est spécifique, sinon le `resourceType` libre (les valeurs génériques `Text` et `Other` y renvoient souvent un type plus précis comme « Journal article » ou « Working Paper »). La conversion vers le vocabulaire canonique vit dans le mapping `datacite` de [`doc_types`](https://github.com/Y33sha/bibliometrie-uca/blob/master/domain/source_publications/doc_types.py).

### Affiliations textuelles

Les affiliations des `creators` sont des chaînes de texte (parfois accompagnées d'un identifiant ROR). Elles sont routées vers `addresses` / `source_authorship_addresses` comme HAL/OpenAlex/ScanR/Crossref : la phase [`affiliations`](../pipeline/04-affiliations.md) y détecte `in_perimeter`, ce qui fait entrer les `source_authorships` DataCite dans la cascade de matching personnes.

### DOI liés et concept/version

Un entrepôt comme Zenodo attribue un DOI distinct à chaque version d'un dépôt, plus un **DOI concept** stable couvrant toutes les versions. Le champ `relatedIdentifiers` expose ces liens, et la relation `IsVersionOf` pointe d'une version vers son concept. La phase [`metadata_correction`](../pipeline/06-metadata-correction.md) s'en sert pour faire converger versions et concept vers une seule publication.

Les `relatedIdentifiers` portent aussi d'autres liens entre documents (un supplément et son article, un chapitre et son ouvrage, des citations). Le sous-ensemble « même œuvre ou œuvre étroitement liée » alimente le pool de DOI à rapatrier (`external_ids.related_dois`) ; la liste complète et typée est conservée dans `source_publications.meta` pour un usage ultérieur (relations entre publications).

### `oa_status` non dérivé

DataCite n'expose pas un statut OA fiable. `oa_status` reste NULL côté DataCite — les autres sources arbitrent via `refresh_from_sources`.
