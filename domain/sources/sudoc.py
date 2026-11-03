"""Notice Sudoc d'une publication en série.

Une notice décrit une publication sur un support : l'ISSN papier, l'ISSN en ligne et l'ISSN d'un CD-ROM d'une même revue ont chacun leur notice.
"""

from dataclasses import dataclass

from domain.serials.issns import IssnSupport


@dataclass(frozen=True, slots=True)
class SudocSerialRecord:
    """Notice Sudoc d'une publication en série, réduite aux zones lues. Les ISSN sont normalisés ; une valeur invalide est ignorée."""

    ppn: str
    issn: str | None
    cancelled_issns: tuple[str, ...]
    support: IssnSupport | None
    other_support_issns: tuple[str, ...]
    title: str | None
    continues: tuple[str, ...] = ()
    """ISSN du titre précédent (`430`)."""
    continued_by: tuple[str, ...] = ()
    """ISSN du titre suivant (`440`)."""
    supplements: tuple[str, ...] = ()
    """ISSN du supplément (`421`)."""
    supplement_of: tuple[str, ...] = ()
    """ISSN de la revue principale (`422`)."""
