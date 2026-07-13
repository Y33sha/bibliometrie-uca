"""Délais de politesse entre requêtes (secondes), par API.

Centralise les rate limits pour éviter la dérive entre scripts. Modifier une valeur ici s'applique à tous les scripts qui interrogent l'API concernée.

Les comportements spécifiques (reprise après erreur, pauses longues après quota dépassé) restent codés en dur dans chaque script.
"""

# Archives ouvertes HAL — API SolR (https://api.archives-ouvertes.fr/search/)
HAL_DELAY = 0.5
HAL_PER_PAGE = 200  # max 10 000 ; 200 retenu empiriquement (un peu mieux que 100 et 500 au fetch)

# Overrides par collection : collections de physique des particules avec méga-authorships (3000+ auteurs, collabs CERN/ATLAS/CMS, etc.) produisent des payloads énormes côté `label_xml` — le serveur HAL time-out à 500 records/page et renvoie des 500. Descendre à un per_page plus petit stabilise l'extraction sur ces collections.
HAL_PER_PAGE_OVERRIDES: dict[str, int] = {
    "LPC-CLERMONT": 50,
}


def hal_per_page_for(collection_code: str | None) -> int:
    """Retourne le `per_page` HAL à utiliser pour une collection donnée."""
    if collection_code and collection_code in HAL_PER_PAGE_OVERRIDES:
        return HAL_PER_PAGE_OVERRIDES[collection_code]
    return HAL_PER_PAGE


# OpenAlex — polite pool (~5 req/s, 10 req/s toléré)
OPENALEX_DELAY = 0.2
OPENALEX_PER_PAGE = 200  # max imposé par l'API

# Clarivate WoS — API instable, 1 req/s par marge de sécurité
WOS_DELAY = 1.0
WOS_PER_PAGE = 10  # recommandation Clarivate (timeouts fréquents au-delà)

# ScanR — Elasticsearch public, courtoisie
SCANR_DELAY = 0.3
# Taille des batchs search_after. 1000 retenu empiriquement : le cluster ScanR inflige des stalls serveur intermittents (~10s) dont la fréquence suit le *nombre* de requêtes. Réduire les pages (29 → 7 pour une année de ~5500 docs) supprime ces stalls et divise le temps par ~4. 2000 fait couper la connexion par le serveur ; 1000 est le point d'équilibre.
SCANR_PER_PAGE = 1000

# theses.fr — API publique
THESES_DELAY = 0.3
THESES_PER_PAGE = 500  # max accepté par l'API

# CrossRef — polite pool (avec mailto), pas de seuil documenté ; on reste raisonnable à ~10 req/s
CROSSREF_DELAY = 0.1

# Unpaywall — ~8 req/s conservateur
UNPAYWALL_DELAY = 0.12

# DOAJ — courtoisie
DOAJ_DELAY = 0.15

# ROR — 2000 req / 5 min = 6.66 req/s sustained, 100 req / 10s en burst. 150ms (~6.66 req/s) reste sous le seuil sustained sans burst.
ROR_DELAY = 0.15
