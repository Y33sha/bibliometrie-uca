"""Espaces de noms DOI des revues : le segment d'un DOI qui désigne sa revue.

Un espace de noms est un préfixe de DOI coupé à une frontière de segment : `10.1016/j.physletb.`, `10.1038/s41598-`, `10.3390/nu`. Une revue en a souvent plusieurs, au fil des changements de convention, de plateforme ou d'éditeur.

Un dépôt, un serveur de preprints, une plateforme de livres ou une collection de livres n'est désigné par aucun espace de noms : leur préfixe désigne la plateforme, et la suite du DOI désigne le document.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping
from typing import NamedTuple

from domain.journals.journal import JournalType

_SEPARATORS = frozenset("./-_(")
_PLATFORM_TYPES = frozenset(
    {
        JournalType.REPOSITORY,
        JournalType.PREPRINT_SERVER,
        JournalType.EBOOK_PLATFORM,
        JournalType.BOOK_SERIES,
    }
)
# DOI construit sur un ISBN : il désigne une monographie, pas une revue.
_ISBN_SUFFIX = re.compile(r"97[89][-\d]")
# Tiret interne d'un ISSN (`1748-0221`, `s0273-0979`) : l'ISSN reste d'un seul tenant.
_ISSN_HYPHEN = re.compile(r"(?<!\d)\d{4}(?=-\d{3}[\dx](?!\d))")


def _kind(char: str) -> str:
    return "lettre" if char.isalpha() else "chiffre" if char.isdigit() else "autre"


def namespace_candidates(doi: str) -> list[str]:
    """Préfixes de `doi` coupés à une frontière de segment, du plus court au plus long.

    Une frontière suit un séparateur, qui reste dans le préfixe (`10.1016/j.ins.` écarte `j.insmatheco`), ou sépare des lettres de chiffres (`10.3390/nu`, puis un chiffre). Un ISSN n'est pas coupé à son tiret (`10.1088/1748-0221/`). Le préfixe du déposant seul (`10.1016/`) n'en est pas un : un éditeur publie plusieurs revues. Un DOI construit sur un ISBN n'a aucun candidat.
    """
    registrant, slash, suffix = doi.partition("/")
    if not slash or not suffix or _ISBN_SUFFIX.match(suffix):
        return []
    base = f"{registrant}/"
    candidates = []
    issn_hyphens = {m.end() for m in _ISSN_HYPHEN.finditer(suffix)}
    for i, char in enumerate(suffix[:-1]):
        following = suffix[i + 1]
        if i in issn_hyphens:
            continue
        if char in _SEPARATORS or (
            _kind(char) != _kind(following) and "autre" not in (_kind(char), _kind(following))
        ):
            candidates.append(base + suffix[: i + 1])
    return candidates


class DoiNamespace(NamedTuple):
    """Un espace de noms retenu : la revue qu'il désigne, les DOI qui l'attestent et la part d'entre eux qui porte cette revue."""

    namespace: str
    journal_id: int
    dois: int
    share: float


def designated_by_namespace(journal_type: JournalType) -> bool:
    """Vrai si un espace de noms DOI peut désigner une revue de ce type."""
    return journal_type not in _PLATFORM_TYPES


def learn_namespaces(
    evidence: Iterable[tuple[str, int]],
    *,
    platforms: Collection[int] = (),
    min_dois: int = 5,
    min_share: float = 0.9,
) -> dict[str, DoiNamespace]:
    """Espaces de noms que désignent les couples `(DOI, revue)` des enregistrements, un couple par enregistrement.

    Chaque DOI donne une voix, répartie entre ses revues au prorata de ses enregistrements. Un espace est retenu s'il couvre au moins `min_dois` DOI distincts et qu'une revue hors de `platforms` y recueille au moins `min_share` des voix. Les DOI des revues de `platforms` comptent dans le total. Un espace est écarté quand un espace plus court, retenu, désigne déjà la même revue.
    """
    records_by_doi: dict[str, Counter[int]] = defaultdict(Counter)
    for doi, journal_id in evidence:
        records_by_doi[doi][journal_id] += 1
    dois_by_namespace: Counter[str] = Counter()
    votes: dict[str, defaultdict[int, float]] = defaultdict(lambda: defaultdict(float))
    for doi, records in records_by_doi.items():
        total_records = records.total()
        for namespace in namespace_candidates(doi):
            dois_by_namespace[namespace] += 1
            for journal_id, n in records.items():
                votes[namespace][journal_id] += n / total_records
    retained: dict[str, DoiNamespace] = {}
    for namespace in sorted(dois_by_namespace, key=len):
        total = dois_by_namespace[namespace]
        if total < min_dois:
            continue
        journal_id, count = max(votes[namespace].items(), key=lambda vote: vote[1])
        if count / total < min_share or journal_id in platforms:
            continue
        shorter = _longest_retained(namespace, retained)
        if shorter is not None and shorter.journal_id == journal_id:
            continue
        retained[namespace] = DoiNamespace(namespace, journal_id, total, count / total)
    return retained


def _longest_retained(namespace: str, retained: Mapping[str, DoiNamespace]) -> DoiNamespace | None:
    """L'espace retenu le plus long parmi les préfixes plus courts de `namespace`."""
    for shorter in reversed(namespace_candidates(namespace)):
        if shorter != namespace and shorter in retained:
            return retained[shorter]
    return None


def resolve_journal(doi: str, namespaces: Mapping[str, DoiNamespace]) -> DoiNamespace | None:
    """L'espace de noms retenu le plus long parmi les préfixes de `doi`, ou `None`."""
    for candidate in reversed(namespace_candidates(doi)):
        if candidate in namespaces:
            return namespaces[candidate]
    return None
