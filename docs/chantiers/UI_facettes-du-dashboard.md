# Chantier — Facettes du dashboard

## Contexte

**Le dashboard** des fiches structure, personne, revue et éditeur (`PublicationsDashboard`) agrège les publications de l'entité par `/api/stats/pivot`, `/api/stats/collaborations` et `/api/stats/citation-points`. Ces trois points d'entrée acceptent tous les filtres de la liste des publications (`PublicationQueryFilters`).

**Ses filtres sont écrits en dur, et invisibles.**
- Types : la famille « Publications ». Le graphique des types de documents fait exception : il compte toutes les familles, thèses en cours comprises, alors que la liste des publications les exclut (`excluded_doc_type=ongoing_thesis`).
- Années : de l'année en cours moins 5 à l'année en cours, parmi les années présentes (`defaultYears`).

**L'onglet Publications** de chaque fiche (`PublicationsListView`) possède déjà le panneau des filtres, leur synchronisation avec l'URL et trois vues : Notices, Tableau, Statistiques. La vue Statistiques lit les filtres actifs (`list.filterParams`).

**Chaque fiche ajoute au dashboard des blocs hors filtres** : thèses en cours et personnes rattachées pour une structure, thèses dirigées ou jugées pour une personne, sujets pour l'une et l'autre.

## Décisions

- **Le dashboard affiche le panneau des filtres des publications.**
- **Les filtres sont communs au dashboard et à la liste des publications de la fiche.**
- **Aucun filtre par défaut** : le dashboard compte toutes les publications de l'entité, hors thèses en cours, comme la liste. Des valeurs par défaut s'ajoutent si l'usage le demande.
- **Le graphique des types de documents suit les filtres**, comme le reste du dashboard. Sans filtre de types, il couvre toutes les familles.

## Architecture à trancher

- **A. Le dashboard devient une vue de `PublicationsListView`**, à côté de Notices, Tableau et Statistiques, sur le modèle de la vue Statistiques. Un seul état des filtres, un seul panneau, une seule URL. Les onglets « Dashboard » et « Publications » de chaque fiche fusionnent en un onglet « Publications », ouvert sur la vue Dashboard. Les blocs propres à la fiche passent à la vue par un snippet. La page `/publications` reçoit la vue ou s'en passe, selon une option du composant.
- **B. Deux onglets, état des filtres créé par la fiche.** Chaque fiche crée l'état (`useFilteredList`) et le confie aux deux onglets ; `PublicationsListView` reçoit un état créé ailleurs. Les onglets restent inchangés.

Recommandation : A. Elle réutilise la mécanique de la vue Statistiques et supprime un doublon d'onglets ; B oblige chacune des quatre fiches à créer et transmettre l'état.

## Phasage

### 1. Vue Dashboard

- [ ] `PublicationsDashboard` lit les filtres actifs, au lieu de ses filtres en dur. Suppression de `defaultYears` et de son test.
- [ ] Vue « Dashboard » dans `PublicationsListView`, rechargée à chaque changement de filtre, inscrite dans l'URL.
- [ ] Blocs propres à la fiche transmis à la vue.
- [ ] Fiches structure, personne, revue et éditeur : un onglet « Publications » ouvert sur la vue Dashboard, à la place des onglets « Dashboard » et « Publications ».
- [ ] Captures avant et après des quatre fiches.

### 2. Évaluation

- [ ] Blocs hors filtres à côté de chiffres filtrés : lisibilité à juger sur captures.
- [ ] Graphique des publications par année sans filtre d'années, sur une entité ancienne : nombre de barres.
- [ ] Valeurs par défaut des filtres, si l'usage le demande.

### 3. Mise à jour de la documentation

- [ ] `docs/guide-utilisateur/pages-publiques/` : dashboard filtrable et onglets des fiches dans `02-publications.md`, `03-structures.md`, `04-personnes.md` et `05-revues-et-editeurs.md` ; captures `structure_dashboard.png`, `journal_dashboard.png` et `publisher_dashboard.png`.
