"""Value objects et helpers de normalisation des identifiants publication.

DOI, HALId (document HAL), NNT (Numéro National de Thèse), PMID (PubMed),
PMCID (PubMed Central), ArxivId (arXiv). VOs immuables et auto-validés au
même contrat que ``domain/persons/identifiers.py`` :

- ``X("...")`` strict : lève ``ValidationError`` si malformé
- ``X.try_parse(...)`` tolérant : renvoie None si malformé

Les helpers ``clean_doi``, ``normalize_nnt``, ``extract_hal_id_from_url``,
``normalize_pmid``, ``normalize_pmcid``, ``normalize_arxiv_id`` sont exposés
indépendamment pour les call sites qui veulent juste normaliser sans
construire un VO (typiquement les normalizers de pipeline qui stockent la
forme texte en base). Ils acceptent une URL (location OpenAlex, lien externe
HAL) ou un identifiant brut.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from domain.errors import ValidationError

# ── DOI ────────────────────────────────────────────────────────────

# Suffixe de version sur les DOI de dépôts de données (figshare, zenodo,
# techrxiv, opticaopen…). On normalise vers le DOI "concept" (sans version)
# qui pointe toujours vers la dernière version.
_DOI_VERSION_SUFFIX = re.compile(r"\.v\d+$", re.IGNORECASE)
# Suffixe `/pdf` parfois collé au DOI quand une source expose l'URL de la
# ressource PDF au lieu du DOI canonique — strip pour éviter les doublons.
_DOI_PDF_SUFFIX = re.compile(r"/pdf$", re.IGNORECASE)
_DOI_URL_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
)


def _normalize_doi(raw: str | None) -> str | None:
    """Normalise un DOI brut (préfixe URL, espaces, suffixe de version, casse).

    Lowercase systématique : la spec DOI Handbook précise que le préfixe
    `10.xxxx` est insensible à la casse, et CrossRef (registre officiel)
    traite l'ensemble du DOI en case-insensitive. Stocker tout en minuscules
    évite les faux doublons lors des comparaisons cross-sources.
    """
    if not raw:
        return None
    s = raw.strip().lower()
    for prefix in _DOI_URL_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix) :]
            break
    s = s.strip()
    if not s:
        return None
    # Slash final parasite (artefact d'URL) : `10.x/abc/` ≠ `10.x/abc` sinon, faux doublon.
    # Strippé avant les suffixes ci-dessous, qui sont ancrés en fin (`v2/`, `/pdf/` matchent alors).
    s = s.rstrip("/")
    s = _DOI_VERSION_SUFFIX.sub("", s)
    s = _DOI_PDF_SUFFIX.sub("", s)
    return s or None


@dataclass(frozen=True)
class DOI:
    """Digital Object Identifier, normalisé et validé.

    Lève ValidationError à la construction si la valeur est invalide ou vide.
    Utiliser `DOI.try_parse()` quand l'absence est un cas normal.
    """

    value: str

    def __post_init__(self) -> None:
        cleaned = _normalize_doi(self.value)
        if not cleaned:
            raise ValidationError(f"DOI invalide : {self.value!r}")
        # frozen=True interdit l'assignation directe — détour par object.__setattr__
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> "DOI | None":
        """Tente de parser ; renvoie None si l'entrée est vide ou invalide."""
        if not raw:
            return None
        try:
            return cls(raw)
        except ValidationError:
            return None

    def __str__(self) -> str:
        return self.value


# ── HAL ID (document) ──────────────────────────────────────────────

# Un HAL ID est `<code de collection>-<numéro à 8 chiffres>`. Le code de collection est ouvert :
# `hal`, `tel`, `halshs`, `dumas`, `emse`, `in2p3`, `inserm`, `insu`, `cea`… — des dizaines de
# portails institutionnels, et de nouveaux apparaissent. On matche donc tout préfixe alphanumérique
# plutôt qu'une liste blanche fermée, qui exclurait silencieusement de la déduplication les
# collections non listées (deux dépôts au même `hal_id` `emse-…` ne se relieraient pas).
#
# Le numéro est exigé à 8 chiffres minimum (le docid CCSD est uniforme : tous les hal_id observés en
# base, tous portails confondus, ont exactement 8 chiffres). Ce plancher écarte les fragments
# `mot-chiffres` glanés dans des URLs étrangères — un suffixe de DOI DataCite (`pubdb-2020`,
# `rwth-2020`) ou un PURL (`gro-2`) ne ressemble plus à un hal_id.
_HAL_DOC_BASE = re.compile(r"([a-z][a-z0-9]*-\d{8,})", re.IGNORECASE)


def _is_hal_host(host: str) -> bool:
    """True si l'hôte est un portail HAL : `hal.science` et ses sous-portails, l'infrastructure
    CCSD historique (`*.archives-ouvertes.fr`, `*.ccsd.cnrs.fr`) et les portails white-label
    institutionnels reconnaissables au label `hal` (`hal.inrae.fr`, `www.hal.inserm.fr`…)."""
    host = host.lower()
    if host.endswith(".archives-ouvertes.fr") or host.endswith(".ccsd.cnrs.fr"):
        return True
    return any(label == "hal" or label.startswith("hal-") for label in host.split("."))


def _normalize_hal_id(raw: str | None) -> str | None:
    """Extrait le HAL ID canonique d'une chaîne ou URL.

    Accepte une URL (hal.science, tel.archives-ouvertes.fr, …) ou un HAL ID brut avec éventuel
    suffixe de version (v1, v2). Retourne l'ID sans version (concept HAL).

    Une URL dont l'hôte n'est pas un portail HAL ne porte pas de hal_id : on l'écarte avant le
    regex, car un fragment `mot-chiffres` d'un DOI ou d'un PURL étranger le tromperait. Un token nu
    (sans hôte) reste accepté tel quel.
    """
    if not raw:
        return None
    s = raw.strip().lower()
    host = urlparse(s).hostname
    if host and not _is_hal_host(host):
        return None
    m = _HAL_DOC_BASE.search(s)
    return m.group(1) if m else None


@dataclass(frozen=True)
class HALId:
    """Identifiant HAL d'un document (hal-XXXXX, tel-XXXXX, halshs-XXXXX, …).

    Normalisé en minuscules sans suffixe de version (`hal-04123456v2` →
    `hal-04123456`). Accepte une URL en entrée.
    """

    value: str

    def __post_init__(self) -> None:
        cleaned = _normalize_hal_id(self.value)
        if not cleaned:
            raise ValidationError(f"HAL ID invalide : {self.value!r}")
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> "HALId | None":
        if not raw:
            return None
        try:
            return cls(raw)
        except ValidationError:
            return None

    def __str__(self) -> str:
        return self.value


# ── NNT (Numéro National de Thèse) ─────────────────────────────────


def _normalize_nnt(raw: str | None) -> str | None:
    """Normalise un NNT : uppercase + strip. Format historiquement variable,
    on se contente d'exiger une valeur alphanumérique non vide."""
    if not raw:
        return None
    s = raw.strip().upper()
    if not s or not s.isalnum():
        return None
    return s


@dataclass(frozen=True)
class NNT:
    """Numéro National de Thèse. Format typique : YYYY + code établissement
    + séquence (ex. 2021CLFAC030), mais le format a varié historiquement.

    On normalise en majuscules, trim, et on exige une valeur alphanumérique.
    """

    value: str

    def __post_init__(self) -> None:
        cleaned = _normalize_nnt(self.value)
        if not cleaned:
            raise ValidationError(f"NNT invalide : {self.value!r}")
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> "NNT | None":
        if not raw:
            return None
        try:
            return cls(raw)
        except ValidationError:
            return None

    def __str__(self) -> str:
        return self.value


# ── PMID / PMCID (PubMed) ──────────────────────────────────────────

_PMID_URL_RE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")
_PMC_URL_RE = re.compile(r"ncbi\.nlm\.nih\.gov/pmc/articles/(?:PMC)?(\d+)")
_PMCID_BARE_RE = re.compile(r"^(?:PMC)?(\d+)$", re.IGNORECASE)


def _normalize_pmid(raw: str | None) -> str | None:
    """PMID depuis une URL PubMed ou un identifiant brut (suite de chiffres)."""
    if not raw:
        return None
    s = raw.strip()
    m = _PMID_URL_RE.search(s)
    if m:
        return m.group(1)
    return s if s.isdigit() else None


def _normalize_pmcid(raw: str | None) -> str | None:
    """PMCID (`PMC<digits>`) depuis une URL PubMed Central ou un id brut."""
    if not raw:
        return None
    s = raw.strip()
    m = _PMC_URL_RE.search(s)
    if m:
        return f"PMC{m.group(1)}"
    m = _PMCID_BARE_RE.match(s)
    return f"PMC{m.group(1)}" if m else None


@dataclass(frozen=True)
class PMID:
    """PubMed ID (suite de chiffres). Accepte une URL PubMed en entrée."""

    value: str

    def __post_init__(self) -> None:
        cleaned = _normalize_pmid(self.value)
        if not cleaned:
            raise ValidationError(f"PMID invalide : {self.value!r}")
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> "PMID | None":
        if not raw:
            return None
        try:
            return cls(raw)
        except ValidationError:
            return None

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class PMCID:
    """PubMed Central ID (`PMC<digits>`). Accepte une URL PMC en entrée."""

    value: str

    def __post_init__(self) -> None:
        cleaned = _normalize_pmcid(self.value)
        if not cleaned:
            raise ValidationError(f"PMCID invalide : {self.value!r}")
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> "PMCID | None":
        if not raw:
            return None
        try:
            return cls(raw)
        except ValidationError:
            return None

    def __str__(self) -> str:
        return self.value


# ── arXiv ──────────────────────────────────────────────────────────

_ARXIV_URL_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}|[a-z.\-]+/\d{7})",
    re.IGNORECASE,
)
_ARXIV_BARE_RE = re.compile(r"^(\d{4}\.\d{4,5}|[a-z.\-]+/\d{7})(?:v\d+)?$", re.IGNORECASE)


def _normalize_arxiv_id(raw: str | None) -> str | None:
    """Identifiant arXiv depuis une URL `arxiv.org/abs|pdf/<id>` ou un id brut.

    Gère le format moderne (`2103.00001`) et l'ancien (`math/0211159`),
    en ignorant le suffixe de version (`v2`) et l'extension `.pdf`.
    """
    if not raw:
        return None
    s = raw.strip()
    m = _ARXIV_URL_RE.search(s)
    if m:
        return m.group(1)
    m = _ARXIV_BARE_RE.match(s)
    return m.group(1) if m else None


@dataclass(frozen=True)
class ArxivId:
    """Identifiant arXiv. Accepte une URL arXiv ou un id brut en entrée."""

    value: str

    def __post_init__(self) -> None:
        cleaned = _normalize_arxiv_id(self.value)
        if not cleaned:
            raise ValidationError(f"arXiv ID invalide : {self.value!r}")
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> "ArxivId | None":
        if not raw:
            return None
        try:
            return cls(raw)
        except ValidationError:
            return None

    def __str__(self) -> str:
        return self.value


# ── Helpers publics (API string-in/string-out) ─────────────────────
#
# Ces fonctions couvrent le besoin du code existant qui travaille sur
# des chaînes brutes (pipelines d'extraction, normalisation). Elles
# sont l'équivalent fonctionnel des VO mais en retour string|None.
# Pour un accès structuré et typé, préférer DOI/NNT/HALId directement.


def clean_doi(doi: str | None) -> str | None:
    """Nettoie un DOI brut : préfixe URL, espaces, suffixe de version.
    Retourne le DOI canonique, ou None si l'entrée est vide/inutilisable.
    """
    return _normalize_doi(doi)


def normalize_nnt(nnt: str | None) -> str | None:
    """Normalise un NNT : uppercase, strip whitespace. Retourne None
    si l'entrée est vide ou ne contient pas de caractères alphanumériques."""
    return _normalize_nnt(nnt)


def extract_hal_id_from_url(url: str | None) -> str | None:
    """Extrait le HAL ID canonique d'une URL HAL ou d'un ID brut.

    Accepte tout préfixe de collection (`hal-`, `tel-`, `halshs-`, `dumas-`, `emse-`, `in2p3-`…).
    Ignore le suffixe de version (v1, v2, etc.).

    >>> extract_hal_id_from_url("https://hal.science/hal-04123456v2")
    'hal-04123456'
    """
    return _normalize_hal_id(url)


def extract_doi_from_url(url: str | None) -> str | None:
    """Extrait le DOI d'une URL `doi.org`/`dx.doi.org` ou d'un identifiant
    OAI-PMH `doi:<doi>` (forme prise par `location.id` côté OpenAlex). None sinon.

    >>> extract_doi_from_url("https://doi.org/10.1234/x")
    '10.1234/x'
    >>> extract_doi_from_url("doi:10.1234/x")
    '10.1234/x'
    """
    if not url:
        return None
    if url.startswith("doi:"):
        return clean_doi(url[4:])
    if "doi.org/" in url:
        return clean_doi(url)
    return None


def normalize_pmid(raw: str | None) -> str | None:
    """PMID canonique depuis une URL PubMed ou un id brut ; None sinon."""
    return _normalize_pmid(raw)


def normalize_pmcid(raw: str | None) -> str | None:
    """PMCID canonique (`PMC<digits>`) depuis une URL PMC ou un id brut ; None sinon."""
    return _normalize_pmcid(raw)


def normalize_arxiv_id(raw: str | None) -> str | None:
    """Identifiant arXiv canonique depuis une URL arXiv ou un id brut ; None sinon."""
    return _normalize_arxiv_id(raw)
