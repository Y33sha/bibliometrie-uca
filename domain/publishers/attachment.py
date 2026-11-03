"""Rattachement des enregistrements sources à leur éditeur, calculé sur tous les enregistrements sources qui nomment un éditeur.

Chaque identifiant OpenAlex rejoint son éditeur, à défaut l'éditeur le plus fréquent parmi les formes de nom de ses enregistrements sources, à défaut un éditeur créé. Les formes de nom libres portées par ses enregistrements sources lui reviennent. Un enregistrement source sans identifiant OpenAlex rejoint l'éditeur de sa forme de nom ; chaque forme restée libre crée un éditeur. Une forme attribuée garde son éditeur. À égalité, le plus grand nombre d'enregistrements sources départage, puis la plus petite valeur. Le résultat est indépendant de l'ordre des enregistrements sources.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import NamedTuple

from domain.publishers.names import publisher_name_key
from domain.serials.attachment import most_frequent


class PublisherRecord(NamedTuple):
    """Enregistrement source qui nomme son éditeur."""

    id: int
    name: str
    openalex_id: str | None


@dataclass(frozen=True)
class NewPublisher:
    """Éditeur à créer, désigné par l'identifiant OpenAlex ou la forme de nom qui le fonde."""

    key: str
    name: str
    openalex_id: str | None = None


type PublisherRef = int | NewPublisher
"""Éditeur existant, par identifiant, ou éditeur à créer."""


@dataclass
class PublisherAttachment:
    """Éditeur de chaque enregistrement source, avec les écritures du référentiel qui en découlent."""

    publisher_of: dict[int, PublisherRef] = field(default_factory=dict)
    """Éditeur de chaque enregistrement source rattaché."""
    new_forms: dict[str, PublisherRef] = field(default_factory=dict)
    """Formes de nom libres et leur éditeur."""
    openalex_ids: dict[int, str] = field(default_factory=dict)
    """Identifiant OpenAlex attribué à un éditeur existant qui n'en a pas."""


type _FormedRecord = tuple[PublisherRecord, str]
"""Enregistrement source et forme de nom de son éditeur."""


def attach_publishers(
    records: Iterable[PublisherRecord],
    publisher_of_openalex_id: Mapping[str, int],
    publisher_of_form: Mapping[str, int],
) -> PublisherAttachment:
    """Renvoie l'éditeur de chaque enregistrement source de `records`. Un enregistrement source au nom sans forme reste sans éditeur."""
    by_openalex: dict[str, list[_FormedRecord]] = defaultdict(list)
    by_form: dict[str, list[PublisherRecord]] = defaultdict(list)
    for record in records:
        form = publisher_name_key(record.name)
        if record.openalex_id:
            by_openalex[record.openalex_id].append((record, form))
        elif form:
            by_form[form].append(record)

    result = PublisherAttachment()
    publisher_of_id = _publishers_of_openalex_ids(
        by_openalex, publisher_of_openalex_id, publisher_of_form, result
    )
    for form, openalex_id in _free_forms(by_openalex, publisher_of_form).items():
        result.new_forms[form] = publisher_of_id[openalex_id]
    for openalex_id, members in by_openalex.items():
        for record, _ in members:
            result.publisher_of[record.id] = publisher_of_id[openalex_id]

    # Enregistrements sources sans identifiant OpenAlex, par forme ; une forme libre crée un éditeur.
    for form in sorted(by_form):
        members = by_form[form]
        publisher = (
            publisher_of_form[form] if form in publisher_of_form else result.new_forms.get(form)
        )
        if publisher is None:
            publisher = NewPublisher(
                f"form:{form}", most_frequent(Counter(r.name for r in members))
            )
            result.new_forms[form] = publisher
        for record in members:
            result.publisher_of[record.id] = publisher
    return result


def _publishers_of_openalex_ids(
    by_openalex: Mapping[str, list[_FormedRecord]],
    publisher_of_openalex_id: Mapping[str, int],
    publisher_of_form: Mapping[str, int],
    result: PublisherAttachment,
) -> dict[str, PublisherRef]:
    """Renvoie l'éditeur de chaque identifiant OpenAlex, et range dans `result` l'identifiant attribué à un éditeur existant qui n'en a pas."""
    with_openalex_id = set(publisher_of_openalex_id.values())
    publisher_of_id: dict[str, PublisherRef] = {}
    claims: dict[int, Counter[str]] = defaultdict(Counter)
    for openalex_id, members in by_openalex.items():
        if openalex_id in publisher_of_openalex_id:
            publisher_of_id[openalex_id] = publisher_of_openalex_id[openalex_id]
            continue
        known = Counter(publisher_of_form[f] for _, f in members if f in publisher_of_form)
        if not known:
            name = most_frequent(Counter(r.name for r, _ in members))
            publisher_of_id[openalex_id] = NewPublisher(
                f"openalex:{openalex_id}", name, openalex_id
            )
            continue
        publisher_id = most_frequent(known)
        publisher_of_id[openalex_id] = publisher_id
        if publisher_id not in with_openalex_id:
            claims[publisher_id][openalex_id] = len(members)
    for publisher_id, candidates in claims.items():
        result.openalex_ids[publisher_id] = most_frequent(candidates)
    return publisher_of_id


def _free_forms(
    by_openalex: Mapping[str, list[_FormedRecord]], publisher_of_form: Mapping[str, int]
) -> dict[str, str]:
    """Renvoie l'identifiant OpenAlex qui reçoit chaque forme libre : celui qui la porte le plus."""
    claims: dict[str, Counter[str]] = defaultdict(Counter)
    for openalex_id, members in by_openalex.items():
        for _, form in members:
            if form and form not in publisher_of_form:
                claims[form][openalex_id] += 1
    return {form: most_frequent(candidates) for form, candidates in claims.items()}
