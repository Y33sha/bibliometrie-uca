"""Services applicatifs des corrections à la main sur les adresses (écritures API).

L'adresse n'a pas d'objet de domaine. `AddressRepository` gère ses tables ; le SQL et ces modules appliquent ses règles. La détection appartient au pipeline — matching des structures en phase `affiliations`, détection des pays en phase `countries` ; ces services corrigent ses résultats à la main.

Sous-modules :
- `structure_links` : validation manuelle des rattachements adresse ↔ structure (confirmer / rejeter / réinitialiser), propagation vers le périmètre des contributions sources.
- `countries` : attribution manuelle des pays, propagation vers les `source_records` et `publications`.
"""
