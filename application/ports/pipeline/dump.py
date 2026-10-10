"""Erreur commune aux dumps de référentiels téléchargés par le pipeline (ROR, DOAJ)."""


class DumpUnavailableError(Exception):
    """Un dump est inaccessible : échec du réseau, du serveur, ou réponse inattendue."""
