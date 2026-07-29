"""Paramètres d'API invariants, codés en dur : URLs de base, délais de politesse entre requêtes et tailles de page, par source.

Centralise ces réglages pour éviter la dérive entre scripts. Modifier une valeur ici s'applique à tous les scripts qui interrogent l'API concernée. Les comportements spécifiques (reprise après erreur, pauses longues après quota dépassé) restent codés en dur dans chaque script.
"""

API_BASE_URLS: dict[str, str] = {
    # Extracteurs principaux (un endpoint par source)
    "hal": "https://api.archives-ouvertes.fr/search/",
    "openalex": "https://api.openalex.org/works",
    "wos": "https://api.clarivate.com/api/wos",
    "scanr": "https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search",
    "theses": "https://theses.fr/api/v1/theses/recherche/",
    # CrossRef : racine sans /works, l'adapter compose le chemin selon l'usage (/works/<doi>, /works?filter=orcid:...)
    "crossref": "https://api.crossref.org",
    # DataCite : racine, l'adapter compose `/dois` (query batch) ou `/dois/<doi>`.
    "datacite": "https://api.datacite.org",
    # doi.org : résolution de Registration Agency, l'adapter compose `/<doi>`.
    "doi_org": "https://doi.org/ra",
    # Endpoints secondaires
    "openalex_sources": "https://api.openalex.org/sources",
    "openalex_publishers": "https://api.openalex.org/publishers",
    "unpaywall": "https://api.unpaywall.org/v2",
    "zenodo": "https://zenodo.org/api/records",
    # DOAJ : racine de l'API, l'adapter compose `/search/journals/issn:{issn}`.
    "doaj": "https://doaj.org/api",
}


# Archives ouvertes HAL — API SolR (https://api.archives-ouvertes.fr/search/)
HAL_DELAY = 0.5
# 100 records/page (union de toutes les collections en une requête). Au-delà, les payloads label_xml (TEI) des collections à méga-authorships (CERN/ATLAS/CMS) font time-out le serveur HAL.
HAL_PER_PAGE = 100


# OpenAlex — polite pool (~5 req/s, 10 req/s toléré)
OPENALEX_DELAY = 0.2
OPENALEX_PER_PAGE = 200  # max imposé par l'API

# Clarivate WoS — API instable, 1 req/s par marge de sécurité
WOS_DELAY = 1.0
WOS_PER_PAGE = 10  # recommandation Clarivate (timeouts fréquents au-delà)

# ScanR — Elasticsearch public, courtoisie
SCANR_DELAY = 0.3
# Batchs search_after. 1000 retenu empiriquement : le cluster ScanR inflige des stalls intermittents (~10s) dont la fréquence suit le nombre de requêtes ; 2000 fait couper la connexion, 1000 est l'équilibre.
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
