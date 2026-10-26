# Finalisation

*À jour le 2026-10-26.*

La phase `finalize` met à jour les données qui dérivent des [contributions](../donnees/04-contributions.md), après la résolution des personnes et avant les enrichissements.

1. **Report sur les publications** : `publications.in_perimeter` est matérialisé, pour que les filtres de liste lisent un drapeau au lieu de recalculer l'appartenance au périmètre à chaque requête.
2. **Rafraîchissement des vues matérialisées** `contribution_structures` et `publication_structures`, qui rattachent contributions et publications à leurs structures, puis `publication_rors`, qui rattache chaque publication aux ROR de tous ses auteurs, ancêtres compris.

## Opérations finales

- **Purge des publications** : une publication sans enregistrement source ou sans contribution est supprimée. Elle perd son dernier enregistrement source quand le document disparaît de sa source, et sa dernière contribution rattachée quand celle-ci perd sa personne.
- **Éditeur des publications en série** : chaque publication en série prend l'éditeur de ses publications les plus récentes (`serial_publishers.py`).
- **Suppression des référentiels vides**, dans cet ordre, car une monographie maintient sa collection, une publication en série ou un préfixe DOI son éditeur :
  - les monographies sans enregistrement ni publication ;
  - les publications en série sans enregistrement, sans publication, sans monographie et sans paiement APC, avec leurs formes de nom. Le journal d'exécution garde le titre, l'éditeur et les ISSN de chaque entrée supprimée ;
  - les éditeurs sans publication en série, sans monographie, sans enregistrement source, sans publication, sans préfixe DOI, sans paiement APC et sans forme de nom de revue.

  Elle suit les dernières suppressions de publications : un référentiel vidé dans le run est supprimé dans le même run.
- **Recalcul des `publication_count`** des adresses, des publications en série et des éditeurs, qui dérivent du nombre de publications du périmètre.
