"""Règles des paramètres applicatifs : forme imposée à chaque clé, valeur appliquée quand la clé est absente, portée."""

from collections.abc import Callable
from enum import StrEnum
from typing import NamedTuple

from domain.countries import NO_COUNTRY_CODE, normalize_country_code
from domain.errors import NotFoundError, ValidationError
from domain.structures.structure import StructureType
from domain.types import JsonValue


class ConfigKey(StrEnum):
    """Clé d'un paramètre applicatif."""

    PIPELINE_START_YEAR_FULL = "pipeline_start_year_full"
    """Première année moissonnée."""
    UNPAYWALL_MAX_PER_RUN = "unpaywall_max_per_run"
    """Nombre de DOI vérifiés auprès d'Unpaywall par run."""
    FETCH_MISSING_MAX_PER_SOURCE = "fetch_missing_max_per_source"
    """Nombre de DOI interrogés par source cible à la recherche par DOI (phase `fetch_missing`)."""
    SUDOC_MAX_PER_RUN = "sudoc_max_per_run"
    """Nombre d'ISSN vérifiés dans le Sudoc par run."""
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
    ISSNL_TABLE_REFRESH_AFTER_DAYS = "issnl_table_refresh_after_days"
    """Délai avant de télécharger de nouveau la table ISSN-L de l'ISSN International Centre."""
    LABORATORY_TYPES = "laboratory_types"
    """Types de structure traités comme laboratoires."""
    PERIMETER_EXTRACTION = "perimeter_extraction"
    """Code du périmètre moissonné."""
    PERIMETER_PERSONS = "perimeter_persons"
    """Code du périmètre de création des personnes."""
    SITE_TITLE = "site_title"
    """Titre de l'application. Pour un texte vide, l'interface compose le titre avec le nom de l'établissement."""
    BRAND_HUE = "brand_hue"
    """Teinte de l'interface : angle OKLCH en degrés, entier de 0 à 359."""
    INSTITUTION_COUNTRY = "institution_country"
    """Pays de l'établissement : code ISO 3166-1 en minuscules. Une publication co-affiliée à un autre pays est une collaboration internationale."""


DEFAULT_START_YEAR_OFFSET = 5
"""Sans première année fixée, la première année moissonnée précède l'année courante de ce nombre d'années."""


def _parse_int(value: JsonValue) -> int | None:
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


def _is_blank(value: JsonValue) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _bounded_int(key: str, value: JsonValue) -> JsonValue:
    """Entier compris dans les bornes de la clé (`ConfigSetting.bounds`)."""
    minimum, maximum = integer_bounds(ConfigKey(key))
    entier = _parse_int(value)
    if entier is None or not (minimum <= entier <= maximum):
        raise ValidationError(
            f"`{key}` attend un entier de {minimum} à {maximum} ; reçu : {value!r}"
        )
    return entier


def _year(key: str, value: JsonValue) -> JsonValue:
    """Année dans les bornes de la clé. Une valeur vide laisse l'année non fixée."""
    return None if _is_blank(value) else _bounded_int(key, value)


def _cap(key: str, value: JsonValue) -> JsonValue:
    """Plafond d'interrogations dans les bornes de la clé ; zéro pour illimité. Une valeur vide vaut zéro."""
    return 0 if _is_blank(value) else _bounded_int(key, value)


def _delay(key: str, value: JsonValue) -> JsonValue:
    """Délai de réinterrogation, en jours, dans les bornes de la clé."""
    return _bounded_int(key, value)


def _laboratory_types(key: str, value: JsonValue) -> JsonValue:
    """Liste non vide de types de structure, sans doublon, dans l'ordre de `StructureType`."""
    if not isinstance(value, list) or not value:
        raise ValidationError(
            f"`{key}` attend une liste non vide de types de structure ; reçu : {value!r}"
        )
    inconnus = [v for v in value if v not in set(StructureType)]
    if inconnus:
        raise ValidationError(f"`{key}` : types de structure inconnus : {inconnus!r}")
    return [t.value for t in StructureType if t in value]


def _site_title(key: str, value: JsonValue) -> JsonValue:
    """Texte sans les espaces qui l'entourent. Une valeur absente vaut un texte vide."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError(f"`{key}` attend un texte ; reçu : {value!r}")
    return value.strip()


def _institution_country(key: str, value: JsonValue) -> JsonValue:
    """Code pays à deux lettres, en minuscules."""
    code = normalize_country_code(value) if isinstance(value, str) else None
    if code is None or code == NO_COUNTRY_CODE:
        raise ValidationError(f"`{key}` attend un code pays à deux lettres ; reçu : {value!r}")
    return code


type Normalizer = Callable[[str, JsonValue], JsonValue]
"""Ramène une valeur écrite à la forme imposée par sa clé, ou lève `ValidationError`."""


class ConfigSetting(NamedTuple):
    """Règles d'une clé."""

    normalize: Normalizer | None
    """Forme imposée à la valeur. `None` : valeur libre."""
    default: JsonValue = None
    """Valeur initiale, posée par le seed. Une migration insère chaque clé."""
    institution: bool = False
    """Clé propre à l'établissement, posée par le seed d'établissement. Le seed commun pose les autres clés."""
    public: bool = False
    """Clé lisible sans session."""
    bounds: tuple[int, int] | None = None
    """Bornes incluses d'une clé entière."""


CAP_BOUNDS = (0, 10_000_000)
DELAY_BOUNDS = (1, 3650)

SETTINGS: dict[ConfigKey, ConfigSetting] = {
    ConfigKey.PIPELINE_START_YEAR_FULL: ConfigSetting(_year, bounds=(1970, 2100)),
    ConfigKey.UNPAYWALL_MAX_PER_RUN: ConfigSetting(_cap, 10_000, bounds=CAP_BOUNDS),
    ConfigKey.FETCH_MISSING_MAX_PER_SOURCE: ConfigSetting(_cap, 0, bounds=CAP_BOUNDS),
    ConfigKey.SUDOC_MAX_PER_RUN: ConfigSetting(_cap, 10_000, bounds=CAP_BOUNDS),
    ConfigKey.DOI_RESOLUTION_MAX_PER_RUN: ConfigSetting(_cap, 10_000, bounds=CAP_BOUNDS),
    ConfigKey.FETCH_STALE_AFTER_DAYS: ConfigSetting(_delay, 90, bounds=DELAY_BOUNDS),
    ConfigKey.FETCH_MISSING_RETRY_AFTER_DAYS: ConfigSetting(_delay, 30, bounds=DELAY_BOUNDS),
    ConfigKey.UNPAYWALL_RECHECK_AFTER_DAYS: ConfigSetting(_delay, 15, bounds=DELAY_BOUNDS),
    ConfigKey.DOI_RESOLUTION_RECHECK_AFTER_DAYS: ConfigSetting(_delay, 180, bounds=DELAY_BOUNDS),
    ConfigKey.DOAJ_REFRESH_AFTER_DAYS: ConfigSetting(_delay, 30, bounds=DELAY_BOUNDS),
    ConfigKey.ISSNL_TABLE_REFRESH_AFTER_DAYS: ConfigSetting(_delay, 30, bounds=DELAY_BOUNDS),
    ConfigKey.LABORATORY_TYPES: ConfigSetting(
        _laboratory_types, [StructureType.LABO.value], public=True
    ),
    ConfigKey.PERIMETER_EXTRACTION: ConfigSetting(None, institution=True),
    ConfigKey.PERIMETER_PERSONS: ConfigSetting(None, institution=True),
    ConfigKey.SITE_TITLE: ConfigSetting(_site_title, "", institution=True),
    ConfigKey.BRAND_HUE: ConfigSetting(_bounded_int, 196, institution=True, bounds=(0, 359)),
    ConfigKey.INSTITUTION_COUNTRY: ConfigSetting(_institution_country, "fr", institution=True),
}
assert set(SETTINGS) == set(ConfigKey)


def integer_bounds(key: ConfigKey) -> tuple[int, int]:
    """Renvoie les bornes incluses de la clé entière `key`."""
    bounds = SETTINGS[key].bounds
    assert bounds is not None, key
    return bounds


def _keys_normalized_by(normalize: Normalizer) -> frozenset[str]:
    return frozenset(key.value for key, s in SETTINGS.items() if s.normalize is normalize)


CAP_KEYS = _keys_normalized_by(_cap)
"""Clés des plafonds d'interrogations."""

DELAY_KEYS = _keys_normalized_by(_delay)
"""Clés des délais de réinterrogation."""

PUBLIC_CONFIG_KEYS = frozenset(key.value for key, s in SETTINGS.items() if s.public)
"""Clés lisibles sans session."""

INSTITUTION_CONFIG_KEYS = frozenset(key.value for key, s in SETTINGS.items() if s.institution)
"""Clés propres à l'établissement."""

PERIMETER_CONFIG_KEYS = frozenset({ConfigKey.PERIMETER_EXTRACTION, ConfigKey.PERIMETER_PERSONS})
"""Clés dont la valeur est le code d'un périmètre."""

INITIAL_CONFIG_VALUES: dict[str, JsonValue] = {
    key.value: s.default for key, s in SETTINGS.items() if not s.institution
}
"""Valeur initiale de chaque clé commune à tous les établissements."""


def start_year_value(stored: int | None, current_year: int) -> int:
    """Renvoie la première année moissonnée d'après la valeur stockée. Sans année fixée, elle précède l'année courante de `DEFAULT_START_YEAR_OFFSET` ans."""
    return current_year - DEFAULT_START_YEAR_OFFSET if stored is None else stored


def normalize_config_value(key: str, value: JsonValue) -> JsonValue:
    """Renvoie la valeur à écrire pour `key`, ramenée à la forme imposée par la clé. Une clé sans forme imposée passe telle quelle.

    Raises:
        NotFoundError: clé inconnue.
        ValidationError: valeur hors de la forme imposée.
    """
    if key not in ConfigKey:
        raise NotFoundError(f"Paramètre '{key}' introuvable")
    normalize = SETTINGS[ConfigKey(key)].normalize
    return value if normalize is None else normalize(key, value)
