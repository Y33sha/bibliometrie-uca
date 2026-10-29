"""Idempotence des phases du pipeline : chaque test insère des données de staging, lance la phase, compte les résultats, relance la phase et compare les comptes.

Un fichier par phase (`normalize_<source>`, `affiliations`, `persons`), plus `normalize_inter_source` pour l'enchaînement de deux sources.
"""
