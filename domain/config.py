"""Règles des paramètres applicatifs.

La table `config` porte les réglages d'exploitation du pipeline : périmètres, années couvertes, plafonds d'interrogation, types de structure affichés. Une part est consommée par les pages publiques, le reste est réservé à une session d'administration.

Chaque clé dont la valeur a une forme imposée la voit contrôlée à l'écriture : un plafond se ramène à un entier positif ou à zéro, une année doit tomber dans les bornes.
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

YEAR_KEYS: frozenset[str] = frozenset({"pipeline_start_year_full"})
"""Clés portant une année."""

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

    Un plafond se ramène à un entier positif ; toute autre valeur y vaut zéro, qui retire la borne. Une année hors des bornes, ou qui n'en est pas une, est refusée : aucune valeur de repli n'y a de sens.

    Les autres clés passent telles quelles.
    """
    if key in CAP_KEYS:
        plafond = _as_int(value)
        return plafond if plafond is not None and plafond > 0 else 0
    if key in YEAR_KEYS:
        annee = _as_int(value)
        if annee is None or not (MIN_YEAR <= annee <= MAX_YEAR):
            raise ValidationError(
                f"`{key}` attend une année entre {MIN_YEAR} et {MAX_YEAR} ; reçu : {value!r}"
            )
        return annee
    return value
