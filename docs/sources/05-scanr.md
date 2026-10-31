# ScanR

*À jour le 2026-10-28.*

https://scanr.enseignementsup-recherche.gouv.fr/

https://scanr.enseignementsup-recherche.gouv.fr/docs/overview

## API utilisée

**Elasticsearch DataESR** (`https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search`) — moissonnage des publications du périmètre français de la recherche.

- Identifiant et mot de passe nécessaires, accordés gratuitement sur demande : https://scanr.enseignementsup-recherche.gouv.fr/about/contact
- Requête : année + affiliation par identifiant SIREN
- [Moissonnage par personne](../pipeline/02-harvest.md#moissonnage-par-personne-harvest_by_person) : clause réunissant l'IdRef (`authors.person`, sous la forme `idref<IdRef>`) et l'ORCID (`authors.denormalized.orcid`) d'un lot de personnes RH
- Pagination par `search_after` sur `id.keyword`, 1 000 résultats par page, à 5 req/s (`MAX_PER_SECOND`, `pipeline/ingestion/api_params.py`)

## Données récupérées

- **Publications** : identifiant ScanR, titre (multilingue), année, type, résumé (multilingue), mots-clés (multilingue), concepts `domains` (concepts wikidata et mots-clés, ajoutés aux mots-clés ; vedettes sudoc, retenues comme sujets), citations (somme des comptages annuels), URLs (landing, PDF, DOI), identifiants externes (DOI, hal_id, NNT, PMID), licence (`oaEvidence.license`)
- **Localisations** (`source_record_locations`) : la copie ouverte (`oaEvidence`), avec son PDF, sa version et son accès, puis la page du document (`landingPage`) quand elle désigne une autre adresse.
- **Revue et éditeur** : titre, ISSN, eISSN, éditeur. Pour une thèse ou une habilitation, le titre de la source est l'université de soutenance : il ne donne ni publication en série ni titre de conteneur.
- **Auteurs** : nom complet, rôle, affiliations rattachées à chaque auteur (arbre tutelle → laboratoire, seules les feuilles sont retenues), ORCID et IdRef si présents. Une affiliation avec `structId` est une fiche du référentiel HAL : elle donne une structure HAL à la contribution source. Une affiliation sans `structId` est un texte d'affiliation : elle donne une adresse.

## Exemple de payload

Document `doi10.1001/jama.2021.7683` (2 auteurs JAMA). Réduit aux champs lus par le pipeline ; `summary` tronqué, `domains` réduit à 2 entrées.

```json
{
  "id": "doi10.1001/jama.2021.7683",
  "isOa": false,
  "type": "journal-article",
  "year": 2021,
  "title": {
    "en": "Diagnosis and Treatment of Alcohol-Associated Liver Disease",
    "default": "Diagnosis and Treatment of Alcohol-Associated Liver Disease"
  },
  "summary": {
    "en": "Alcohol-associated liver disease results in cirrhosis in approximately 10% to 20% of patients. In 20… (tronqué)",
    "default": "Alcohol-associated liver disease results in cirrhosis in approximately 10% to 20% of patients. In 20… (tronqué)"
  },
  "doiUrl": "http://doi.org/10.1001/jama.2021.7683",
  "landingPage": "http://doi.org/10.1001/jama.2021.7683",
  "source": {
    "isOa": false,
    "title": "JAMA",
    "isInDoaj": false,
    "publisher": "American Medical Association",
    "journalIssns": ["0098-7484", "1538-3598"]
  },
  "domains": [
    {
      "code": "Q147778", "type": "wikidata", "count": 18,
      "label": { "default": "cirrhosis" },
      "naturalKey": "cirrhosis"
    },
    {
      "code": "Q929737", "type": "wikidata", "count": 17,
      "label": { "default": "Liver Disease" },
      "naturalKey": "liverdisease"
    },
    "<… 23 autres domains wikidata>"
  ],
  "authors": [
    {
      "role": "author",
      "fullName": "Ashwani K. Singal",
      "affiliations": [
        {
          "ids": [{ "id": "grid.267169.d", "type": "grid" }],
          "name": "University of South Dakota Sanford School of Medicine, Sioux Falls",
          "detected_countries": ["us"]
        },
        {
          "ids": [],
          "name": "Avera Transplant Institute, Sioux Falls, South Dakota",
          "detected_countries": []
        }
      ]
    },
    {
      "role": "author",
      "person": "idref060983086",
      "id_name": "idref060983086###Philippe Mathurin",
      "fullName": "Philippe Mathurin",
      "affiliations": [
        {
          "ids": [],
          "name": "Division of Hepatology, Hospital Huriez, Lille, France",
          "detected_countries": ["fr"]
        }
      ],
      "denormalized": { "id": "idref060983086", "idref": "060983086", "orcid": "0000-0003-3447-2025" }
    }
  ],
  "externalIds": [
    { "id": "10.1001/jama.2021.7683", "type": "doi" },
    { "id": "34255003", "type": "pmid" },
    { "id": "hal-04481877", "type": "hal" }
  ],
  "cited_by_counts_by_year": {
    "2021": 9, "2022": 57, "2023": 77, "2024": 83, "2025": 95
  },
  "publicationDate": "2021-07-13T00:00:00"
}
```

## Particularités

### Identifiants ScanR

L'`id` ScanR concatène le préfixe de source et l'identifiant natif de la publication dans cette source, sans séparateur. Sondage sur 10 000 documents :

| Préfixe | Part | Exemple |
|---|---|---|
| `doi`  | 54 % | `doi10.1001/jama.2021.7683` |
| `hal`  | 42 % | `halhal-04244961` |
| `nnt`  | 4 %  | `nnt2023clil0004` |
| `pmid` | 0.2 %| `pmid36609465` |
