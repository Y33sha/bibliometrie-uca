"""Moissonnage des sources par l'identifiant d'une personne : statuts des identifiants interrogés. Les identifiants que chaque source sait chercher sont dans son profil (`domain.sources.registry`)."""

from domain.persons.identifiers import AttributionStatus

# Statuts d'un identifiant de personne RH qui la font interroger.
SEARCHED_IDENTIFIER_STATUSES: frozenset[AttributionStatus] = frozenset(
    {AttributionStatus.CONFIRMED, AttributionStatus.AUTHENTICATED}
)
