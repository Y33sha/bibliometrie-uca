"""Licences des publications : vocabulaire fermé, et normalisation des formes brutes des sources (URL, identifiant SPDX, code OpenAlex ou scanR)."""

import re
from enum import StrEnum

from domain.publications.doc_types import DocType
from domain.sources.registry import Source
from domain.types import JsonValue, as_mapping, as_sequence, as_str


class License(StrEnum):
    """Licence d'une publication, sans numéro de version."""

    CC_BY = "cc-by"
    CC_BY_SA = "cc-by-sa"
    CC_BY_ND = "cc-by-nd"
    CC_BY_NC = "cc-by-nc"
    CC_BY_NC_SA = "cc-by-nc-sa"
    CC_BY_NC_ND = "cc-by-nc-nd"
    # Domaine public : renonciation CC0, Public Domain Mark (œuvre d'un agent fédéral américain, par exemple).
    PUBLIC_DOMAIN = "public-domain"
    # Licence Ouverte Etalab.
    LICENCE_OUVERTE = "licence-ouverte"
    # Licence de logiciel libre : MIT, BSD, GPL, LGPL, Apache, CeCILL, AFL.
    OPEN_SOURCE = "open-source"
    # Autorisation de diffusion donnée à une archive : HAL, licence non exclusive arXiv.
    REPOSITORY_DISTRIBUTION = "repository-distribution"
    # Licence ouverte propre à l'éditeur (`publisher-specific-oa` d'OpenAlex et de scanR).
    PUBLISHER_OPEN = "publisher-open"
    # Licence ouverte non précisée (`other-oa` d'OpenAlex).
    OTHER_OA = "other-oa"
    ALL_RIGHTS_RESERVED = "all-rights-reserved"
    # Licence déclarée mais non classée : politique de données d'un projet, par exemple.
    OTHER = "other"


LICENSE_LABELS: dict[License, str] = {
    License.CC_BY: "CC BY",
    License.CC_BY_SA: "CC BY-SA",
    License.CC_BY_ND: "CC BY-ND",
    License.CC_BY_NC: "CC BY-NC",
    License.CC_BY_NC_SA: "CC BY-NC-SA",
    License.CC_BY_NC_ND: "CC BY-NC-ND",
    License.PUBLIC_DOMAIN: "Domaine public (CC0, Public Domain Mark)",
    License.LICENCE_OUVERTE: "Licence Ouverte Etalab",
    License.OPEN_SOURCE: "Licence de logiciel libre",
    License.REPOSITORY_DISTRIBUTION: "Autorisation de diffusion (HAL, arXiv)",
    License.PUBLISHER_OPEN: "Licence ouverte de l'éditeur",
    License.OTHER_OA: "Autre licence ouverte",
    License.ALL_RIGHTS_RESERVED: "Droits réservés",
    License.OTHER: "Autre licence",
}
"""Libellé français de chaque licence, dans l'ordre de l'enum."""

NO_LICENSE_LABEL = "Aucune licence"


def license_label(value: str | None) -> str:
    """Renvoie le libellé français d'une licence, `NO_LICENSE_LABEL` sans licence."""
    return LICENSE_LABELS[License(value)] if value else NO_LICENSE_LABEL


# Sources de la licence de la version éditeur d'une publication, par priorité.
PUBLISHER_LICENSE_SOURCES: tuple[Source, ...] = (
    Source.CROSSREF,
    Source.OPENALEX,
    Source.SCANR,
    Source.DATACITE,
)
# Pour un jeu de données ou un logiciel, DataCite passe en tête.
DATA_LICENSE_SOURCES: tuple[Source, ...] = (
    Source.DATACITE,
    Source.CROSSREF,
    Source.OPENALEX,
    Source.SCANR,
)
DATA_DOC_TYPES: frozenset[str] = frozenset({DocType.DATASET, DocType.SOFTWARE})
# Source de la licence du fichier déposé.
DEPOSIT_LICENSE_SOURCE = Source.HAL


def publisher_license_sources(doc_type: str | None) -> tuple[Source, ...]:
    """Renvoie les sources de la licence de la version éditeur, par priorité, selon le type de document."""
    return DATA_LICENSE_SOURCES if doc_type in DATA_DOC_TYPES else PUBLISHER_LICENSE_SOURCES


# Éléments d'une licence Creative Commons, dans l'ordre de son code.
_CC_ELEMENTS = ("by", "nc", "sa", "nd")
_CC_CODES = {
    "by": License.CC_BY,
    "by-sa": License.CC_BY_SA,
    "by-nd": License.CC_BY_ND,
    "by-nc": License.CC_BY_NC,
    "by-nc-sa": License.CC_BY_NC_SA,
    "by-nc-nd": License.CC_BY_NC_ND,
}

# Codes sans URL : vocabulaire OpenAlex et scanR, identifiants SPDX et libellés de DataCite.
_CODES = {
    "public-domain": License.PUBLIC_DOMAIN,
    "cc-pddc": License.PUBLIC_DOMAIN,
    "publisher-specific-oa": License.PUBLISHER_OPEN,
    "other-oa": License.OTHER_OA,
    "other-open": License.OTHER_OA,
    "reserved": License.ALL_RIGHTS_RESERVED,
    "inc-1.0": License.ALL_RIGHTS_RESERVED,
    "etalab-1.0": License.LICENCE_OUVERTE,
    "etalab-2.0": License.LICENCE_OUVERTE,
}
_OPEN_SOURCE_CODE = re.compile(
    r"^(mit|0bsd|bsd-.+|(l|a)?gpl-.+|apache-.+|cecill.*|afl-.+|mpl-.+|eupl-.+|isc|unlicense)$"
)
_CC0_CODE = re.compile(r"^cc0(-\d+(\.\d+)*)?$")

# URL sans schéma ni `www.`, en minuscules : préfixe → licence.
_URL_PREFIXES = (
    ("creativecommons.org/publicdomain/", License.PUBLIC_DOMAIN),
    ("creativecommons.org/share-your-work/public-domain/", License.PUBLIC_DOMAIN),
    ("creativecommons.org/public-domain/", License.PUBLIC_DOMAIN),
    ("creativecommons.org/licenses/publicdomain", License.PUBLIC_DOMAIN),
    ("about.hal.science/hal-authorisation", License.REPOSITORY_DISTRIBUTION),
    ("arxiv.org/licenses/nonexclusive-distrib", License.REPOSITORY_DISTRIBUTION),
    ("arxiv.org/licenses/assumed-1991-2003", License.REPOSITORY_DISTRIBUTION),
    ("hal.science/licences/copyright", License.ALL_RIGHTS_RESERVED),
    ("rightsstatements.org/vocab/inc", License.ALL_RIGHTS_RESERVED),
    ("rightsstatements.org/page/inc", License.ALL_RIGHTS_RESERVED),
    ("rioxx.net/licenses/all-rights-reserved", License.ALL_RIGHTS_RESERVED),
    ("purl.org/net/rdflicense/allrightsreserved", License.ALL_RIGHTS_RESERVED),
    ("en.wikipedia.org/wiki/all_rights_reserved", License.ALL_RIGHTS_RESERVED),
    ("opensource.org/licenses/", License.OPEN_SOURCE),
    ("gnu.org/licenses/", License.OPEN_SOURCE),
    ("apache.org/licenses/", License.OPEN_SOURCE),
    ("cecill.info", License.OPEN_SOURCE),
)
_ETALAB_URL = re.compile(r"etalab.*licence-ouverte|licence-ouverte.*etalab")
_CC_URL = re.compile(r"^creativecommons\.org/licenses/([a-z-]+)")
_SPDX_URL = re.compile(r"^spdx\.org/licenses/([^/]+?)(\.html)?$")


def _cc_code(elements: str) -> License | None:
    """Renvoie la licence Creative Commons de code `elements` (`by-nc-nd`, `by-nd-nc`), dans n'importe quel ordre des éléments."""
    parts = elements.split("-")
    if not parts or parts[0] != "by" or any(p not in _CC_ELEMENTS for p in parts):
        return None
    return _CC_CODES.get("-".join(e for e in _CC_ELEMENTS if e in parts))


def _from_code(code: str) -> License | None:
    """Renvoie la licence d'un code sans URL : identifiant SPDX, libellé DataCite, code OpenAlex ou scanR."""
    code = re.sub(r"\s+", "-", code.strip().lower())
    if code in _CODES:
        return _CODES[code]
    if _CC0_CODE.match(code):
        return License.PUBLIC_DOMAIN
    if code.startswith("cc-"):
        elements = re.match(r"^cc-((?:by|nc|sa|nd)(?:-(?:by|nc|sa|nd))*)", code)
        return _cc_code(elements.group(1)) if elements else None
    if _OPEN_SOURCE_CODE.match(code):
        return License.OPEN_SOURCE
    return None


def _from_url(url: str) -> License | None:
    """Renvoie la licence d'une URL de licence."""
    u = re.sub(r"^https?://", "", url.strip().lower())
    u = re.sub(r"^www\.", "", u).rstrip("/")
    for prefix, matched in _URL_PREFIXES:
        if u.startswith(prefix):
            return matched
    if match := _CC_URL.match(u):
        return _cc_code(match.group(1))
    if match := _SPDX_URL.match(u):
        return _from_code(match.group(1))
    if _ETALAB_URL.search(u):
        return License.LICENCE_OUVERTE
    return None


def is_access_right(raw: str) -> bool:
    """Vrai pour un droit d'accès (vocabulaire COAR, `info:eu-repo`), qui n'est pas une licence."""
    value = re.sub(r"^https?://", "", raw.strip().lower())
    return value.startswith(("info:eu-repo", "purl.org/coar"))


def normalize_license(raw: str | None) -> License | None:
    """Renvoie la licence désignée par une forme brute, ou `None` pour une forme vide, non reconnue, ou qui n'est pas une licence (droit d'accès, URL d'éditeur)."""
    if not raw or not raw.strip() or is_access_right(raw):
        return None
    value = raw.strip()
    if "/" in value:
        return _from_url(value)
    return _from_code(value)


def crossref_license(entries: JsonValue) -> License | None:
    """Renvoie la licence de la version éditeur d'un enregistrement source Crossref (`license`) : entrée `vor`, à défaut `unspecified`."""
    for version in ("vor", "unspecified"):
        for entry in as_sequence(entries):
            item = as_mapping(entry)
            if as_str(item.get("content-version")) == version:
                if found := normalize_license(as_str(item.get("URL"))):
                    return found
    return None


def datacite_license(rights: JsonValue) -> License | None:
    """Renvoie la licence d'un enregistrement source DataCite (`rightsList`) : identifiant SPDX, à défaut URI. Une licence déclarée par son URI mais non reconnue vaut `OTHER`."""
    declared = False
    for entry in as_sequence(rights):
        item = as_mapping(entry)
        uri = as_str(item.get("rightsUri"))
        if found := normalize_license(as_str(item.get("rightsIdentifier"))) or normalize_license(
            uri
        ):
            return found
        declared = declared or bool(uri and uri.strip() and not is_access_right(uri))
    return License.OTHER if declared else None
