# OpenAlex

https://openalex.org/

https://developers.openalex.org/

## API utilisées

**Works API** (https://api.openalex.org/works) — moissonnage des publications.
- Nécessite *mailto* ou clé API (création via un compte gratuit)
- Requête par institution (filtre `lineage`) + année de publication
- Pagination par cursor, 200 résultats/page, 0.2s de délai

**Sources API** (https://api.openalex.org/sources) — enrichissement par `openalex_id` de la revue. Sub-step `enrich_journals_from_openalex` de la phase [`publishers_journals`](../pipeline/05-publishers-journals.md). Met à jour `journals.apc_amount`, `apc_currency`, `is_in_doaj` (flag), `journal_type`.

> APC OpenAlex peu fiable (cf. audit du 2026-05-26 dans la fiche chantier `METIER_pipeline-publishers-journals` : médiane 21% d'écart vs DOAJ, OpenAlex sous-estime systématiquement). Cible visée à terme : retrait. État actuel conservé en attendant une source de remplacement pour les ~2 300 revues hors-DOAJ.

**Publishers API** (https://api.openalex.org/publishers) — enrichissement par `openalex_id` de l'éditeur. Sub-step `enrich_publishers_from_openalex` de la phase [`publishers_journals`](../pipeline/05-publishers-journals.md). Met à jour `publishers.country` (ISO-2 depuis `country_codes[0]`) et `publishers.ror` (depuis `ids.ror`, short form). Couverture limitée (~13% des publishers locaux ont un `openalex_id`) ; le complément `country` est posé par [Crossref Members](06-crossref.md), et le typage `publisher_type` repose sur [ROR](08-sources-supplementaires.md#ror).

## Données récupérées

- **Publications** : identifiant OpenAlex, titre, DOI, année et date de publication, type, langue, OA status, nombre de citations, indication de rétractation, résumé (reconstruit depuis l'inverted index), mots-clés, topics (hiérarchie domain/field/subfield/topic + score), biblio (volume/numéro/pages), URLs des copies de l'article
- **Auteurs** : nom tel qu'il apparaît dans la signature, drapeau corresponding, ORCID si présent. Le nom unifié de l'entité auteur OpenAlex est conservé séparément, utilisé uniquement pour vérifier que l'ORCID attribué par OA correspond bien à notre auteur (cf. Particularités).
- **Affiliations** : adresse textuelle + identifiants OpenAlex des institutions
<!--TODO: changer source_structures en JSONB pour conserver ROR et pays-->
- **Journaux/éditeurs** : titre, ISSN, eISSN, ISSN-L, type, modèle OA, identifiants OpenAlex du journal et de l'éditeur

> Côté base, l'identifiant OpenAlex est notre appellation pour le champ `id` natif (URL `https://openalex.org/W…` pour les works, `A…` auteurs, `S…` sources/journaux, `I…` institutions) une fois short-prefixé. On le stocke pour les publications, journaux, éditeurs et institutions. L'identifiant de l'entité auteur OpenAlex est dans le payload mais pas conservé.

## Exemple de payload

Document `W4395704497` (2 auteurs, article de mathématiques). `abstract_inverted_index` élidé (reconstitué en texte pendant la [phase `normalize`](../pipeline/03-normalize.md) via `reconstruct_abstract`), `locations` réduit à un placeholder (la `primary_location` est conservée intégralement), 2 topics sur 3 abrégés.

```json
{
  "abstract_inverted_index": {
    "<inverted index>": "<reconstitué via `reconstruct_abstract`>"
  },
  "authorships": [
    {
      "affiliations": [
        {
          "institution_ids": ["https://openalex.org/I4210091279"],
          "raw_affiliation_string": "UP13 - Université Paris 13 (France)"
        }
      ],
      "author": {
        "display_name": "A. Raouf Chouikha",
        "id": "https://openalex.org/A5083688291",
        "orcid": "https://orcid.org/0000-0001-9809-2932"
      },
      "author_position": "first",
      "countries": ["FR"],
      "institutions": [
        {
          "country_code": "FR",
          "display_name": "Université Sorbonne Paris Nord",
          "id": "https://openalex.org/I4210091279",
          "lineage": ["https://openalex.org/I4210091279"],
          "ror": "https://ror.org/0199hds37",
          "type": "education"
        }
      ],
      "is_corresponding": true,
      "raw_affiliation_strings": ["UP13 - Université Paris 13 (France)"],
      "raw_author_name": "Abd Raouf Chouikha",
      "raw_orcid": null
    },
    {
      "affiliations": [
        {
          "institution_ids": [
            "https://openalex.org/I4210155549",
            "https://openalex.org/I4387155825"
          ],
          "raw_affiliation_string": "LMNO - Laboratoire de Mathématiques Nicolas Oresme (…)"
        }
      ],
      "author": {
        "display_name": "Christophe Chesneau",
        "id": "https://openalex.org/A5083045521",
        "orcid": "https://orcid.org/0000-0002-1522-9292"
      },
      "author_position": "last",
      "countries": ["FR"],
      "institutions": [
        {
          "country_code": null,
          "display_name": "Laboratoire de Mathématiques Nicolas Oresme",
          "id": "https://openalex.org/I4387155825",
          "lineage": [
            "https://openalex.org/I1294671590",
            "https://openalex.org/I4210105918",
            "https://openalex.org/I4387155825",
            "https://openalex.org/I98702875"
          ],
          "ror": "https://ror.org/03jm2hc44",
          "type": "facility"
        },
        {
          "country_code": "FR",
          "display_name": "Laboratoire de Mathématiques",
          "id": "https://openalex.org/I4210155549",
          "lineage": ["… autres ancêtres OpenAlex …"],
          "ror": "https://ror.org/05sd5r855",
          "type": "facility"
        }
      ],
      "is_corresponding": false,
      "raw_affiliation_strings": ["LMNO - Laboratoire de Mathématiques Nicolas Oresme (…)"],
      "raw_author_name": "Christophe Chesneau",
      "raw_orcid": null
    }
  ],
  "biblio": { "first_page": null, "issue": "2", "last_page": null, "volume": "73" },
  "cited_by_count": 1,
  "display_name": "Contributions to trigonometric 1-parameter inequalities",
  "doi": "https://doi.org/10.7169/facm/240419-4-3",
  "id": "https://openalex.org/W4395704497",
  "is_retracted": false,
  "keywords": [
    "Trigonometry", "Inequality", "Mathematics", "Applied mathematics",
    "Calculus (dental)", "Mathematical economics", "Mathematical analysis", "Medicine"
  ],
  "language": "en",
  "locations": ["<2 entrées : primary_location + autres copies (preprint, repo, etc.)>"],
  "open_access": {
    "any_repository_has_fulltext": true,
    "is_oa": true,
    "oa_status": "green",
    "oa_url": "https://hal.science/hal-04500965v3/document"
  },
  "primary_location": {
    "id": "doi:10.7169/facm/240419-4-3",
    "is_accepted": true,
    "is_oa": false,
    "is_published": true,
    "landing_page_url": "https://doi.org/10.7169/facm/240419-4-3",
    "license": null,
    "license_id": null,
    "pdf_url": null,
    "raw_source_name": "Functiones et Approximatio Commentarii Mathematici",
    "raw_type": "journal-article",
    "source": {
      "display_name": "Functiones et Approximatio Commentarii Mathematici",
      "host_organization": null,
      "host_organization_name": null,
      "id": "https://openalex.org/S4210187257",
      "is_core": true,
      "is_in_doaj": false,
      "is_oa": false,
      "issn": ["0208-6573", "2080-9433"],
      "issn_l": "0208-6573",
      "type": "journal"
    },
    "version": "publishedVersion"
  },
  "publication_date": "2025-06-16",
  "publication_year": 2025,
  "title": "Contributions to trigonometric 1-parameter inequalities",
  "topics": [
    {
      "display_name": "Mathematical Inequalities and Applications",
      "domain": { "display_name": "Physical Sciences", "id": "https://openalex.org/domains/3" },
      "field": { "display_name": "Mathematics", "id": "https://openalex.org/fields/26" },
      "id": "https://openalex.org/T11564",
      "score": 0.9998,
      "subfield": { "display_name": "Applied Mathematics", "id": "https://openalex.org/subfields/2604" }
    },
    { "display_name": "Mathematics and Applications", "score": 0.9967, "...": "(domain/field/subfield omis)" },
    { "display_name": "Matrix Theory and Algorithms", "score": 0.9961, "...": "(domain/field/subfield omis)" }
  ],
  "type": "article"
}
```

## Particularités

- Les requêtes API paginées tronquent les authorships à **100 auteurs max** par publication ; [refetch_truncated](https://github.com/Y33sha/bibliometrie-uca/blob/master/infrastructure/sources/openalex/refetch_truncated.py) re-télécharge individuellement les works concernés (*n* auteurs == 100).
> La préservation des listes d'auteurs complètes obtenues par `refetch_truncated` repose sur un *hack* assumé : le refetch met à jour `raw_data` mais **pas** `raw_hash`, qui reste le hash du payload paginé initial. Tant que celui-ci ne change pas, l'UPSERT ne touche pas `raw_data`. Si le payload change, les `raw_data` sont écrasées (avec la troncature à 100 auteurs) puis re-refetchées au sein du même *run* pipeline.
- Le `raw_author_name` de l'authorship est plus fiable que `author.display_name` (ce dernier est un nom unifié par l'algo OA, qui peut être erroné).
- Deux ORCID coexistent dans le payload, de provenances opposées. On retient `authorship.raw_orcid` (recopié tel quel par OpenAlex de la métadonnée brute de la source amont — Crossref pour l'essentiel des articles à éditeur ; c'est l'ORCID déposé par l'auteur, fiable au même titre qu'un ORCID Crossref) et on **ignore** `author.orcid` (ORCID de l'**entité auteur unifiée** par le clustering OpenAlex, régulièrement fautif). Le `raw_orcid` retenu est stocké dans `source_authorships.person_identifiers` et utilisé directement comme signal de matching côté pipeline persons (source OpenAlex inscrite dans [`ORCID_MATCH_SOURCES`](https://github.com/Y33sha/bibliometrie-uca/blob/master/domain/persons/matching.py)), sans filtre par nom.
