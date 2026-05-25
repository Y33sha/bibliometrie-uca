# ScanR

https://scanr.enseignementsup-recherche.gouv.fr/

https://scanr.enseignementsup-recherche.gouv.fr/docs/overview

## API utilisée

**Elasticsearch DataESR** (`https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search`) — moissonnage des publications du périmètre français de la recherche.

- Login et mot de passe nécessaires : accordés gratuitement sur demande par mail: https://scanr.enseignementsup-recherche.gouv.fr/about/contact
- Requête : année + affiliation par identifiant SIREN
- Pagination par `search_after` sur `id.keyword`, taille `SCANR_PER_PAGE`, délai `SCANR_DELAY` entre requêtes

## Données récupérées

- **Publications** : identifiant ScanR, titre (multilingue), année, type, statut OA, résumé (multilingue), mots-clés (multilingue), topics (hiérarchie OpenAlex domain/field/subfield/topic), domains (wikidata), citations (somme des comptages annuels), URLs (landing, PDF, DOI), identifiants externes (DOI, hal_id, NNT, PMID)
- **Journal/éditeur** : titre, ISSN, eISSN, éditeur
- **Auteurs** : nom complet, rôle, affiliations rattachées à chaque auteur (arbre tutelle → laboratoire, on ne conserve que les feuilles), ORCID et IdRef si présents

## Exemple de payload

Document `doi10.1001/jama.2021.7683` (2 auteurs JAMA). `summary` tronqué, `topics` réduit à 1 entrée complète + 2 abrégées (la hiérarchie OpenAlex est verbeuse), `domains` réduit à 2 entrées + ellipsis. Champs ScanR non consommés par le pipeline (`ix`, `structures`, `institutions`, `co_structures`, `predict_teds`, `bso_local_affiliations`, `autocompleted*`, etc.) retirés.

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
  "topics": [
    {
      "id": "https://openalex.org/T11207",
      "field": { "id": "https://openalex.org/fields/27", "display_name": "Medicine" },
      "score": 1,
      "domain": { "id": "https://openalex.org/domains/4", "display_name": "Health Sciences" },
      "subfield": { "id": "https://openalex.org/subfields/2734", "display_name": "Pathology and Forensic Medicine" },
      "display_name": "Alcohol Consumption and Health Effects"
    },
    { "display_name": "Liver Disease Diagnosis and Treatment", "score": 1, "...": "(hiérarchie omise)" },
    { "display_name": "Liver Disease and Transplantation", "score": 0.999, "...": "(hiérarchie omise)" }
  ],
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

### Identifiant ScanR : `<source><id natif>` collés

L'`id` ScanR concatène le préfixe de source et l'identifiant natif de la publication dans cette source, sans séparateur. Sondage sur 10 000 documents UCA :

| Préfixe | Part | Exemple |
|---|---|---|
| `doi`  | 54 % | `doi10.1001/jama.2021.7683` |
| `hal`  | 42 % | `halhal-04244961` |
| `nnt`  | 4 %  | `nnt2023clil0004` |
| `pmid` | 0.2 %| `pmid36609465` |

### Statut OA dérivé plutôt que pris brut

`isOa` n'est qu'un booléen oui/non. Pour obtenir un `oa_status` nuancé (green / gold / hybrid / bronze / closed / diamond), on dérive depuis le couple `(isOa, oaEvidence)` via `derive_scanr_oa_status` : `oaEvidence` porte l'information sur la voie d'accès OA (repository, publisher, license, etc.) qui permet de classer le statut.
