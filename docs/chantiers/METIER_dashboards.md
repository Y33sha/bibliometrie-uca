# Contenu des dashboards de structure et de personne

## Contexte

Le dashboard d'une structure (`get_structure_dashboard`, `infrastructure/read_models/structures/queries.py`) et celui d'une personne (`person_dashboard`, `infrastructure/read_models/persons/detail.py`) s'ouvrent sur une rangée de chiffres clés : publications, part en open access, thèses. Suivent les publications par année, la répartition open access, les collaborations internationales et les pays partenaires (structure seulement), puis les sujets principaux.

Les blocs ne comptent pas sur le même corpus :

- **Publications par année** : tous les types de documents, sur les sept dernières années.
- **Chiffre clé « publications » et répartition open access** : tous les types de documents, toutes années confondues.
- **Collaborations internationales et pays partenaires** : les seuls articles (`doc_type = 'article'`), toutes années confondues.

Le chiffre clé « publications » et le graphique par année couvrent donc des périodes différentes. Rien à l'écran ne signale le passage des publications aux articles.

Le dashboard d'une structure compte les contributions marquées `in_perimeter`. L'onglet Publications de la même page compte toutes les publications de la structure (`publication_structures`). Les deux décomptes diffèrent pour un laboratoire non UCA : 1 208 publications au dashboard, 1 459 dans l'onglet.

Les dashboards d'éditeur (`get_publisher_dashboard`) et de revue (`get_serial_dashboard`) ont aussi leurs propres requêtes. Les quatre dashboards recalculent des agrégats que le moteur de la page Statistiques produit (`infrastructure/read_models/stats/`).

Les chiffres clés actuels (total, part en open access, thèses) renseignent peu une personne qui connaît la structure.

## Décisions

- **Corpus** : celui de l'onglet Publications de la page, sous les valeurs par défaut de la page Statistiques (famille « Publications », années récentes). Tous les blocs comptent sur ce corpus, collaborations comprises.
- **Un seul moteur** : les blocs communs aux dashboards et à la page Statistiques passent par le moteur des statistiques. Les requêtes propres aux dashboards disparaissent.
- **Chiffres clés** : publications, part en open access, part de collaborations internationales, thèses. Pour une structure, s'y ajoute le nombre de personnes présentes dans le SI RH.
- **Types de documents** : nombre de publications par famille de types.
- **Open access par année** : barres empilées par statut d'accès dans le graphique des publications par année, à la place de la répartition globale.

## Phasage

### Serveur

- [x] Dashboards de structure et de personne servis par le moteur des statistiques (pivot, collaborations), sur le corpus de l'onglet Publications ; requêtes propres retirées
- [x] Nombre de personnes présentes dans le SI RH d'une structure

### Interface

- [x] Chiffres clés : publications, part en open access, part de collaborations internationales, thèses ; pour une structure, personnes présentes dans le SI RH
- [x] Publications par année en barres empilées par statut d'accès
- [x] Nombre de publications par famille de types de documents
- [x] Corpus du dashboard indiqué à l'écran (types, années)
- [ ] Mise à jour de la documentation

### Dashboards d'éditeur et de revue

- [ ] Blocs communs (types de documents, open access) servis par le moteur des statistiques, sur le même corpus ; blocs propres conservés (types de publications en série, statuts attendus selon le modèle de la revue)

## Questions ouvertes

- **Disposition.** Graphiques de même nature côte à côte (publications par année et pays partenaires pour une structure), répartition par types de documents en bande compacte sur toute la largeur, sujets en fin de page.
- **Choix du corpus par l'utilisateur.** Un dashboard sans facettes montre un corpus fixe ; le lien vers la page Statistiques ne convient pas pour le modifier.
