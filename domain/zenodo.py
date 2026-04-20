"""Format des DOI Zenodo (partie pure, sans I/O)."""

import re

ZENODO_DOI_RE = re.compile(r"10\.5281/zenodo\.(\d+)", re.IGNORECASE)


def is_zenodo_doi(doi: str | None) -> bool:
    """Vérifie si un DOI est un DOI Zenodo."""
    return bool(doi and ZENODO_DOI_RE.search(doi))
