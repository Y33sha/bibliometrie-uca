"""Sources bibliographiques : registre et interprétation des sources dont d'autres paquets ont besoin.

- `registry` : registre des sources (liste, sets, ordres de priorité).
- `hal`, `scanr` : ce que le domaine, l'API ou les transformations lisent d'une source (statuts de dépôt HAL, domaines CCSD, hal-id d'un document ScanR).

La lecture du payload qui sert seulement à l'ingestion d'une source vit dans `pipeline/ingestion/<source>/payload.py`.
"""
