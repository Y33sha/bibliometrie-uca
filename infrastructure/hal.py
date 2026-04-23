"""Configuration de l'adapter HAL Solr.

Liste des champs Solr à récupérer lors des requêtes HAL (staging).
Si un champ est ajouté, il doit être référencé ici pour être extrait
de l'API.
"""

HAL_FIELDS = [
    "halId_s",
    "docid",
    "doiId_s",
    "title_s",
    "subTitle_s",
    "authFullName_s",
    "authIdHal_s",
    "authIdHal_i",
    "authFullNameIdHal_fs",
    "authFullNameId_fs",
    "authFullNameFormIDPersonIDIDHal_fs",
    "authQuality_s",
    "authIdHasStructure_fs",
    # label_xml (TEI) : seul champ qui attache ORCID/IdRef à chaque auteur
    # par position. Les listes `authORCIDIdExt_s` / `authIdRefIdExt_s`
    # sont compactées (valeurs non-null seulement, pas d'alignement).
    "label_xml",
    "producedDateY_i",
    "publicationDate_s",
    "docType_s",
    "docSubType_s",
    "language_s",
    "journalTitle_s",
    "journalIssn_s",
    "journalEissn_s",
    "journalPublisher_s",
    "bookTitle_s",
    "publisher_s",
    "conferenceTitle_s",
    "openAccess_bool",
    "linkExtUrl_s",
    "uri_s",
    "label_s",
    "collCode_s",
    "structId_i",
    "structName_s",
    "structType_s",
    "structAcronym_s",
    "nntId_s",
    "abstract_s",
    "keyword_s",
    "domain_s",
    "volume_s",
    "issue_s",
    "page_s",
]

HAL_FIELDS_STR = ",".join(HAL_FIELDS)
