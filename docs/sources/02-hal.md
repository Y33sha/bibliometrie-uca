# HAL

*À jour le 2026-10-28.*

https://hal.science/

Documentation HAL : https://doc.hal.science/

Documentation API : https://api.archives-ouvertes.fr/docs

## API utilisée

**Search API** (https://api.archives-ouvertes.fr/search) — moissonnage des publications.
- Sans identifiants d'accès.
- Requête par [collection HAL](../glossaire.md#collection-hal) + année de publication
- [Moissonnage par personne](../pipeline/02-harvest.md#moissonnage-par-personne-harvest_by_person) : filtre réunissant les ORCID (`authORCIDIdExt_s`), idHAL (`authIdHal_s`) et IdRef (`authIdRefIdExt_s`) d'un lot de personnes RH
- Champs Solr récupérés : voir [pipeline/ingestion/hal/fields.py](https://github.com/Y33sha/bibliometrie-uca/blob/master/pipeline/ingestion/hal/fields.py) (`HAL_FIELDS`)
- Pagination par `cursorMark`, 100 résultats/page, à 5 req/s (`MAX_PER_SECOND`, `pipeline/ingestion/api_params.py`)

## Données récupérées

- **Publications** : titre, DOI, année, type de document, langue, revue (titre, ISSN, eISSN, éditeur), ISBN (lu dans le TEI), OA, licence du fichier déposé (`licence_s`), URI, résumé, mots-clés, domaines HAL, biblio (volume/numéro/pages)
- **Localisation** (`source_record_locations`) : la page du dépôt (`uri_s`) et le fichier déposé (`fileMain_s`), avec sa licence. La copie est ouverte quand un fichier est déposé ; un dépôt sans fichier, qui renvoie seulement vers un autre emplacement, est fermé. Un fichier sous embargo est fermé jusqu'à la fin de l'embargo, date portée par la copie.
- **Auteurs** : nom complet, compte HAL, idHAL, ORCID et IdRef si présents
- **Affiliations** : structures HAL directes de chaque auteur et leur ROR, lus dans le TEI. HAL donne des structures de son référentiel, sans texte d'affiliation : les contributions sources HAL sont sans adresse.

## Exemple de payload

Document `hal-04836977` (3 auteurs, podcast Métaclassique). `abstract_s`, `subTitle_s` et `label_s` tronqués, `label_xml` élidé (extrait formaté plus bas).

```json
{
  "abstract_s": ["En 1890, dans son Dictionnaire théorique… (tronqué)"],
  "authFullNameFormIDPersonIDIDHal_fs": [
    "Céline Frigau Manning_FacetSep_2688470-752404_FacetSep_celine-frigau-manning",
    "Hélène Tysman_FacetSep_3340220-0_FacetSep_",
    "David Christoffel_FacetSep_1340141-1275740_FacetSep_dcdb"
  ],
  "authQuality_s": ["aut", "aut", "aut"],
  "collCode_s": [
    "SHS", "UNIV-ST-ETIENNE", "ENS-LYON", "UNIV-LYON3", "PRES_CLERMONT",
    "CNRS", "UNIV-BPCLERMONT", "UNIV-LYON2", "AO-MUSICOLOGIE", "CERHAC",
    "HIPHISCITECH", "CERILAC", "LYON2", "IHRIM", "UDL", "UNIV-LYON",
    "UNIV-PARIS", "UNIVERSITE-PARIS", "UP-SOCIETES-HUMANITES",
    "HAL-LYON-2-NOUVELLE-VERSION"
  ],
  "docType_s": "OTHER",
  "fr_domainAllCodeLabel_fs": [
    "shs.hisphilso_FacetSep_Sciences de l'Homme et Société/Histoire, Philosophie et Sociologie des sciences",
    "shs.musiq_FacetSep_Sciences de l'Homme et Société/Musique, musicologie et arts de la scène"
  ],
  "halId_s": "hal-04836977",
  "keyword_s": ["Hypnose", "Hypnose musicale", "Suggestion", "Auditeurs", "Musiciens", "Piano"],
  "label_s": "Céline Frigau Manning, Hélène Tysman, David Christoffel. Podcast… (tronqué)",
  "label_xml": "<TEI…> … voir extrait formaté ci-dessous … </TEI>",
  "language_s": ["en"],
  "openAccess_bool": false,
  "producedDateY_i": 2020,
  "publicationDate_s": "2020-03-18",
  "subTitle_s": ["URL : https://metaclassique.com/… (tronqué)"],
  "title_s": [
    "Podcast : Métaclassique #59. Hypnotiser, entretien avec Céline Frigau Manning et Hélène Tysman, réalisé par David Christoffel"
  ],
  "uri_s": "https://hal.science/hal-04836977v1"
}
```

Extrait du `label_xml` (TEI), premier auteur :

```xml
<author role="aut">
  <persName>
    <forename type="first">Céline</forename>
    <surname>Frigau Manning</surname>
  </persName>
  <email type="md5">8d1bdf606d8ecce07577cb9852ffaf37</email>
  <email type="domain">gmail.com</email>
  <idno type="idhal" notation="string">celine-frigau-manning</idno>
  <idno type="idhal" notation="numeric">752404</idno>
  <idno type="halauthorid" notation="string">2688470-752404</idno>
  <idno type="IDREF">https://www.idref.fr/112524346</idno>
  <idno type="ORCID">https://orcid.org/0000-0001-6644-9546</idno>
  <idno type="VIAF">…</idno>
  <affiliation ref="#struct-1063691"/>
  …
</author>
```

## Particularités

### Identifiants et structures des auteurs

Le TEI `label_xml` est le seul champ qui attache à chaque auteur, par position, ses identifiants (ORCID, IdRef, idHAL), son nom et son prénom, et ses structures avec leur ROR. Les listes Solr d'identifiants par auteur (`authORCIDIdExt_s`, `authIdRefIdExt_s`…) gardent seulement les valeurs présentes : leur index ne correspond pas à la position de l'auteur.

Le champ Solr `authFullNameFormIDPersonIDIDHal_fs`, aligné par position, donne le nom complet et le compte HAL (`hal_person_id`) de chaque auteur. Un dépôt sans ce champ est refusé.
