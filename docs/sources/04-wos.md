# Web of Science

https://developer.clarivate.com/apis/wos

## API utilisée

**Expanded API** (`https://api.clarivate.com/api/wos`) — moissonnage des publications.
- Clé API nécessaire, obtenue sur demande après enregistrement de l'application (compter plusieurs jours de délai).
- Requête par champ OG (Organization) + année de publication
- Pagination par offset (`firstRecord`), 10 résultats/page, 1s de délai
- Retry avec backoff exponentiel (API instable, rate limiting silencieux)
- Quota annuel limité (vérification au démarrage) : le quota dépend du contrat ; pour l'UCA, la limite est de 50000 *full records* par an.

## Données récupérées

- **Publications** : UID (identifiant interne WoS), titre, DOI, année, type de document, langue, OA status, nombre de citations, résumé, mots-clés, topics (sujets + headings WoS), biblio (volume/numéro/pages), journal (titre, ISSN, eISSN, éditeur)
- **Auteurs** : nom complet, position, rôle, drapeau corresponding, ORCID si présent, ResearcherID Clarivate (identifiant stable de l'auteur côté WoS). L'identifiant d'entité auteur algorithmique de WoS (`daisng_id`) est ignoré — référentiel interne Clarivate non fiable.
- **Affiliations** : adresses textuelles + noms d'organisations rattachés à chaque auteur (pas d'identifiant stable d'institution côté WoS — le nom fait office d'identifiant).

## Exemple de payload

Document `WOS:001759398100001` (2 auteurs, article de mathématiques discrètes). Réduit aux structures que le code consomme — sont retirés/élidés : `static_data.item`, `dates`, `contributors`, `fund_ack`, `refs`, les ~22 entrées de `tc_list.silo_tc` (un compteur de citations par base WoS : `RSCI`, `PQDT`, `CCC`, etc.) sauf celle de `WOK` (l'agrégateur toutes bases que le code lit comme `cited_by_count`), et les multiples variantes de `titles` (`abbrev_*`) et de `pub_info` (`early_access`, `sortdate`, etc.). Abstract tronqué.

```json
{
  "UID": "WOS:001759398100001",
  "static_data": {
    "summary": {
      "names": {
        "name": [
          {
            "role": "author",
            "seq_no": 1,
            "addr_no": 1,
            "full_name": "Dailly, Antoine",
            "display_name": "Dailly, Antoine",
            "r_id": "CLX-1867-2022",
            "data-item-ids": {
              "data-item-id": {
                "type": "person",
                "content": "CLX-1867-2022",
                "id-type": "PreferredRID"
              }
            },
            "daisng_id": 6812274
          },
          {
            "role": "author",
            "seq_no": 2,
            "addr_no": 2,
            "reprint": "Y",
            "full_name": "Lehtila, Tuomo",
            "display_name": "Lehtila, Tuomo",
            "r_id": "AAD-7392-2020",
            "data-item-ids": {
              "data-item-id": [
                { "type": "person", "content": "AAD-7392-2020", "id-type": "PreferredRID" },
                { "type": "person", "content": "0000-0003-2940-8088", "id-type": "PreferredORCID" },
                { "type": "person", "content": "0000-0003-2940-8088", "id-type": "OtherORCID" }
              ]
            },
            "daisng_id": 1940961
          }
        ]
      },
      "titles": {
        "title": [
          { "type": "source", "content": "DISCRETE APPLIED MATHEMATICS" },
          { "type": "item", "content": "Reconstructing graphs with subgraph compositions" }
        ]
      },
      "doctypes": { "doctype": "Article" },
      "pub_info": {
        "vol": 390,
        "issue": null,
        "page": { "begin": 198, "end": 219 },
        "pubyear": 2026,
        "journal_oas_gold": "N"
      },
      "publishers": {
        "publisher": {
          "names": { "name": { "unified_name": "Elsevier", "full_name": "ELSEVIER" } }
        }
      }
    },
    "fullrecord_metadata": {
      "addresses": {
        "address_name": [
          {
            "address_spec": {
              "addr_no": 1,
              "full_address": "Univ Clermont Auvergne, INRAE, UR TSCF, F-63000 Clermont Ferrand, France",
              "organizations": {
                "count": 3,
                "organization": [
                  { "pref": null, "content": "Univ Clermont Auvergne" },
                  { "pref": "Y", "ror_id": "https://ror.org/003vg9w96", "content": "INRAE" },
                  { "pref": "Y", "ror_id": "https://ror.org/01a8ajp46", "content": "Universite Clermont Auvergne (UCA)" }
                ]
              }
            }
          },
          {
            "address_spec": {
              "addr_no": 2,
              "full_address": "Univ Turku, Dept Math & Stat, FI-20014 Turku, Finland",
              "organizations": {
                "count": 4,
                "organization": [
                  { "pref": null, "content": "Univ Turku" },
                  { "pref": "Y", "ror_id": "https://ror.org/05vghhr25", "content": "University of Turku" },
                  { "pref": "N", "content": "University of Turku Faculty of Social Sciences" },
                  { "pref": "N", "content": "Turku University Department of Mathematics and Statistics" }
                ]
              }
            }
          }
        ]
      },
      "languages": { "language": { "type": "primary", "content": "English" } },
      "abstracts": {
        "abstract": { "abstract_text": { "p": "<texte de l'abstract — tronqué>" } }
      },
      "keywords": {
        "keyword": ["Graph reconstruction", "Mass spectrometry", "Polymer-based data storage", "Trees"]
      },
      "category_info": {
        "headings": { "heading": "Science & Technology" },
        "subjects": {
          "subject": [
            { "ascatype": "traditional", "content": "Mathematics, Applied" },
            { "ascatype": "extended", "content": "Mathematics" }
          ]
        }
      }
    }
  },
  "dynamic_data": {
    "cluster_related": {
      "identifiers": {
        "identifier": [
          { "type": "issn", "value": "0166-218X" },
          { "type": "eissn", "value": "1872-6771" },
          { "type": "doi", "value": "10.1016/j.dam.2026.04.023" }
        ]
      }
    },
    "citation_related": {
      "tc_list": {
        "silo_tc": [
          { "coll_id": "WOK", "local_count": 0 },
          "<… ~20 autres bases (RSCI, PQDT, CCC, …) — compteurs par silo, tous à 0 ici>"
        ]
      }
    }
  }
}
```
