"""Statut open access d'une publication, déduit des accès constatés sur ses copies, du modèle de sa revue et du verdict d'Unpaywall.

1. Copie ouverte chez l'éditeur, sous licence ouverte : le modèle de la revue décide. `subscription` ou inconnu donne `hybrid`, `full_oa` donne `gold`, `diamond` donne `diamond`. Sans revue, `gold`.
2. Sinon, copie d'archive ou de serveur de preprints ouverte : `green`.
3. Sinon, copie ouverte chez l'éditeur sans licence ouverte : `bronze`.
4. Sinon : `embargoed` sous embargo, `closed` avec une information sur la publication, `unknown` sans aucune.

Le verdict d'Unpaywall relève les accès, jamais ne les abaisse.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace

from domain.platforms.platform import PlatformType
from domain.publications.access import Copy, open_copies
from domain.publications.licenses import OPEN_LICENSES
from domain.publications.metadata import OaStatus
from domain.serials.serial import OaModel

_ARCHIVE_TYPES = frozenset({PlatformType.REPOSITORY, PlatformType.PREPRINT_SERVER})


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenAccessFacts:
    """Accès constatés à une publication."""

    publisher_open: bool = False
    """Une copie est ouverte chez l'éditeur : toute copie ouverte hors archive et hors serveur de preprints."""
    publisher_licensed: bool = False
    """Une copie ouverte chez l'éditeur a une licence ouverte (`OPEN_LICENSES`)."""
    archive_open: bool = False
    embargoed: bool = False
    """Une copie est sous embargo actif, ou theses.fr déclare un embargo."""
    informed: bool = False
    """La publication a une copie, un verdict d'Unpaywall ou un statut `closed` déclaré par une source."""

    def raised_by(self, unpaywall: str | None) -> OpenAccessFacts:
        """Renvoie les accès relevés par le verdict d'Unpaywall : `gold`, `hybrid` ou `diamond` valent une copie ouverte chez l'éditeur sous licence, `bronze` sans licence, `green` une copie d'archive ouverte."""
        if unpaywall is None:
            return self
        raised = replace(self, informed=True)
        if unpaywall in (OaStatus.GOLD, OaStatus.HYBRID, OaStatus.DIAMOND):
            return replace(raised, publisher_open=True, publisher_licensed=True)
        if unpaywall == OaStatus.BRONZE:
            return replace(raised, publisher_open=True)
        if unpaywall == OaStatus.GREEN:
            return replace(raised, archive_open=True)
        return raised


def copies_facts(copies: Iterable[Copy]) -> OpenAccessFacts:
    """Renvoie les accès constatés sur les copies d'une publication (`open_copies`). Une copie, même fermée, informe sur la publication."""
    copies = list(copies)
    opened = open_copies(copies)
    publisher = [c for c in opened if c.platform_type not in _ARCHIVE_TYPES]
    return OpenAccessFacts(
        publisher_open=bool(publisher),
        publisher_licensed=any(c.license in OPEN_LICENSES for c in publisher),
        archive_open=any(c.platform_type in _ARCHIVE_TYPES for c in opened),
        informed=bool(copies),
    )


def decide_oa_status(
    facts: OpenAccessFacts, *, has_serial: bool, serial_oa_model: str | None
) -> OaStatus:
    """Renvoie le statut open access d'une publication.

    Args:
        has_serial: la publication est rattachée à une revue.
        serial_oa_model: modèle open access de cette revue (`OaModel`), `None` s'il est inconnu.
    """
    if facts.publisher_open and facts.publisher_licensed:
        if not has_serial or serial_oa_model == OaModel.FULL_OA:
            return OaStatus.GOLD
        if serial_oa_model == OaModel.DIAMOND:
            return OaStatus.DIAMOND
        return OaStatus.HYBRID
    if facts.archive_open:
        return OaStatus.GREEN
    if facts.publisher_open:
        return OaStatus.BRONZE
    if facts.embargoed:
        return OaStatus.EMBARGOED
    if facts.informed:
        return OaStatus.CLOSED
    return OaStatus.UNKNOWN
