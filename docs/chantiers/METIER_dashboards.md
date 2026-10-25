# Contenu des dashboards de structure et de personne

## Contexte

Le dashboard d'une structure (`get_structure_dashboard`, `infrastructure/read_models/structures.py`) et celui d'une personne (`person_dashboard`, `infrastructure/read_models/persons/detail.py`) s'ouvrent sur une rangée de chiffres clés : publications, part en open access, thèses. Suivent les publications par année, la répartition open access, les collaborations internationales et les pays partenaires (structure seulement), puis les sujets principaux.

Les blocs ne comptent pas sur le même corpus :

- **Publications par année** : tous les types de documents, sur les sept dernières années.
- **Chiffre clé « publications » et répartition open access** : tous les types de documents, toutes années confondues.
- **Collaborations internationales et pays partenaires** : les seuls articles (`doc_type = 'article'`), toutes années confondues.

Le chiffre clé « publications » et le graphique par année couvrent donc des périodes différentes. Rien à l'écran ne signale le passage des publications aux articles.

Les chiffres clés actuels (total, part en open access, thèses) renseignent peu une personne qui connaît la structure.

## Questions ouvertes

- **Corpus.** Harmoniser le corpus de tous les blocs, rendre la distinction publications / articles explicite bloc par bloc, ou fournir des facettes (types de documents, années) pour que l'utilisateur choisisse le corpus du dashboard.
- **Chiffres clés.** Lesquels retenir. Pistes calculables avec les données actuelles : publications de la dernière année complète et écart avec l'année précédente, moyenne annuelle sur cinq ans, part en open access, part d'articles en collaboration internationale (structure), nombre de thèses.
- **Chiffres par catégorie de document** : nombre de jeux de données, de logiciels, de brevets, de thèses, etc.
- **Nombre de personnes d'une structure** : absent de la réponse du dashboard.
- **Open access par année** : barres empilées par statut d'accès dans le graphique des publications par année, à la place de la répartition globale. Demande d'ajouter cette répartition à la réponse du dashboard.
- **Disposition.** Graphiques de même nature côte à côte (publications par année et pays partenaires pour une structure), répartition open access en bande compacte sur toute la largeur, sujets en fin de page.
