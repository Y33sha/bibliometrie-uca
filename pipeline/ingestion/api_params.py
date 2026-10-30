"""Paramètres invariants des API des sources : URL de base, tailles de page et débits.

Chaque valeur vaut pour tous les modules clients de l'API. La reprise après erreur et les pauses après un dépassement de quota relèvent de chaque module.
"""

API_BASE_URLS: dict[str, str] = {
    # Moissonnage
    "hal": "https://api.archives-ouvertes.fr/search/",
    "openalex": "https://api.openalex.org/works",
    "wos": "https://api.clarivate.com/api/wos",
    "scanr": "https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search",
    "theses": "https://theses.fr/api/v1/theses/recherche/",
    # theses.fr : détail d'une thèse ; l'adaptateur compose `<identifiant>`.
    "theses_detail": "https://theses.fr/api/v1/theses/these/",
    # Crossref : racine ; l'adaptateur compose `/works/<doi>` ou `/works?filter=…`.
    "crossref": "https://api.crossref.org",
    # DataCite : racine ; l'adaptateur compose `/dois` (requête par lot) ou `/dois/<doi>`.
    "datacite": "https://api.datacite.org",
    # doi.org : agence d'enregistrement ; l'adaptateur compose `/<préfixe>,<préfixe>,…`.
    "doi_org": "https://doi.org/ra",
    # doi.org : registre des DOI ; l'adaptateur compose `/<doi>`. Un DOI inconnu répond 404.
    "doi_org_handles": "https://doi.org/api/handles",
    # Référentiels et compléments
    "hal_structures": "https://api.archives-ouvertes.fr/ref/structure/",
    "openalex_sources": "https://api.openalex.org/sources",
    "openalex_publishers": "https://api.openalex.org/publishers",
    "openalex_institutions": "https://api.openalex.org/institutions",
    "unpaywall": "https://api.unpaywall.org/v2",
    # Sudoc : racine ; l'adaptateur compose `/services/issn2ppn/<ISSN>` et `/<ppn>.xml`.
    "sudoc": "https://www.sudoc.fr",
    # Versions du dump ROR publiées sur Zenodo, communauté `ror-data`.
    "zenodo_ror": "https://zenodo.org/api/communities/ror-data/records",
}


# Archives ouvertes HAL — API SolR (https://api.archives-ouvertes.fr/search/)
# Une requête couvre toutes les collections. Au-delà de 100 documents par page, les TEI (`label_xml`) des collections aux milliers d'auteurs (CERN, ATLAS, CMS) font expirer la requête.
HAL_PER_PAGE = 100


# OpenAlex
OPENALEX_PER_PAGE = 200  # max imposé par l'API

# Clarivate WoS — API instable
WOS_PER_PAGE = 10  # recommandation Clarivate (timeouts fréquents au-delà)

# ScanR — Elasticsearch public
# Pagination par `search_after`. Le cluster ScanR marque des pauses intermittentes (~10 s), d'autant plus fréquentes que les requêtes sont nombreuses. À 2000 documents par page, il coupe la connexion.
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
    """Renvoie le débit consenti à `source`, en requêtes par seconde, ou `None` sans plafond."""
    return MAX_PER_SECOND.get(source)


SUDOC_ISSN2PPN_BATCH = 20  # ISSN par requête `issn2ppn`
