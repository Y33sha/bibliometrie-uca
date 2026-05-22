# Unpaywall

Script : [interfaces/cli/pipeline/enrich_oa_status.py](https://github.com/Y33sha/bibliometrie-uca/blob/master/interfaces/cli/pipeline/enrich_oa_status.py) (orchestration dans [application/pipeline/enrich/enrich_oa_status.py](https://github.com/Y33sha/bibliometrie-uca/blob/master/application/pipeline/enrich/enrich_oa_status.py)).

Interroge l'API Unpaywall (`https://api.unpaywall.org/v2/{doi}`) pour chaque publication avec DOI. Met à jour `publications.oa_status`.

Règle métier : ne remplace jamais un statut `diamond` par `gold` (Unpaywall ne distingue pas le diamond OA du gold).
