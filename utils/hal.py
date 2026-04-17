"""Utilitaires HAL partagés entre extraction, normalisation et processing."""

import re

# Champs Solr à récupérer lors des requêtes HAL (staging)
HAL_FIELDS = [
    "halId_s",
    "docid",
    "doiId_s",
    "title_s",
    "subTitle_s",
    "authFullName_s",
    "authIdHal_s",
    "authOrcid_s",
    "authIdHal_i",
    "authFullNameIdHal_fs",
    "authFullNameId_fs",
    "authFullNameFormIDPersonIDIDHal_fs",
    "authQuality_s",
    "authIdHasStructure_fs",
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


def extract_hal_id_from_url(url: str | None) -> str | None:
    """Extrait le halId depuis une URL HAL.

    Gère les préfixes hal, tel, halshs, inserm, pasteur, cea, ineris.
    Ignore le suffixe de version (v1, v2, etc.).

    >>> extract_hal_id_from_url("https://hal.science/hal-04123456v2")
    'hal-04123456'
    """
    if not url:
        return None
    match = re.search(r"((?:hal|tel|halshs|inserm|pasteur|cea|ineris)-\d+)", url)
    return match.group(1) if match else None
