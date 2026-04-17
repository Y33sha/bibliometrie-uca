"""
Délais de politesse entre requêtes (secondes), par API.

Centralise les rate limits pour éviter la dérive entre scripts. Modifier
une valeur ici s'applique à tous les scripts qui interrogent l'API concernée.

Les comportements spécifiques (recovery après erreur, pauses longues après
quota dépassé) restent localement hardcodés dans chaque script.
"""

# Archives ouvertes HAL — API SolR (https://api.archives-ouvertes.fr/search/)
HAL_DELAY = 0.5

# OpenAlex — polite pool (~5 req/s, 10 req/s toléré)
OPENALEX_DELAY = 0.2

# Clarivate WoS — API instable, 1 req/s par marge de sécurité
WOS_DELAY = 1.0

# ScanR — Elasticsearch public, courtoisie
SCANR_DELAY = 0.3

# theses.fr — API publique
THESES_DELAY = 0.3

# Unpaywall — ~8 req/s conservateur
UNPAYWALL_DELAY = 0.12

# Zenodo — courtoisie
ZENODO_DELAY = 0.5

# DOAJ — courtoisie
DOAJ_DELAY = 0.15
