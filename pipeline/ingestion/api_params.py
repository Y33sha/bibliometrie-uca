"""Paramètres d'API invariants, codés en dur : URLs de base, débits et tailles de page, par source.

Centralise ces réglages pour éviter la dérive entre scripts. Modifier une valeur ici s'applique à tous les scripts qui interrogent l'API concernée. Les comportements spécifiques (reprise après erreur, pauses longues après quota dépassé) restent codés en dur dans chaque script.
"""

API_BASE_URLS: dict[str, str] = {
    # Moissonneurs principaux (un endpoint par source)
    "hal": "https://api.archives-ouvertes.fr/search/",
    "openalex": "https://api.openalex.org/works",
    "wos": "https://api.clarivate.com/api/wos",
    "scanr": "https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search",
    "theses": "https://theses.fr/api/v1/theses/recherche/",
    # CrossRef : racine sans /works, l'adapter compose le chemin selon l'usage (/works/<doi>, /works?filter=orcid:...)
    "crossref": "https://api.crossref.org",
    # DataCite : racine, l'adapter compose `/dois` (query batch) ou `/dois/<doi>`.
    "datacite": "https://api.datacite.org",
    # doi.org : agence d'enregistrement, l'adapter compose `/<préfixe>,<préfixe>,…`.
    "doi_org": "https://doi.org/ra",
    # doi.org : registre des DOI, l'adapter compose `/<doi>` ; un DOI inconnu répond 404.
    "doi_org_handles": "https://doi.org/api/handles",
    # Endpoints secondaires
    "hal_structures": "https://api.archives-ouvertes.fr/ref/structure/",
    "openalex_sources": "https://api.openalex.org/sources",
    "openalex_publishers": "https://api.openalex.org/publishers",
    "openalex_institutions": "https://api.openalex.org/institutions",
    "unpaywall": "https://api.unpaywall.org/v2",
    # Sudoc : racine, l'adapter compose `/services/issn2ppn/<ISSN>` et `/<ppn>.xml`.
    "sudoc": "https://www.sudoc.fr",
    # Versions du dump ROR publiées sur Zenodo, communauté `ror-data`.
    "zenodo_ror": "https://zenodo.org/api/communities/ror-data/records",
}


# Archives ouvertes HAL — API SolR (https://api.archives-ouvertes.fr/search/)
# 100 records/page (union de toutes les collections en une requête). Au-delà, les payloads label_xml (TEI) des collections à méga-contributions (CERN/ATLAS/CMS) font time-out le serveur HAL.
HAL_PER_PAGE = 100


# OpenAlex
OPENALEX_PER_PAGE = 200  # max imposé par l'API

# Clarivate WoS — API instable
WOS_PER_PAGE = 10  # recommandation Clarivate (timeouts fréquents au-delà)

# ScanR — Elasticsearch public
# Batchs search_after. 1000 retenu empiriquement : le cluster ScanR inflige des stalls intermittents (~10s) dont la fréquence suit le nombre de requêtes ; 2000 fait couper la connexion, 1000 est l'équilibre.
SCANR_PER_PAGE = 1000

# theses.fr — API publique
THESES_PER_PAGE = 500  # max accepté par l'API

# doi.org/ra — aucune limite documentée ; 200 préfixes par requête passent
DOI_ORG_RA_BATCH = 100  # préfixes par requête

# Sudoc — aucune limite documentée
SUDOC_MAX_CONCURRENT = 4


# Débit consenti à chaque accès, en requêtes par seconde, toutes requêtes confondues. Un accès absent de la table est sans plafond.
MAX_PER_SECOND: dict[str, float] = {
    # Aucun seuil publié.
    "hal": 5,
    # Seuil publié : 10 req/s.
    "openalex": 8,
    "wos": 2,
    # Aucun seuil publié.
    "scanr": 5,
    # Aucun seuil publié.
    "theses": 3,
    # Seuil publié du polite pool : 10 req/s, 3 requêtes simultanées.
    "crossref": 5,
    # Seuil publié du tier identifié (User-Agent avec mailto) : 1 000 requêtes par 5 minutes.
    "datacite": 3,
    # Aucun seuil publié.
    "sudoc": 5,
}


def request_budget(source: str) -> float | None:
    """Débit consenti à `source`, en requêtes par seconde, ou `None` sans plafond."""
    return MAX_PER_SECOND.get(source)


SUDOC_ISSN2PPN_BATCH = 20  # ISSN par requête `issn2ppn`
