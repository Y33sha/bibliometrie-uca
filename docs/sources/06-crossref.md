# CrossRef

https://www.crossref.org/

Documentation API:
- https://www.crossref.org/documentation/retrieve-metadata/rest-api/
- https://api.crossref.org/swagger-ui/index.html

Le pipeline n'interroge CrossRef que pour les DOI déjà découverts par les autres sources, via [`fetch_missing_doi`](../pipeline/02-extract.md#cross-imports) (pas de moissonnage par institution+année comme pour HAL/OpenAlex/WoS/ScanR). CrossRef sert d'autorité sur les métadonnées éditeur déposées au moment de l'enregistrement du DOI.

## API utilisée

**Works API** (`https://api.crossref.org/works/{doi}`) — interrogation unitaire par DOI.

- Polite pool obtenu via `User-Agent: BibliometrieUCA-pipeline/1.0 (mailto:<email>)` (email lu via `polite_pool_email`)
- Limites du polite pool CrossRef : 10 req/s + 3 concurrentes. L'adapter colle exactement à ces limites (`max_concurrent=3`, `request_delay_s=0.1`)
- Les 404 sont matérialisés dans `staging` avec `not_found=TRUE` + `processed=TRUE` pour ne pas être réinterrogés à chaque run

**Prefixes API** (`https://api.crossref.org/prefixes/{prefix}`) — identification du Crossref Member (= éditeur déposant) associé à un préfixe DOI. Consommée par le sub-step `resolve_publishers` de la phase [`publishers_journals`](../pipeline/05-publishers-journals.md), qui complète la table `doi_prefixes` (préfixe → `crossref_member_id` + nom du déposant) une fois sa Registration Agency résolue en amont par [`resolve_ra`](../pipeline/02-extract.md#resolve-ra).

**Members API** (`https://api.crossref.org/members/{id}`) — récupération du record complet d'un Crossref Member (notamment son champ `location` au format `"City, State, Country"`). Consommée par le sub-step `enrich_publishers_from_crossref_members` (fallback `publishers.country` quand OpenAlex Publishers n'a pas matché). Couverture mesurée à l'audit : ~95 % des publishers candidats gagnent un pays via ce fallback.

## Données récupérées

- **Publications** : DOI, titre, type, langue, journal (titre, ISSN, eISSN, éditeur), année (extraite via [`extract_crossref_pub_year`](https://github.com/Y33sha/bibliometrie-uca/blob/master/domain/sources/crossref.py)), résumé (nettoyé du JATS XML), mots-clés (depuis `subject`), citations (`is-referenced-by-count`), biblio (volume/numéro/pages/n° d'article), identifiants externes (ISSN, ISBN), métadonnées éditoriales (license, funders, dates `issued`/`published-print`/`published-online`/`created`)
- **Auteurs** : nom complet, ORCID si présent, affiliation textuelle

## Exemple de payload

Document `10.1063/5.0056957` (2 auteurs en mécanique). Champs non consommés retirés : `URL`, `link` (PDF), `score`/`member`/`prefix`/`source` (métadonnées CrossRef internes), `relation` (hors scope — chantier relations entre publications), `reference` (souvent très volumineux), `indexed`/`deposited`/`issn-type`, `short-title`/`short-container-title`/`original-title`/`subtitle`/`journal-issue`/`update-policy`/`content-domain`, `references-count`/`reference-count`. Abstract tronqué.

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

### Affiliations partielles

~29 % seulement des auteurs CrossRef portent une affiliation (sondage sur 1 000 payloads, à confirmer sur base complète), et elles sont génériques (tutelle, sans labo). Elles sont néanmoins routées vers `addresses` / `source_authorship_addresses` via `AddressLinker`, comme HAL/OpenAlex/ScanR/theses.fr : la phase `affiliations` y détecte `in_perimeter`, ce qui fait entrer les `source_authorships` CrossRef dans la cascade de matching personnes (et CrossRef figure désormais dans `build_authorships.all_sources`). Couverture partielle, mais strictement mieux que rien. Cette même pauvreté condamne en revanche la *discovery* par affiliation — trouver de nouvelles publis via la query affiliation, un usage distinct (cf. Statut).

### `doc_type` : `journal-article` indistinct, arbitré contre les sous-types

CrossRef rend `journal-article` pour tous les sous-types d'article (review, data_paper, conference_paper, editorial, letter, erratum, retraction). Le type est stocké tel quel dans `source_publications.doc_type`, et l'arbitrage final ([`arbitrate_doc_type_with_article_subtype`](https://github.com/Y33sha/bibliometrie-uca/blob/master/domain/publications/aggregation.py)) préfère un sous-type plus précis exposé par une source moins prioritaire (HAL, OpenAlex) — cf. `ARTICLE_SUBTYPES`. Sur tous les autres types (book-chapter, posted-content/preprint, monograph, etc.), CrossRef domine en tant que 2ᵉ priorité.

### `oa_status` non dérivé

CrossRef n'expose pas un statut OA fiable. `oa_status` reste NULL côté CrossRef — les autres sources arbitrent via `refresh_from_sources`.

### Année de publication

CrossRef expose plusieurs dates (`issued`, `published-print`, `published-online`, `created`). [`extract_crossref_pub_year`](https://github.com/Y33sha/bibliometrie-uca/blob/master/domain/sources/crossref.py) choisit la plus pertinente avec un plafond `current_year + 1` (les éditeurs déposent parfois des années farfelues).

## Statut

CrossRef est intégré en **DOI-driven uniquement** ; le périmètre est arrêté là (sujet clos le 2026-05-30). Voir la fiche chantier [`METIER_crossref`](https://github.com/Y33sha/bibliometrie-uca/blob/master/docs/chantiers/METIER_crossref.md).

**En place** :
- Ingestion DOI-driven (`fetch_missing_doi` + `normalize_crossref`)
- Arbitrage du `doc_type` contre les sous-types HAL/OpenAlex (`arbitrate_doc_type_with_article_subtype`)

**Écarté** (décisions 2026-05-30) :
- **Discovery par affiliation** : évaluée sur dump prod via `query.affiliation=Clermont Auvergne` (2 tokens, sans le bruit « université » qui faussait le spike initial). Recall faible (~26 % des publis DOI-Crossref UCA déjà connues — CrossRef n'indexe l'affiliation que pour une minorité de ses dépôts) **et** précision faible (~14-34 % des nouveaux candidats réellement UCA, le reste = bruit de token : « Clermont » aux USA, « Auvergne » comme région ⇒ Lyon/Grenoble). Pas d'extracteur affiliation-driven.
- **Promotion d'ORCID `pending → confirmed`** : abandonnée (action admin manuelle, sans impact pipeline).
- **Discovery par ORCID confirmé** : sortie du chantier (non spécifique à CrossRef, éventuel chantier multi-source).
- **Relations entre publications** (preprint-of, version-of, etc.) : hors scope → chantier `METIER_relations-publications`.
