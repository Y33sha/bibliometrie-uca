"""Port : empreinte de détection de changement d'une valeur JSON.

Implémenté par `infrastructure.fingerprint.fingerprint`.
"""

from typing import Protocol

from domain.types import JsonValue


class Fingerprinter(Protocol):
    """Rend l'empreinte d'une valeur JSON : deux valeurs égales ont la même empreinte."""

    def __call__(self, value: JsonValue, /) -> str: ...
