"""Événements d'audit écartés hors requête d'administration."""

from application.audit_log import discarded_events, emit_event, get_current_user


def test_discarded_events_hors_requete():
    """Hors requête d'administration, le bloc s'exécute et rien n'est consigné."""
    with discarded_events():
        emit_event("a.b", "person", 1)
    assert get_current_user() is None
