# Page Statistiques : filtres communs avec la liste des publications, indicateurs

## Contexte

**Deux jeux de filtres.** La liste des publications (`PublicationsListView.svelte`) déclare 18 filtres dans un registre (`filterRegistry.ts`). La page Statistiques (`routes/stats/+page.svelte`) déclare 9 filtres à la main : années, labos, voies open access, types de documents, revue, éditeur, organisation partenaire, licence, APC. Les deux pages emploient les mêmes noms de paramètres pour ces 9 filtres.

**Deux API.** L'API des statistiques (`stats_filters`, `interfaces/api/routers/stats.py`) n'accepte que ces 9 filtres. Elle ignore la recherche, l'accès, les pays, les langues, les sujets, l'auteur, les sources, le statut HAL, la correspondance et le périmètre. Trois fonctions assemblent les conditions séparément, à partir des mêmes briques (`infrastructure/read_models/filters.py`) :

- `_build_list_clauses` pour la liste (`publications/list.py`) ;
- `_clauses_skipping` pour les facettes de la liste (`publications/facets.py`) ;
- `stats_filter_clauses` pour les statistiques (`stats/_shared.py`).

**Filtres liés à un contexte.** Le statut HAL suppose un seul labo. La correspondance et le périmètre supposent une personne. Ces filtres n'ont pas de sens sur la page Statistiques. Le bouton « Statistiques » est absent de la page d'une personne.

**Transmission entre les pages.** Le bouton « Statistiques » de la liste transmet les filtres que la page Statistiques sait représenter. Les autres sont perdus sans avertissement. Le bouton « Voir les publications » transmet les 9 filtres de la page Statistiques. La page Statistiques présélectionne des années par défaut quand l'URL ne contient pas d'années.

**Indicateur et mesure.** La page Statistiques propose deux réglages distincts :

- un indicateur : la dimension qui découpe chaque barre (accès, voie open access, type de document, licence) ou la carte des collaborations ;
- une mesure : nombre de publications ou montant des APC (`MEASURES`, `infrastructure/read_models/stats/pivot.py`).

Cette distinction est pertinente pour le calcul, mais obscure pour l'utilisateur.

## Décisions

- **Les filtres de la liste valent aussi pour la page Statistiques**, sauf ceux qui supposent un labo ou une personne (statut HAL, correspondance, périmètre).
- **Une seule barre de filtres** pour les deux pages.
- **Les boutons « Statistiques » et « Voir les publications » transmettent tous les filtres.** Quand un filtre ne peut pas être transmis, un message l'annonce.
- **Un indicateur impose sa mesure.** « Montant des APC » devient un indicateur, mesuré en montant ; tous les autres indicateurs se mesurent en nombre de publications. Le réglage « Mesure » disparaît. Les futures mesures d'impact suivront la même règle.

## Phasage

### Serveur

- [ ] Un seul modèle de filtres et une seule fonction d'assemblage des conditions pour la liste, ses facettes et les statistiques
- [ ] L'API des statistiques accepte tous les filtres de la liste, sauf statut HAL, correspondance et périmètre

### Interface

- [ ] Contexte de la liste en union discriminée (sujet, laboratoire, personne, revue, éditeur, monographie). Il détermine les filtres liés au contexte et le mode APC, à la place de `showHalStatusColumn`, `showCorrespondingColumn`, `showPerimeterFacet` et `apcMode`
- [ ] Barre de filtres de la liste extraite en composant, réutilisée par la page Statistiques
- [ ] Sérialisation unique des filtres dans l'URL ; « Statistiques » et « Voir les publications » transmettent tous les filtres
- [ ] Message d'avertissement quand un filtre n'est pas transmis
- [ ] Indicateurs imposant leur mesure ; « Montant des APC » ajouté aux indicateurs, réglage « Mesure » retiré

## Questions ouvertes

- **Années par défaut** de la page Statistiques : les garder quand l'URL ne contient pas d'années, ou les retirer pour qu'un lien depuis la liste sans filtre d'années montre le même corpus.
- **Filtres liés à un contexte** : les transmettre quand le laboratoire ou la personne est seul sélectionné ? Statut HAL pour un seul laboratoire ; correspondance et périmètre pour une seule personne. Piste commune avec les listes d'entités liées ([Administration et navigation](UI_administration-et-navigation.md)).
- **Découpage de l'indicateur « Montant des APC »** : une barre unique par catégorie, ou un découpage par voie open access.
- **Du graphique à la liste**, idée à tester : un clic sur une barre ouvrirait la liste des publications filtrée sur le groupement cliqué.
