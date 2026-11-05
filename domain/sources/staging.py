"""Vocabulaire de la table `staging`."""

from enum import StrEnum


class StagingEntryMode(StrEnum):
    """Voie par laquelle une ligne de `staging` est entrée, valeur de `staging.entry_mode`. Posée à la création de la ligne, et fixe ensuite."""

    BULK = "bulk"
    """Moissonnage d'une source sur les affiliations du périmètre."""
    FETCH_MISSING_DOI = "fetch_missing_doi"
    """Recherche par DOI d'un document trouvé dans une autre source."""
    FETCH_MISSING_HAL_ID = "fetch_missing_hal_id"
    """Recherche par hal-id d'un document trouvé dans une autre source."""
    FETCH_MISSING_NNT = "fetch_missing_nnt"
    """Recherche par NNT d'une thèse trouvée dans une autre source."""
    FETCH_MISSING_PATENT_NUMBER = "fetch_missing_patent_number"
    """Recherche par numéro de publication ou de demande d'un brevet trouvé dans une autre source."""
    MANUAL_EXPORT = "manual_export"
    """Import d'un export de l'interface d'une source."""
    PERSON_IDENTIFIER = "person_identifier"
    """Interrogation d'une source par l'identifiant d'une personne."""
