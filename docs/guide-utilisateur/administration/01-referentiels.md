# Référentiels

## Labos

`/structures`, en session d'administration

Le volet de gestion d'une structure règle ses détails, ses tutelles et ses formes de nom. Les formes de nom servent à reconnaître la structure dans les adresses des publications.

![Gestion d'une structure](../../img/screenshots/admin_structure_management.png)

## Chercheurs

`/persons`, en session d'administration

Le volet de gestion d'une personne permet :

- **Exclusion** : écarter une fausse personne (nom mal découpé, nom d'équipe de recherche) ou une personne rattachée à l'établissement par erreur.
- **Identifiants** : chaque identifiant attribué par le pipeline est en attente, confirmé ou rejeté.
- **Formes de nom** : une forme partagée avec une autre personne est ambiguë. Une forme ouvre la liste de ses contributions rattachées ; chacune peut être détachée.
- **Fusion** : réunir deux personnes en double. La fusion exige qu'au plus une des deux ait une fiche RH.

### Contributions orphelines `/admin/orphan-contributions`

[Contributions](../../glossaire.md#contribution) de l'établissement sans personne, à attribuer à une personne existante ou nouvelle.

![Contributions orphelines](../../img/screenshots/admin_orphan_contributions.png)

## Publications

`/publications`, en session d'administration

L'onglet « Fusions suspectes » liste les publications aux listes d'auteurs très différentes selon les sources : deux documents distincts ont peut-être été fusionnés à tort.

Le volet d'une publication compare les métadonnées de chaque source, une colonne par source. Une ligne surlignée signale des valeurs différentes selon les sources.

![Fusions suspectes](../../img/screenshots/admin_publications.png)

## Éditeurs et publications en série

`/publishers` et `/journals`, en session d'administration

Le volet de gestion d'un éditeur règle son nom, son type et son pays. Il montre ses formes de nom : elles rattachent à l'éditeur les enregistrements sources qui le nomment.

Le volet de gestion d'une publication en série règle son titre, son type, son modèle OA et son caractère académique. Changer le type d'une publication en série change le type de ses publications.

Chaque volet fusionne un doublon dans l'entité ouverte.
