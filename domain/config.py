"""Règles des paramètres applicatifs : forme imposée à chaque clé, valeur appliquée quand la clé est absente."""

from collections.abc import Callable
from enum import StrEnum
from typing import NamedTuple

from domain.countries import NO_COUNTRY_CODE, normalize_country_code
from domain.errors import ValidationError
from domain.structures.structure import StructureType
from domain.types import JsonValue

LABORATORY_TYPES_KEY = "laboratory_types"
"""Clé des types de structure traités comme laboratoires."""

DEFAULT_LABORATORY_TYPES: tuple[StructureType, ...] = (StructureType.LABO,)
"""Types de structure traités comme laboratoires quand la clé est absente."""

# Clés de configuration consommées par une page publique
PUBLIC_CONFIG_KEYS: frozenset[str] = frozenset({LABORATORY_TYPES_KEY})


class ConfigKey(StrEnum):
    """Clé d'un réglage numérique du pipeline."""

    UNPAYWALL_MAX_PER_RUN = "unpaywall_max_per_run"
    """Nombre de DOI vérifiés auprès d'Unpaywall par run."""
    FETCH_MISSING_MAX_PER_SOURCE = "fetch_missing_max_per_source"
    """Nombre de DOI interrogés par source cible à la recherche par DOI (phase `fetch_missing`)."""
    SUDOC_MAX_PER_RUN = "sudoc_max_per_run"
    """Nombre de revues vérifiées dans le Sudoc par run."""
    DOI_RESOLUTION_MAX_PER_RUN = "doi_resolution_max_per_run"
    """Nombre de DOI dont l'URL de résolution est lue chez doi.org par run."""
    FETCH_STALE_AFTER_DAYS = "fetch_stale_after_days"
    """Âge au-delà duquel un enregistrement source est interrogé de nouveau à sa source."""
    FETCH_MISSING_RETRY_AFTER_DAYS = "fetch_missing_retry_after_days"
    """Délai avant de chercher de nouveau un identifiant resté introuvable dans une source."""
    UNPAYWALL_RECHECK_AFTER_DAYS = "unpaywall_recheck_after_days"
    """Délai avant de vérifier de nouveau le statut open access d'une publication auprès d'Unpaywall."""
    DOI_RESOLUTION_RECHECK_AFTER_DAYS = "doi_resolution_recheck_after_days"
    """Délai avant de relire chez doi.org l'URL de résolution d'un DOI."""
    DOAJ_REFRESH_AFTER_DAYS = "doaj_refresh_after_days"
    """Délai avant de télécharger de nouveau le fichier du DOAJ."""
    PIPELINE_START_YEAR_FULL = "pipeline_start_year_full"
    """Première année moissonnée."""


class ConfigKind(StrEnum):
    """Forme d'un réglage numérique."""

    CAP = "cap"
    """Plafond d'interrogations, entier positif ou nul ; zéro pour illimité."""
    DELAY = "delay"
    """Délai de réinterrogation, en jours, au moins un."""
    YEAR = "year"
    """Année, entre `MIN_YEAR` et `MAX_YEAR`."""


class ConfigSetting(NamedTuple):
    """Forme d'un réglage, et valeur retenue quand la clé est absente ou illisible."""

    kind: ConfigKind
    default: int | None = None


SETTINGS: dict[ConfigKey, ConfigSetting] = {
    ConfigKey.UNPAYWALL_MAX_PER_RUN: ConfigSetting(ConfigKind.CAP, 10_000),
    ConfigKey.FETCH_MISSING_MAX_PER_SOURCE: ConfigSetting(ConfigKind.CAP, 0),
    ConfigKey.SUDOC_MAX_PER_RUN: ConfigSetting(ConfigKind.CAP, 10_000),
    ConfigKey.DOI_RESOLUTION_MAX_PER_RUN: ConfigSetting(ConfigKind.CAP, 10_000),
    ConfigKey.FETCH_STALE_AFTER_DAYS: ConfigSetting(ConfigKind.DELAY, 90),
    ConfigKey.FETCH_MISSING_RETRY_AFTER_DAYS: ConfigSetting(ConfigKind.DELAY, 30),
    ConfigKey.UNPAYWALL_RECHECK_AFTER_DAYS: ConfigSetting(ConfigKind.DELAY, 15),
    ConfigKey.DOI_RESOLUTION_RECHECK_AFTER_DAYS: ConfigSetting(ConfigKind.DELAY, 180),
    ConfigKey.DOAJ_REFRESH_AFTER_DAYS: ConfigSetting(ConfigKind.DELAY, 30),
    ConfigKey.PIPELINE_START_YEAR_FULL: ConfigSetting(ConfigKind.YEAR),
}
assert set(SETTINGS) == set(ConfigKey)
assert all(s.default is not None for s in SETTINGS.values() if s.kind is not ConfigKind.YEAR)


def _keys_of(kind: ConfigKind) -> frozenset[str]:
    return frozenset(key.value for key, setting in SETTINGS.items() if setting.kind is kind)


CAP_KEYS = _keys_of(ConfigKind.CAP)
DELAY_KEYS = _keys_of(ConfigKind.DELAY)
YEAR_KEYS = _keys_of(ConfigKind.YEAR)


def cap_value(key: ConfigKey, stored: int | None) -> int | None:
    """Renvoie le plafond à appliquer pour `key` d'après la valeur stockée, `None` pour illimité. Une valeur absente donne le défaut ; zéro ou une valeur négative retire la borne."""
    value = SETTINGS[key].default if stored is None else stored
    assert value is not None
    return value if value > 0 else None


def delay_value(key: ConfigKey, stored: int | None) -> int:
    """Renvoie le délai à appliquer pour `key` d'après la valeur stockée, en jours. Une valeur absente ou inférieure à un jour donne le défaut."""
    default = SETTINGS[key].default
    assert default is not None
    return stored if stored is not None and stored >= 1 else default


PERIMETER_EXTRACTION_KEY = "perimeter_extraction"
"""Clé du code du périmètre moissonné."""

PERIMETER_PERSONS_KEY = "perimeter_persons"
"""Clé du code du périmètre de création des personnes."""

SITE_TITLE_KEY = "site_title"
"""Clé du titre de l'application. Pour un texte vide, l'interface compose le titre avec le nom de l'établissement."""

BRAND_HUE_KEY = "brand_hue"
"""Clé de la teinte de l'interface : angle OKLCH en degrés, entier de 0 à 359."""

DEFAULT_BRAND_HUE = 196
"""Teinte de l'interface quand la clé est absente."""

INSTITUTION_COUNTRY_KEY = "institution_country"
"""Clé du pays de l'établissement : code ISO 3166-1 en minuscules. Une publication co-affiliée à un autre pays est une collaboration internationale."""

DEFAULT_INSTITUTION_COUNTRY = "fr"
"""Pays de l'établissement quand la clé est absente."""

INSTITUTION_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        PERIMETER_EXTRACTION_KEY,
        PERIMETER_PERSONS_KEY,
        SITE_TITLE_KEY,
        BRAND_HUE_KEY,
        INSTITUTION_COUNTRY_KEY,
    }
)
"""Clés propres à l'établissement."""

INITIAL_START_YEAR = 2017
"""Première année moissonnée d'une installation."""

INITIAL_CONFIG_VALUES: dict[str, JsonValue] = {
    **{key.value: s.default for key, s in SETTINGS.items() if s.default is not None},
    ConfigKey.PIPELINE_START_YEAR_FULL.value: INITIAL_START_YEAR,
    LABORATORY_TYPES_KEY: [t.value for t in DEFAULT_LABORATORY_TYPES],
}
"""Valeur initiale de chaque clé commune à tous les établissements : sa valeur par défaut, et `INITIAL_START_YEAR` pour la première année moissonnée."""

MIN_YEAR = 1970
MAX_YEAR = 2100


def _as_int(value: JsonValue) -> int | None:
    """Renvoie l'entier contenu dans `value`, entier ou texte ; sinon `None`. Écarte les booléens, tenus pour des entiers par Python."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _site_title(key: str, value: JsonValue) -> JsonValue:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError(f"`{key}` attend un texte ; reçu : {value!r}")
    return value.strip()


def _brand_hue(key: str, value: JsonValue) -> JsonValue:
    teinte = _as_int(value)
    if teinte is None or not (0 <= teinte <= 359):
        raise ValidationError(f"`{key}` attend un entier de 0 à 359 ; reçu : {value!r}")
    return teinte


def _institution_country(key: str, value: JsonValue) -> JsonValue:
    code = normalize_country_code(value) if isinstance(value, str) else None
    if code is None or code == NO_COUNTRY_CODE:
        raise ValidationError(f"`{key}` attend un code pays à deux lettres ; reçu : {value!r}")
    return code


def _laboratory_types(key: str, value: JsonValue) -> JsonValue:
    """Renvoie les types sans doublon, dans l'ordre de `StructureType`."""
    if not isinstance(value, list) or not value:
        raise ValidationError(
            f"`{key}` attend une liste non vide de types de structure ; reçu : {value!r}"
        )
    inconnus = [v for v in value if v not in set(StructureType)]
    if inconnus:
        raise ValidationError(f"`{key}` : types de structure inconnus : {inconnus!r}")
    return [t.value for t in StructureType if t in value]


def _cap(key: str, value: JsonValue) -> JsonValue:
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0
    plafond = _as_int(value)
    if plafond is None or plafond < 0:
        raise ValidationError(f"`{key}` attend un entier positif ou nul ; reçu : {value!r}")
    return plafond


def _delay(key: str, value: JsonValue) -> JsonValue:
    delai = _as_int(value)
    if delai is None or delai < 1:
        raise ValidationError(
            f"`{key}` attend un nombre entier de jours, au moins 1 ; reçu : {value!r}"
        )
    return delai


def _year(key: str, value: JsonValue) -> JsonValue:
    annee = _as_int(value)
    if annee is None or not (MIN_YEAR <= annee <= MAX_YEAR):
        raise ValidationError(
            f"`{key}` attend une année entre {MIN_YEAR} et {MAX_YEAR} ; reçu : {value!r}"
        )
    return annee


_BY_KIND: dict[ConfigKind, Callable[[str, JsonValue], JsonValue]] = {
    ConfigKind.CAP: _cap,
    ConfigKind.DELAY: _delay,
    ConfigKind.YEAR: _year,
}

_NORMALIZERS: dict[str, Callable[[str, JsonValue], JsonValue]] = {
    SITE_TITLE_KEY: _site_title,
    BRAND_HUE_KEY: _brand_hue,
    INSTITUTION_COUNTRY_KEY: _institution_country,
    LABORATORY_TYPES_KEY: _laboratory_types,
    **{key.value: _BY_KIND[setting.kind] for key, setting in SETTINGS.items()},
}


def normalize_config_value(key: str, value: JsonValue) -> JsonValue:
    """Renvoie la valeur à écrire pour `key`, ramenée à la forme imposée par la clé.

    Une valeur absente ou vide vaut zéro pour un plafond, un texte vide pour le titre. Les clés sans forme imposée passent telles quelles.

    Raises:
        ValidationError: valeur hors de la forme imposée.
    """
    normalizer = _NORMALIZERS.get(key)
    return value if normalizer is None else normalizer(key, value)
