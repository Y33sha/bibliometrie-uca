# Données dérivées

*À jour le 2026-11-20.*

La phase `finalize` met à jour les données qui dérivent des [contributions](../donnees/04-contributions.md), après la résolution des personnes, avant le statut open access, les relations et les sujets.

- **Purge des publications** (`purge_publications`) : une publication sans enregistrement source ou sans contribution rattachée est supprimée, avec ses contributions. Elle perd son dernier enregistrement source quand le document disparaît de sa source, et sa dernière contribution rattachée quand celle-ci perd sa personne. Les étapes suivantes portent sur les publications restantes.
- **Report sur les publications** (`publications_in_perimeter`) : `publications.in_perimeter` est matérialisé.
- **Vues des structures** (`refresh_structure_views`) : rafraîchissement des vues matérialisées `contribution_structures` et `publication_structures`, qui rattachent contributions et publications à leurs structures, puis `publication_rors`, qui rattache chaque publication aux ROR de tous ses auteurs, ancêtres compris.
- **Nettoyage des référentiels de l'édition** :
   - **Éditeur des revues** (`serial_publishers`) : chaque publication en série prend l'éditeur de ses publications les plus récentes ;
   - **Référentiels vides** (`delete_empty_monographs`, `delete_empty_serials`, `delete_empty_publishers`) : les monographies, puis les publications en série, puis les éditeurs que rien ne référence sont supprimés. Une publication en série vide reste quand l'un de ses ISSN est cité par la série d'un enregistrement source, ou relié à un titre précédent, suivant ou à un supplément. L'étape suit la purge : un référentiel vidé dans le run est supprimé dans le même run.
- **Compteurs** (`publication_counts`) : recalcul des `publication_count` des adresses, des publications en série et des éditeurs, qui dérivent du nombre de publications du périmètre.
