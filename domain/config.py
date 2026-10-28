"""Règles des paramètres applicatifs.

La table `config` porte les réglages d'exploitation du pipeline : périmètres, années couvertes, plafonds d'interrogation, délais de réinterrogation, types de structure affichés. Une part est consommée par les pages publiques, le reste est réservé à une session d'administration.

Chaque clé dont la valeur a une forme imposée la voit contrôlée à l'écriture : un plafond attend un entier positif ou nul, un délai un nombre entier de jours d'au moins un, une année doit tomber dans les bornes.
"""

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
    """Nombre de DOI interrogés par source cible à l'import par DOI."""
    SUDOC_MAX_PER_RUN = "sudoc_max_per_run"
    """Nombre de revues vérifiées dans le Sudoc par run."""
    FETCH_STALE_AFTER_DAYS = "fetch_stale_after_days"
    """Âge au-delà duquel un document moissonné est interrogé de nouveau à sa source."""
    FETCH_MISSING_RETRY_AFTER_DAYS = "fetch_missing_retry_after_days"
    """Délai avant de chercher de nouveau un identifiant resté introuvable dans une source. L'échec est définitif pour un identifiant absent de son registre (`REGISTRY_LOOKUPS`)."""
    UNPAYWALL_RECHECK_AFTER_DAYS = "unpaywall_recheck_after_days"
    """Délai avant de vérifier de nouveau le statut open access d'une publication auprès d'Unpaywall."""
    DOAJ_REFRESH_AFTER_DAYS = "doaj_refresh_after_days"
    """Délai avant de télécharger de nouveau le fichier du DOAJ."""
    PIPELINE_START_YEAR_FULL = "pipeline_start_year_full"
    """Première année moissonnée."""


class ConfigKind(StrEnum):
    """Forme d'un réglage numérique."""

    CAP = "cap"
    """Plafond d'interrogations, entier positif ; zéro retire la borne."""
    DELAY = "delay"
    """Délai de réinterrogation, en nombre entier de jours, au moins un."""
    YEAR = "year"
    """Année, entre `MIN_YEAR` et `MAX_YEAR`."""


class ConfigSetting(NamedTuple):
    """Forme d'un réglage, et valeur retenue quand la clé est absente ou illisible ; pour un plafond, `None` vaut illimité."""

    kind: ConfigKind
    default: int | None = None


SETTINGS: dict[ConfigKey, ConfigSetting] = {
    ConfigKey.UNPAYWALL_MAX_PER_RUN: ConfigSetting(ConfigKind.CAP, 10_000),
    ConfigKey.FETCH_MISSING_MAX_PER_SOURCE: ConfigSetting(ConfigKind.CAP),
    ConfigKey.SUDOC_MAX_PER_RUN: ConfigSetting(ConfigKind.CAP, 10_000),
    ConfigKey.FETCH_STALE_AFTER_DAYS: ConfigSetting(ConfigKind.DELAY, 90),
    ConfigKey.FETCH_MISSING_RETRY_AFTER_DAYS: ConfigSetting(ConfigKind.DELAY, 30),
    ConfigKey.UNPAYWALL_RECHECK_AFTER_DAYS: ConfigSetting(ConfigKind.DELAY, 15),
    ConfigKey.DOAJ_REFRESH_AFTER_DAYS: ConfigSetting(ConfigKind.DELAY, 30),
    ConfigKey.PIPELINE_START_YEAR_FULL: ConfigSetting(ConfigKind.YEAR),
}
assert set(SETTINGS) == set(ConfigKey)
assert all(s.default is not None for s in SETTINGS.values() if s.kind is ConfigKind.DELAY)


def _keys_of(kind: ConfigKind) -> frozenset[str]:
    return frozenset(key.value for key, setting in SETTINGS.items() if setting.kind is kind)


CAP_KEYS = _keys_of(ConfigKind.CAP)
DELAY_KEYS = _keys_of(ConfigKind.DELAY)
YEAR_KEYS = _keys_of(ConfigKind.YEAR)


def cap_value(key: ConfigKey, stored: int | None) -> int | None:
    """Plafond effectif de `key`, `None` valant illimité : zéro ou une valeur négative retire la borne ; une valeur absente donne la valeur par défaut."""
    if stored is None:
        return SETTINGS[key].default
    return stored if stored > 0 else None


def delay_value(key: ConfigKey, stored: int | None) -> int:
    """Délai effectif de `key`, en jours : la valeur par défaut pour une valeur absente ou inférieure à un jour."""
    default = SETTINGS[key].default
    assert default is not None
    return stored if stored is not None and stored >= 1 else default


PERIMETER_EXTRACTION_KEY = "perimeter_extraction"
"""Clé du code du périmètre dont les structures sont interrogées à l'extraction."""

PERIMETER_PERSONS_KEY = "perimeter_persons"
"""Clé du code du périmètre de création des personnes."""

INSTITUTION_CONFIG_KEYS: frozenset[str] = frozenset(
    {PERIMETER_EXTRACTION_KEY, PERIMETER_PERSONS_KEY}
)
"""Clés propres à l'établissement : elles désignent des périmètres de l'établissement."""

MIN_YEAR = 1970
MAX_YEAR = 2100


def _as_int(value: JsonValue) -> int | None:
    """Entier porté par `value`, ou `None`. Un booléen est écarté, Python le tenant pour un entier."""
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

    Un plafond attend un entier positif ou nul, zéro retirant la borne ; une valeur absente ou vide y vaut zéro. Un délai attend un nombre entier de jours, au moins un. Une année doit tomber dans les bornes. Toute autre valeur est refusée, aucune valeur de repli n'ayant de sens.

    Les autres clés passent telles quelles.
    """
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
