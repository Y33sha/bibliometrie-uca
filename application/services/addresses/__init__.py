"""Services applicatifs de curation des adresses (écritures API).

L'adresse n'a pas d'objet de domaine : le cluster de tables est porté par `AddressRepository`, ses règles par le SQL et par ces modules. La détection appartient au pipeline — matching des structures en phase `affiliations`, détection des pays en phase `countries` ; ces services portent la curation manuelle de ses résultats.

Sous-modules :
- `commands` : command handlers de l'API (frontière transactionnelle, commit).
- `structure_links` : validation manuelle des rattachements adresse ↔ structure (confirmer / rejeter / réinitialiser).
- `countries` : attribution manuelle des pays, propagation aux adresses jumelles puis vers les `source_publications` et `publications`.
"""
