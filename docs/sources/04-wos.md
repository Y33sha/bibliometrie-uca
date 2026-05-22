# Web of Science

## API utilisée

**Expanded API** (`https://api.clarivate.com/api/wos`) — moissonnage des publications.
- Requête par Organisation-Enhanced (OG) + année
- Pagination par offset (`firstRecord`), 100 résultats/page, 1s de délai
- Retry avec backoff exponentiel (API instable, rate limiting silencieux)
- Quota annuel limité (vérification au démarrage)

## Données récupérées

- **Publications** : titre, DOI, année, type, langue, OA status
- **Auteurs** : display_name, last_name, first_name, daisng_id, researcher_id, ORCID
- **Affiliations** : adresses structurées dans le champ C1 (`[Author1; Author2] Address`)
- **Correspondant** : `reprint = "Y"` indique l'auteur correspondant

## Particularités

- Deux formats de données : TSV (fichiers téléchargés) et API JSON (structure imbriquée `static_data`/`dynamic_data`). Le normaliseur gère les deux.
- Le DOI est profondément imbriqué : `dynamic_data.cluster_related.identifiers.identifier[].value` (peut être dict ou liste)
- La pagination par `queryId` ne fonctionne pas de manière fiable ; le script utilise `firstRecord` avec une nouvelle recherche à chaque page
- Pause longue toutes les 10 pages (15s) et entre chaque année (30s) pour ménager l'API
- Les DOI de preprints (10.48550, 10.21203, etc.) sont filtrés lors du cross-import
