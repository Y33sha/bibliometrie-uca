"""Aggregate root `Monograph` : un livre ou un volume d'actes qui contient des publications de la base."""

from dataclasses import dataclass


@dataclass(slots=True)
class Monograph:
    """Livre ou volume d'actes. `journal_id` est la collection dont il fait partie."""

    id: int | None
    title: str
    proceedings: bool = False
    year: int | None = None
    isbn: str | None = None
    eisbn: str | None = None
    publisher_id: int | None = None
    journal_id: int | None = None
