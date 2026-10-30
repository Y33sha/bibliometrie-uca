"""Identifiants de publication : DOI et son préfixe, identifiant HAL, NNT, PMID, PMCID, identifiant arXiv, ISSN, ISBN."""

import re
from typing import NamedTuple
from urllib.parse import unquote, urlparse

from domain.identifiers import NormalizedIdentifier
from domain.urls import is_host

DOI_VERSION_SUFFIX_PATTERN = r"[./]v(\d{1,3})$"
"""Suffixe de version d'un DOI normalisé : `.v` ou `/v` suivi de trois chiffres au plus (`10.6084/m9.figshare.123.v2`, `10.21203/rs.3.rs-123/v1`). Un numéro plus long est un code d'article (`10.1681/asn.v12102060`). Le motif vaut aussi en SQL."""
_DOI_VERSION_SUFFIX = re.compile(DOI_VERSION_SUFFIX_PATTERN)
# Suffixe d'URL de page d'éditeur (`/pdf`, `/full`, `/abstract`) collé au DOI. Le DOI suffixé est inconnu de doi.org.
_DOI_URL_PAGE_SUFFIX = re.compile(r"/(?:pdf|full|abstract)$", re.IGNORECASE)
_DOI_URL_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "https://www.doi.org/",
    "http://www.doi.org/",
)
# Tirets typographiques Unicode, ramenés sur le `-` ASCII.
_DASH_TRANSLATION = {ord(c): "-" for c in "‐‑‒–—―−﹘﹣－"}
# Forme d'un DOI : le préfixe `10.<chiffres>`, une barre oblique, un suffixe non vide.
_DOI_SHAPE = re.compile(r"10\.\d+/\S")
# Préfixe DOI en tête d'une chaîne, suivi d'autre chose qu'une lettre, un chiffre ou un point (« 10.101621gloenvcha.2020.102168 » est sans préfixe).
_DOI_PREFIX_RE = re.compile(r"(10\.\d+)(?![\w.])")
# Séparateurs des identifiants qui s'écrivent par groupes de chiffres (ISSN, ISBN), retirés pour les comparer.
_SEPARATORS_RE = re.compile(r"[\s-]")


def clean_doi(raw: str | None) -> str | None:
    """Renvoie la forme normalisée d'un DOI brut : en minuscules, sans préfixe d'URL ni schéma, sans artefact de copier-coller. `None` si la valeur n'a pas la forme d'un DOI. Les DOI sont insensibles à la casse."""
    if not raw:
        return None
    s = raw.strip().lower()
    # Une étape de fin (suffixe de page d'éditeur) peut laisser un résidu pour une étape de début : la passe se répète jusqu'à stabilité.
    while s:
        reduced = _normalize_doi_step(s)
        if reduced == s:
            break
        s = reduced
    # Une valeur sans la forme d'un DOI n'en est pas un : identifiant numérique, URL d'article.
    return s if _DOI_SHAPE.match(s) else None


def _normalize_doi_step(s: str) -> str:
    """Applique une passe de nettoyage à un DOI en minuscules."""
    if s.startswith("doi:"):
        # Préfixe de schéma (DataCite, identifiant OAI-PMH d'OpenAlex).
        s = s[len("doi:") :]
    for prefix in _DOI_URL_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix) :]
            break
    s = s.strip()
    # Décodage pourcent (`%2f` = `/`). La passe suivante décode un double encodage (`%252f`).
    if "%" in s:
        s = unquote(s)
    s = s.translate(_DASH_TRANSLATION)
    # Paramètres de suivi d'une URL (`?utm_…`).
    s = s.split("?", 1)[0]
    # Liste de DOI : le premier désigne l'œuvre, les suivants des formes liées (versions, rapports de relecture).
    s = s.split(";", 1)[0].strip()
    # Barre oblique finale d'une URL.
    s = s.rstrip("/")
    # Ponctuation finale de copier-coller. Une parenthèse finale part seulement si elle est non appariée (`10.1007/jhep07(2020)108`).
    s = s.rstrip(".,;:<>")
    if s.endswith(")") and s.count(")") > s.count("("):
        s = s[:-1]
    if s.endswith("(") and s.count("(") > s.count(")"):
        s = s[:-1]
    return _DOI_URL_PAGE_SUFFIX.sub("", s)


class DoiVersion(NamedTuple):
    """Forme sans version d'un DOI à suffixe de version, et numéro de la version."""

    unversioned: str
    number: int


def doi_version(doi: str) -> DoiVersion | None:
    """Renvoie la forme sans version et le numéro de version d'un DOI normalisé, ou `None` sans suffixe de version."""
    match = _DOI_VERSION_SUFFIX.search(doi)
    if match is None:
        return None
    return DoiVersion(doi[: match.start()], int(match.group(1)))


class DOI(NormalizedIdentifier):
    """DOI normalisé. Lève `ValidationError` si la valeur nettoyée n'a pas la forme `10.<chiffres>/<suffixe>`."""

    label = "DOI"
    normalize = staticmethod(clean_doi)

    @property
    def prefix(self) -> DoiPrefix:
        """Préfixe du DOI, qui identifie son registrant."""
        return DoiPrefix(self.value.split("/", 1)[0])


def _doi_prefix(raw: str | None) -> str | None:
    """Renvoie le préfixe en tête de `raw`, ou `None`."""
    match = _DOI_PREFIX_RE.match((raw or "").strip())
    return match.group(1) if match else None


class DoiPrefix(NormalizedIdentifier):
    """Préfixe DOI (`10.<chiffres>`), partie d'un DOI avant la première barre oblique. Accepte un DOI complet, des espaces ou une ponctuation finale. Lève `ValidationError` sans préfixe en tête (« doi:10.5194 », « https: »)."""

    label = "Préfixe DOI"
    normalize = staticmethod(_doi_prefix)


# Dépôt HAL : `<code de portail>-<numéro>`, `_` pour séparateur sur ArchiveSIC. Tout code est accepté. Au moins 8 chiffres, pour écarter des fragments d'URL (`pubdb-2020`).
HAL_DOC_PATTERN = r"[a-z][a-z0-9]*[-_]\d{8,}"
"""Motif d'un identifiant de dépôt HAL, insensible à la casse ; repris en SQL par `sql_fragments`."""
_HAL_DOC_BASE = re.compile(f"({HAL_DOC_PATTERN})", re.IGNORECASE)

# Autorité d'un identifiant OAI-PMH `[<préfixe>:]oai:<autorité>:<id local>`, comme `oai:HAL:hal-04123456v1` dans les localisations OpenAlex.
_OAI_AUTHORITY = re.compile(r"(?:^|:)oai:([^:]+):", re.IGNORECASE)


def is_hal_host(host: str) -> bool:
    """Vrai si l'hôte est un portail HAL : `hal.science` et ses sous-portails, `*.archives-ouvertes.fr`, `*.ccsd.cnrs.fr`, et les portails institutionnels dont un label est `hal` ou commence par `hal-` (`hal.inrae.fr`)."""
    host = host.lower()
    if host.endswith((".archives-ouvertes.fr", ".ccsd.cnrs.fr")):
        return True
    return any(label == "hal" or label.startswith("hal-") for label in host.split("."))


def extract_hal_id_from_url(raw: str | None) -> str | None:
    """Renvoie l'identifiant HAL sans version, tiré d'une URL de portail HAL, d'un identifiant OAI-PMH HAL (`oai:HAL:hal-04123456v1`) ou d'un identifiant nu.

    `None` pour une URL d'un autre hôte, ou un identifiant OAI-PMH d'une autre autorité : leurs fragments `mot-chiffres` ressemblent à un identifiant HAL (`oai:pure.rug.nl:openaire/1b9c53c2-4cfa-49c4-b454-3339841149ee`).
    """
    if not raw:
        return None
    s = raw.strip().lower()
    host = urlparse(s).hostname
    if host:
        if not is_hal_host(host):
            return None
    elif (oai := _OAI_AUTHORITY.search(s)) and oai.group(1) != "hal":
        return None
    m = _HAL_DOC_BASE.search(s)
    return m.group(1) if m else None


class HALId(NormalizedIdentifier):
    """Identifiant HAL d'un dépôt (`hal-…`, `tel-…`, `halshs-…`), en minuscules et sans version (`hal-04123456v2` → `hal-04123456`). Accepte une URL."""

    label = "HAL ID"
    normalize = staticmethod(extract_hal_id_from_url)


_NNT_RE = re.compile(r"[0-9A-Z]+")


def normalize_nnt(raw: str | None) -> str | None:
    """Renvoie le NNT en majuscules. `None` s'il contient autre chose que des chiffres et des lettres ASCII, comme les identifiants OAI-PMH donnés à sa place par OpenAlex (`oai:HAL:…`, `ark:/…`)."""
    if not raw:
        return None
    s = raw.strip().upper()
    if not _NNT_RE.fullmatch(s):
        return None
    return s


class NNT(NormalizedIdentifier):
    """Numéro national de thèse, le plus souvent de la forme année, code d'établissement, séquence (`2021CLFAC030`)."""

    label = "NNT"
    normalize = staticmethod(normalize_nnt)


_PMID_URL_RE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")
_PMC_URL_RE = re.compile(
    r"(?:ncbi\.nlm\.nih\.gov/pmc|pmc\.ncbi\.nlm\.nih\.gov)/articles/(?:PMC)?(\d+)"
)
_PMCID_BARE_RE = re.compile(r"^(?:PMC)?(\d+)$", re.IGNORECASE)


def normalize_pmid(raw: str | None) -> str | None:
    """Extrait le PMID d'une URL PubMed ou d'un identifiant brut (suite de chiffres)."""
    if not raw:
        return None
    s = raw.strip()
    m = _PMID_URL_RE.search(s)
    if m:
        return m.group(1)
    return s if s.isdigit() else None


def normalize_pmcid(raw: str | None) -> str | None:
    """Extrait le PMCID (`PMC<chiffres>`) d'une URL PubMed Central ou d'un identifiant brut."""
    if not raw:
        return None
    s = raw.strip()
    m = _PMC_URL_RE.search(s)
    if m:
        return f"PMC{m.group(1)}"
    m = _PMCID_BARE_RE.match(s)
    return f"PMC{m.group(1)}" if m else None


class PMID(NormalizedIdentifier):
    """PubMed ID (suite de chiffres). Accepte une URL PubMed."""

    label = "PMID"
    normalize = staticmethod(normalize_pmid)


class PMCID(NormalizedIdentifier):
    """PubMed Central ID (`PMC<chiffres>`). Accepte une URL PubMed Central."""

    label = "PMCID"
    normalize = staticmethod(normalize_pmcid)


_ARXIV_URL_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}|[a-z.\-]+/\d{7})",
    re.IGNORECASE,
)
_ARXIV_BARE_RE = re.compile(r"^(\d{4}\.\d{4,5}|[a-z.\-]+/\d{7})(?:v\d+)?$", re.IGNORECASE)


def normalize_arxiv_id(raw: str | None) -> str | None:
    """Extrait l'identifiant arXiv, `AAAA.NNNNN` (`2103.00001`) ou `catégorie/NNNNNNN` (`math/0211159`), d'une URL `arxiv.org/abs|pdf/<id>` ou d'un identifiant brut. Suffixe de version (`v2`) et extension `.pdf` sont ignorés."""
    if not raw:
        return None
    s = raw.strip()
    m = _ARXIV_URL_RE.search(s)
    if m:
        return m.group(1)
    m = _ARXIV_BARE_RE.match(s)
    return m.group(1) if m else None


class ArxivId(NormalizedIdentifier):
    """Identifiant arXiv. Accepte une URL arXiv."""

    label = "arXiv ID"
    normalize = staticmethod(normalize_arxiv_id)


_ISSN_RE = re.compile(r"(?:ISSN[:\s]*)?(\d{4})-?(\d{3})([\dX])", re.IGNORECASE | re.ASCII)


def _mod11_check_digit(digits: str) -> str:
    """Calcule la clé de contrôle modulo 11 (ISSN, ISBN-10) : poids décroissants jusqu'à 2, `X` pour 10."""
    total = sum(int(c) * w for c, w in zip(digits, range(len(digits) + 1, 1, -1), strict=True))
    check = (11 - total % 11) % 11
    return "X" if check == 10 else str(check)


def _normalize_issn(raw: str | None) -> str | None:
    """Renvoie l'ISSN sous la forme `NNNN-NNNC`, `X` en majuscule. Tolère l'absence de tiret et le préfixe `ISSN`. `None` si la clé de contrôle est fausse."""
    if not raw:
        return None
    m = _ISSN_RE.fullmatch(raw.strip().translate(_DASH_TRANSLATION))
    if not m:
        return None
    first, middle, check = m.group(1), m.group(2), m.group(3).upper()
    if _mod11_check_digit(first + middle) != check:
        return None
    return f"{first}-{middle}{check}"


def issn_rejection_reason(raw: str) -> str:
    """Renvoie le motif du rejet d'une valeur d'ISSN : clé de contrôle fausse si la forme `NNNN-NNNC` est respectée, forme invalide sinon."""
    if _ISSN_RE.fullmatch(raw.strip().translate(_DASH_TRANSLATION)):
        return "clé de contrôle fausse"
    return "forme invalide"


class ISSN(NormalizedIdentifier):
    """International Standard Serial Number (`NNNN-NNNC`), clé de contrôle vérifiée."""

    label = "ISSN"
    normalize = staticmethod(_normalize_issn)


_ISSN_SEARCH_RE = re.compile(r"\d{1,8}|\d{7}X", re.ASCII)


def issn_search_prefix(raw: str) -> str | None:
    """Renvoie le début d'ISSN d'un terme de recherche, sans séparateur, `X` en majuscule ; `None` si le terme n'a pas cette forme. Le terme peut être tronqué à droite. La clé de contrôle n'est pas vérifiée : les ISSN mal formés d'une revue restent cherchables."""
    cleaned = _SEPARATORS_RE.sub("", raw.strip().translate(_DASH_TRANSLATION)).upper()
    return cleaned if _ISSN_SEARCH_RE.fullmatch(cleaned) else None


_ISBN_SEARCH_RE = re.compile(r"97[89]\d{0,10}", re.ASCII)


def isbn_search_prefix(raw: str) -> str | None:
    """Renvoie le début d'ISBN-13 d'un terme de recherche, sans séparateur ; `None` si le terme n'a pas cette forme. Un ISBN-13 commence par 978 ou 979."""
    cleaned = _SEPARATORS_RE.sub("", raw.strip().translate(_DASH_TRANSLATION))
    return cleaned if _ISBN_SEARCH_RE.fullmatch(cleaned) else None


def issn_typo_candidates(raw: str) -> frozenset[str]:
    """Renvoie les ISSN valides à une faute de frappe près d'une valeur : un caractère remplacé, ou deux caractères voisins inversés. Vide si la valeur n'a pas huit caractères hors tiret."""
    s = raw.replace("-", "").strip().upper()
    if len(s) != 8:
        return frozenset()
    variants = [s[:i] + c + s[i + 1 :] for i in range(8) for c in "0123456789X" if c != s[i]]
    variants += [s[:i] + s[i + 1] + s[i] + s[i + 2 :] for i in range(7) if s[i] != s[i + 1]]
    return frozenset(str(issn) for v in variants if (issn := ISSN.try_parse(v)))


_ISBN_PREFIX_RE = re.compile(r"ISBN(?:-1[03])?[:\s]*", re.IGNORECASE)
_ISBN13_RE = re.compile(r"97[89]\d{10}", re.ASCII)
_ISBN10_RE = re.compile(r"\d{9}[\dX]", re.ASCII)


def _isbn13_check_digit(digits: str) -> str:
    """Calcule la clé de contrôle modulo 10 d'un ISBN-13 : poids alternés 1 et 3."""
    total = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(digits))
    return str((10 - total % 10) % 10)


def _normalize_isbn(raw: str | None) -> str | None:
    """Renvoie l'ISBN-13 sans séparateur. Un ISBN-10 est converti en ISBN-13 (préfixe 978). Tolère tirets, espaces et préfixe `ISBN`. `None` si la clé de contrôle est fausse."""
    if not raw:
        return None
    s = _ISBN_PREFIX_RE.sub("", raw.strip().translate(_DASH_TRANSLATION), count=1)
    s = _SEPARATORS_RE.sub("", s).upper()
    if _ISBN13_RE.fullmatch(s):
        return s if _isbn13_check_digit(s[:12]) == s[12] else None
    if _ISBN10_RE.fullmatch(s) and _mod11_check_digit(s[:9]) == s[9]:
        body = f"978{s[:9]}"
        return body + _isbn13_check_digit(body)
    return None


class ISBN(NormalizedIdentifier):
    """International Standard Book Number, sous sa forme ISBN-13 sans séparateur, clé de contrôle vérifiée. Accepte un ISBN-10."""

    label = "ISBN"
    normalize = staticmethod(_normalize_isbn)


# Suite de chiffres, tirets et espaces de la longueur d'un ISBN, isolée de ce qui l'entoure. La clé de contrôle départage ensuite les vrais ISBN.
_ISBN_CANDIDATE_RE = re.compile(r"(?<![\dXx])(?:97[89][-\s]?)?(?:\d[-\s]?){9}[\dXx](?![\dXx])")


def find_isbns(text: str | None) -> list[str]:
    """Renvoie les ISBN-13 contenus dans `text`, dans l'ordre, sans doublon.

    Une zone donne parfois plusieurs ISBN (`978-2-84867-659-3 ; 978-2-84867-660-9`), un EAN qui répète l'ISBN, ou un ISBN suivi d'un numéro de chapitre (`978-3-319-77273-8_16`). Une suite de chiffres dont la clé de contrôle est fausse est écartée, de même qu'un ISSN, plus court.
    """
    found: list[str] = []
    for match in _ISBN_CANDIDATE_RE.finditer(text or ""):
        isbn = ISBN.try_parse(match.group(0))
        if isbn is not None and isbn.value not in found:
            found.append(isbn.value)
    return found


def meme_registrant(doi_a: str | None, doi_b: str | None) -> bool:
    """Vrai si deux DOI ont le même préfixe, donc le même registrant."""
    prefixe = DoiPrefix.try_parse(doi_a)
    return prefixe is not None and prefixe == DoiPrefix.try_parse(doi_b)


def extract_doi_from_url(url: str | None) -> str | None:
    """Renvoie le DOI d'une URL `doi.org` ou d'un identifiant OAI-PMH `doi:<doi>`, ou `None`.

    >>> extract_doi_from_url("https://doi.org/10.1234/x")
    '10.1234/x'
    >>> extract_doi_from_url("doi:10.1234/x")
    '10.1234/x'
    """
    if not url:
        return None
    if url.startswith("doi:"):
        return clean_doi(url[4:])
    if is_host(url, "doi.org"):
        return clean_doi(url)
    return None
