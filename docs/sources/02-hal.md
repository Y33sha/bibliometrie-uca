# HAL

https://hal.science/

Documentation HAL : https://doc.hal.science/

Documentation API : https://api.archives-ouvertes.fr/docs

## API utilisée

**Search API** (https://api.archives-ouvertes.fr/search) — moissonnage des publications.
- Pas de credentials nécessaires.
- Requête par [collection HAL](../glossaire.md#collection-hal) + année de publication
- Champs Solr récupérés : voir [infrastructure/hal.py](https://github.com/Y33sha/bibliometrie-uca/blob/master/infrastructure/hal.py) (`HAL_FIELDS`)
- Pagination par offset, 500 résultats/page, 0.5s de délai entre requêtes

## Données récupérées

- **Publications** : titre, DOI, année, type de document, langue, journal (titre, ISSN, eISSN, éditeur), OA, URI, résumé, mots-clés, domaines HAL, biblio (volume/numéro/pages)
- **Auteurs** : nom complet, hal_person_id, idHAL, ORCID et IdRef si présents
- **Affiliations** : structures HAL rattachées à chaque auteur via `authIdHasStructure_fs` (pas d'adresses textuelles)

## Exemple de payload

Document `hal-04836977` (3 auteurs, podcast Métaclassique). `abstract_s`, `subTitle_s` et `label_s` tronqués, `authIdHasStructure_fs` réduit à quelques entrées avec acronymes (les vraies entrées portent le nom complet de la structure), `label_xml` élidé (extrait formaté plus bas).

```json
{
  "abstract_s": ["En 1890, dans son Dictionnaire théorique… (tronqué)"],
  "authFullNameFormIDPersonIDIDHal_fs": [
    "Céline Frigau Manning_FacetSep_2688470-752404_FacetSep_celine-frigau-manning",
    "Hélène Tysman_FacetSep_3340220-0_FacetSep_",
    "David Christoffel_FacetSep_1340141-1275740_FacetSep_dcdb"
  ],
  "authIdHasStructure_fs": [
    "2688470-752404_FacetSep_Céline Frigau Manning_JoinSep_1063691_FacetSep_IHRIM",
    "2688470-752404_FacetSep_Céline Frigau Manning_JoinSep_6818_FacetSep_ENS de Lyon",
    "2688470-752404_FacetSep_Céline Frigau Manning_JoinSep_441569_FacetSep_CNRS",
    "1340141-1275740_FacetSep_David Christoffel_JoinSep_557826_FacetSep_UPCité",
    "... 12 autres entrées (Céline 13× + David 2×)"
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
  "domain_s": ["0.shs", "0.shs", "1.shs.hisphilso", "0.shs", "1.shs.musiq"],
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

Extrait du `label_xml` (TEI, ~22k chars), 1er `<author>` :

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

### Champs auteurs alignés vs compactés

Les seuls champs auteurs Solr requêtés (`authQuality_s` et le composite `authFullNameFormIDPersonIDIDHal_fs`) sont alignés par position : longueur = nombre d'auteurs, l'index correspond à la position dans la signature.

HAL expose aussi des listes d'identifiants Solr par auteur (`authIdHal_s`, `authIdHal_i`, `authORCIDIdExt_s`, `authIdRefIdExt_s`) mais elles sont **compactées** (valeurs non-null seulement) : l'index ne correspond plus à la position d'auteur, donc elles sont inutilisables pour reconstituer l'alignement. Ces champs ne sont pas requêtés. Les ORCID et IdRef sont récupérés via le TEI `label_xml` (cf. infra) — seul endroit qui les attache à chaque auteur par position.

### Composite Solr des identifiants

`authFullNameFormIDPersonIDIDHal_fs` : champ par position qui combine 4 identifiants : `Nom_FacetSep_formId-personId_FacetSep_idhal`. C'est le champ central côté auteurs HAL — le nom est dérivé de son 1er segment, et c'est aussi la seule source de `form_id` et `hal_person_id`.

Quand l'idHAL manque, le 3e segment reste vide (cas d'Hélène Tysman : `Hélène Tysman_FacetSep_3340220-0_FacetSep_` — `personId=0` est aussi la valeur sentinelle HAL pour « pas de person »).

Une absence complète de ce champ dans le payload est traitée comme une erreur : le doc reste `processed=FALSE` dans `staging` et un log d'erreur signale le hal_id concerné.

### TEI `label_xml`

Seul champ où ORCID, IdRef et idHAL sont attachés à chaque auteur via les `<idno type="ORCID|IDREF|idhal">` à l'intérieur de chaque `<author>`. Voir l'extrait XML ci-dessus.
