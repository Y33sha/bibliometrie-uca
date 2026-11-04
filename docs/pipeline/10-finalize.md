# Finalisation

*À jour le 2026-11-04.*

La phase `finalize` met à jour les données qui dérivent des [contributions](../donnees/04-contributions.md), après la résolution des personnes et avant les enrichissements.

- **Purge des publications** : une publication sans enregistrement source ou sans contribution rattachée est supprimée, avec ses contributions. Elle perd son dernier enregistrement source quand le document disparaît de sa source, et sa dernière contribution rattachée quand celle-ci perd sa personne. Les étapes suivantes portent sur les publications restantes.
- **Report sur les publications** : `publications.in_perimeter` est matérialisé.
- **Rafraîchissement des vues matérialisées** `contribution_structures` et `publication_structures`, qui rattachent contributions et publications à leurs structures, puis `publication_rors`, qui rattache chaque publication aux ROR de tous ses auteurs, ancêtres compris.
- **Éditeur des publications en série** : chaque publication en série prend l'éditeur de ses publications les plus récentes.
- **Suppression des référentiels vides** : les monographies, puis les publications en série, puis les éditeurs que rien ne référence. Une publication en série vide reste quand l'un de ses ISSN est cité par la série d'un enregistrement source, ou relié à un titre précédent, suivant ou à un supplément. L'étape suit la purge : un référentiel vidé dans le run est supprimé dans le même run.
- **Recalcul des `publication_count`** des adresses, des publications en série et des éditeurs, qui dérivent du nombre de publications du périmètre.
