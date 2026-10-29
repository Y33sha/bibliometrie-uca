"""Règles des paramètres applicatifs : forme imposée à chaque clé, valeur appliquée quand la clé est absente."""

from enum import StrEnum
from typing import NamedTuple

from domain.errors import ValidationError
from domain.types import JsonValue

# Clés de configuration consommées par une page publique
PUBLIC_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        # Types de structure affichés par la page des laboratoires.
        "laboratories_display_types",
    }
)


class ConfigKey(StrEnum):
    """Clé d'un réglage numérique du pipeline."""

    UNPAYWALL_MAX_PER_RUN = "unpaywall_max_per_run"
    """Nombre de DOI vérifiés auprès d'Unpaywall par run."""
    FETCH_MISSING_MAX_PER_SOURCE = "fetch_missing_max_per_source"
    """Nombre de DOI interrogés par source cible à la recherche par DOI (phase `fetch_missing`)."""
    SUDOC_MAX_PER_RUN = "sudoc_max_per_run"
    """Nombre de revues vérifiées dans le Sudoc par run."""
    FETCH_STALE_AFTER_DAYS = "fetch_stale_after_days"
    """Âge au-delà duquel un enregistrement source est interrogé de nouveau à sa source."""
    FETCH_MISSING_RETRY_AFTER_DAYS = "fetch_missing_retry_after_days"
    """Délai avant de chercher de nouveau un identifiant resté introuvable dans une source."""
    UNPAYWALL_RECHECK_AFTER_DAYS = "unpaywall_recheck_after_days"
    """Délai avant de vérifier de nouveau le statut open access d'une publication auprès d'Unpaywall."""
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
    ConfigKey.FETCH_STALE_AFTER_DAYS: ConfigSetting(ConfigKind.DELAY, 90),
    ConfigKey.FETCH_MISSING_RETRY_AFTER_DAYS: ConfigSetting(ConfigKind.DELAY, 30),
    ConfigKey.UNPAYWALL_RECHECK_AFTER_DAYS: ConfigSetting(ConfigKind.DELAY, 15),
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
    """Plafond à appliquer pour `key` d'après la valeur stockée, `None` pour illimité. Une valeur absente donne le défaut ; zéro ou une valeur négative retire la borne."""
    value = SETTINGS[key].default if stored is None else stored
    assert value is not None
    return value if value > 0 else None


def delay_value(key: ConfigKey, stored: int | None) -> int:
    """Délai à appliquer pour `key` d'après la valeur stockée, en jours. Une valeur absente ou inférieure à un jour donne le défaut."""
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

INSTITUTION_CONFIG_KEYS: frozenset[str] = frozenset(
    {PERIMETER_EXTRACTION_KEY, PERIMETER_PERSONS_KEY, SITE_TITLE_KEY, BRAND_HUE_KEY}
)
"""Clés propres à l'établissement."""

MIN_YEAR = 1970
MAX_YEAR = 2100


def _as_int(value: JsonValue) -> int | None:
    """Entier contenu dans `value`, entier ou texte ; sinon `None`. Écarte les booléens, que Python tient pour des entiers."""
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


def normalize_config_value(key: str, value: JsonValue) -> JsonValue:
    """Valeur à écrire pour `key`, ramenée à la forme que la clé impose.

    Lève `ValidationError` pour une valeur hors de cette forme. Une valeur absente ou vide vaut zéro pour un plafond, un texte vide pour le titre. Les clés sans forme imposée passent telles quelles.
    """
    if key == SITE_TITLE_KEY:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValidationError(f"`{key}` attend un texte ; reçu : {value!r}")
        return value.strip()
    if key == BRAND_HUE_KEY:
        teinte = _as_int(value)
        if teinte is None or not (0 <= teinte <= 359):
            raise ValidationError(f"`{key}` attend un entier de 0 à 359 ; reçu : {value!r}")
        return teinte
    if key in CAP_KEYS:
        if value is None or (isinstance(value, str) and not value.strip()):
            return 0
        plafond = _as_int(value)
        if plafond is None or plafond < 0:
            raise ValidationError(f"`{key}` attend un entier positif ou nul ; reçu : {value!r}")
        return plafond
    if key in DELAY_KEYS:
        delai = _as_int(value)
        if delai is None or delai < 1:
            raise ValidationError(
                f"`{key}` attend un nombre entier de jours, au moins 1 ; reçu : {value!r}"
            )
        return delai
    if key in YEAR_KEYS:
        annee = _as_int(value)
        if annee is None or not (MIN_YEAR <= annee <= MAX_YEAR):
            raise ValidationError(
                f"`{key}` attend une année entre {MIN_YEAR} et {MAX_YEAR} ; reçu : {value!r}"
            )
        return annee
    return value
