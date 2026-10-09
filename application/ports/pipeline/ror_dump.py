"""Port : versions publiées du dump ROR et lecture de leurs organisations.

Implémenté par `infrastructure.sources.ror.dump.ZenodoRorDumpSource`.
"""

from collections.abc import Iterator
from typing import Protocol

from domain.structures.ror import RorOrganization


class RorDumpUnavailableError(Exception):
    """Le dump ROR est inaccessible : échec du réseau, du serveur, ou réponse inattendue."""


class RorDumpSource(Protocol):
    def latest_version(self) -> str:
        """Nom de l'archive de la version la plus récente. Lève `RorDumpUnavailableError`."""
        ...

    def organizations(self, version: str) -> Iterator[RorOrganization]:
        """Organisations de l'archive `version`, téléchargée le temps de la lecture. Lève `RorDumpUnavailableError`."""
        ...
