"""Rattachement d'une revue à un enregistrement via l'espace de noms de son DOI.

Une `source_publication` à DOI mais sans `journal_id` reçoit la revue que désigne l'espace de noms de son DOI (`domain/journals/doi_namespaces.py`). La cible dépend des données : ce rattachement vit hors de la table des règles unaires (`rules`), comme la correction du DOI de groupe (`shared_doi`).
"""

# Provenance inscrite dans `raw_metadata.journal_id.corrected_by`.
JOURNAL_BY_DOI_NAMESPACE = "JOURNAL_BY_DOI_NAMESPACE"
