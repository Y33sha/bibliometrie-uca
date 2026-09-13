"""Règles des paramètres applicatifs.

La table `config` porte les réglages d'exploitation du pipeline : périmètres, années couvertes, plafonds d'interrogation, délais de réinterrogation, types de structure affichés. Une part est consommée par les pages publiques, le reste est réservé à une session d'administration.

Chaque clé dont la valeur a une forme imposée la voit contrôlée à l'écriture : un plafond attend un entier positif ou nul, un délai un nombre entier de jours d'au moins un, une année doit tomber dans les bornes.
"""

from domain.errors import ValidationError
from domain.types import JsonValue

# Clés de configuration consommées par une page publique
PUBLIC_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        # Types de structure affichés par la page des laboratoires.
        "laboratories_display_types",
    }
)

CAP_KEYS: frozenset[str] = frozenset(
    {
        # Nombre de DOI vérifiés auprès d'Unpaywall par run.
        "unpaywall_max_per_run",
        # Nombre de DOI interrogés par source cible à l'import par DOI.
        "fetch_missing_max_per_source",
    }
)
"""Plafonds d'interrogation, exprimés en entiers positifs. Zéro retire la borne."""

DELAY_KEYS: frozenset[str] = frozenset(
    {
        # Âge au-delà duquel un document moissonné est interrogé de nouveau à sa source.
        "fetch_stale_after_days",
        # Délai avant de chercher de nouveau un identifiant resté introuvable dans une source. La recherche d'un identifiant natif de la source est définitive.
        "fetch_missing_retry_after_days",
        # Délai avant de vérifier de nouveau le statut open access d'une publication auprès d'Unpaywall.
        "unpaywall_recheck_after_days",
        # Délai avant de télécharger de nouveau le fichier du DOAJ.
        "doaj_refresh_after_days",
    }
)
"""Délais de réinterrogation des sources, exprimés en nombres entiers de jours, au moins un."""

YEAR_KEYS: frozenset[str] = frozenset({"pipeline_start_year_full"})
"""Clés portant une année."""

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
