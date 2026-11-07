"""Paramètres invariants des API des sources : URL de base, tailles de page et débits.

Chaque valeur vaut pour tous les modules clients de l'API. La reprise après erreur et les pauses après un dépassement de quota relèvent de chaque module.
"""

API_BASE_URLS: dict[str, str] = {
    # Moissonnage
    "hal": "https://api.archives-ouvertes.fr/search/",
    "openalex": "https://api.openalex.org/works",
    "wos": "https://api.clarivate.com/api/wos",
    "scanr": "https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search",
    "scanr_patents": "https://cluster-production.elasticsearch.dataesr.ovh/scanr-patents/_search",
    "theses": "https://theses.fr/api/v1/theses/recherche/",
    # theses.fr : détail d'une thèse ; l'adaptateur compose `<identifiant>`.
    "theses_detail": "https://theses.fr/api/v1/theses/these/",
    # Crossref : racine ; l'adaptateur compose `/works/<doi>` ou `/works?filter=…`.
    "crossref": "https://api.crossref.org",
    # DataCite : racine ; l'adaptateur compose `/dois` (requête par lot) ou `/dois/<doi>`.
    "datacite": "https://api.datacite.org",
    # INSPIRE-HEP : recherche dans la littérature ; l'adaptateur compose `/<numéro de fiche>` pour une fiche.
    "inspire": "https://inspirehep.net/api/literature",
    # doi.org : agence d'enregistrement ; l'adaptateur compose `/<préfixe>,<préfixe>,…`.
    "doi_org": "https://doi.org/ra",
    # doi.org : registre des DOI ; l'adaptateur compose `/<doi>`. Un DOI inconnu répond 404.
    "doi_org_handles": "https://doi.org/api/handles",
    # Référentiels et compléments
    "hal_structures": "https://api.archives-ouvertes.fr/ref/structure/",
    "openalex_sources": "https://api.openalex.org/sources",
    "openalex_source_lists": "https://api.openalex.org/source-lists",
    "openalex_publishers": "https://api.openalex.org/publishers",
    "openalex_institutions": "https://api.openalex.org/institutions",
    "unpaywall": "https://api.unpaywall.org/v2",
    # Sudoc : racine ; l'adaptateur compose `/services/issn2ppn/<ISSN>` et `/<ppn>.xml`.
    "sudoc": "https://www.sudoc.fr",
    # Versions du dump ROR publiées sur Zenodo, communauté `ror-data`.
    "zenodo_ror": "https://zenodo.org/api/communities/ror-data/records",
}


HAL_PER_PAGE = 100
"""Archives ouvertes HAL — API SolR (https://api.archives-ouvertes.fr/search/) Une requête couvre toutes les collections. Au-delà de 100 documents par page, les TEI (`label_xml`) des collections aux milliers d'auteurs (CERN, ATLAS, CMS) font expirer la requête."""


OPENALEX_PER_PAGE = 200
"""OpenAlex max imposé par l'API."""

WOS_PER_PAGE = 10
"""Clarivate WoS — API instable recommandation Clarivate (timeouts fréquents au-delà)"""

SCANR_PER_PAGE = 1000
"""ScanR — Elasticsearch public Pagination par `search_after`. Le cluster ScanR marque des pauses intermittentes (~10 s), d'autant plus fréquentes que les requêtes sont nombreuses. À 2000 documents par page, il coupe la connexion."""

THESES_PER_PAGE = 500
"""theses.fr — API publique max accepté par l'API."""

DOI_ORG_RA_BATCH = 100
"""doi.org/ra — aucune limite documentée ; 200 préfixes par requête passent préfixes par requête."""

MAX_CONCURRENT: dict[str, int] = {
    # API Solr publique sans plafond documenté.
    "hal": 5,
    "openalex": 3,
    # API instable.
    "wos": 2,
    # Elasticsearch public sans plafond documenté.
    "scanr": 5,
    # Même cluster que ScanR, pour quelques centaines de familles.
    "scanr_patents": 2,
    # API fragile : une requête à la fois.
    "theses": 1,
    # Polite pool : 3 requêtes simultanées au plus.
    "crossref": 3,
    "datacite": 3,
    # Fiches des grandes collaborations : jusqu'à 2 Mo par fiche.
    "inspire": 2,
    "doi_org": 3,
    # Aucune limite documentée.
    "sudoc": 4,
    # Aucune limite documentée.
    "unpaywall": 5,
}
"""Requêtes simultanées consenties à chaque accès, sous son plafond."""


MAX_PER_SECOND: dict[str, float] = {
    # Aucun seuil publié.
    "hal": 5,
    # Seuil publié : 10 req/s.
    "openalex": 8,
    "wos": 2,
    # Aucun seuil publié.
    "scanr": 5,
    # Même cluster que ScanR.
    "scanr_patents": 2,
    # Aucun seuil publié.
    "theses": 3,
    # Seuil publié du polite pool : 10 req/s, 3 requêtes simultanées.
    "crossref": 5,
    # Seuil publié du tier identifié (User-Agent avec mailto) : 1 000 requêtes par 5 minutes.
    "datacite": 3,
    # Aucun seuil dans les en-têtes de réponse.
    "inspire": 2,
    # Aucun seuil publié.
    "sudoc": 5,
    # Seuil publié : 100 000 requêtes par jour, aucun seuil par seconde.
    "unpaywall": 20,
}
"""Débit consenti à chaque accès, en requêtes par seconde, toutes requêtes confondues. Un accès absent de la table est sans plafond."""


def request_budget(source: str) -> float | None:
    """Renvoie le débit consenti à `source`, en requêtes par seconde, ou `None` sans plafond."""
    return MAX_PER_SECOND.get(source)


SUDOC_ISSN2PPN_BATCH = 20
"""ISSN par requête `issn2ppn`."""
