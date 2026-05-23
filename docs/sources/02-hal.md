# HAL

## API utilisées

**Search API** (`https://api.archives-ouvertes.fr/search`) — moissonnage des publications.
- Requête par collection labo (27 collections UCA) + portail global `clermont-univ`
- Champs Solr récupérés : voir [infrastructure/hal.py](https://github.com/Y33sha/bibliometrie-uca/blob/master/infrastructure/hal.py) (`HAL_FIELDS`)
- Pagination par offset, 500 résultats/page, 0.5s de délai entre requêtes
- Les identifiants ORCID/IdRef des auteurs sont extraits depuis le TEI `label_xml` retourné par la search API ; aucun appel séparé à `ref/author` n'est nécessaire.

## Données récupérées

- **Publications** : titre, DOI, année, type de document, langue, journal, OA, URI
- **Auteurs** : nom complet, hal_person_id, idHAL, ORCID et IdRef (depuis le TEI `label_xml`)
- **Affiliations** : structures HAL rattachées à chaque auteur via `authIdHasStructure_fs` (pas d'adresses textuelles)
- **Collections** : `collCode_s` indique les collections auxquelles appartient le document

## Particularités

- Les champs auteurs HAL "plats" (`authFullName_s`, `authQuality_s`) sont alignés par position. Les listes d'identifiants externes (`authORCIDIdExt_s`, `authIdRefIdExt_s`) sont **compactées** (valeurs non-null seulement) : l'alignement par auteur passe obligatoirement par le TEI `label_xml` où chaque `<author>` porte ses `<idno type="ORCID">` / `<idno type="IDREF">` / `<idno type="idhal">`.
- Le champ composite `authFullNameFormIDPersonIDIDHal_fs` contient form_id, person_id et idHAL dans un format à parser (`Nom_FacetSep_formId-personId_FacetSep_idhal`)
- Un même document peut apparaître dans plusieurs collections ; le champ `collection` en staging les agrège
- Les documents trouvés uniquement via le portail global (pas dans une collection labo) sont taggés `_portail_clermont-univ`
- Les documents cross-importés depuis OpenAlex ont `collection = NULL` (hors périmètre UCA)
