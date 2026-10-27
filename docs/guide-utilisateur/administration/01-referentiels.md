# Référentiels

## Structures

`/structures`, en session d'administration

La liste des structures permet d'en créer. L'icône d'une ligne, ou celle placée à gauche du nom sur la fiche d'une structure, ouvre un volet de gestion de la structure :

- **Détails** : nom, acronyme, identifiant ROR, collection HAL, identifiants dans les sources ;
- **Tutelles** : un clic sur une tutelle ouvre son volet ;
- **Formes de nom**, pour l'identification des structures dans les adresses.

![Gestion d'une structure](../../img/screenshots/admin_structure_management.png)

## Personnes

`/persons`, en session d'administration

La liste des personnes ajoute les facettes Exclusion, Activité et À confirmer, et les onglets de triage : formes ambiguës, conflits d'identifiant, doublons par nom.

Dans toute liste de personnes, l'icône d'une ligne ouvre un volet de gestion de la personne. La même icône figure à gauche du nom, sur la fiche d'une personne.

- **Édition du nom**.
- **Exclusion** : écarter une fausse entité (mauvais parsing, noms d'équipes de recherche…) ou une personne rattachée au périmètre par erreur.
- **Identifiants** : [ORCID](../../glossaire.md#orcid), [idHAL](../../glossaire.md#idhal), [IdRef](../../glossaire.md#idref), compte HAL, avec leur statut (en attente, confirmé, rejeté), à confirmer ou rejeter. Ajout d'identifiants.
- **Formes de nom** : chaque personne a des formes de nom normalisées issues des sources. Un badge orange signale une forme **ambiguë**, partagée avec une autre personne. Cliquer sur une forme ouvre la liste des contributions liées, que l'on peut détacher.
- **Fusion** : chercher un doublon et fusionner deux personnes. Impossible quand les deux ont une fiche RH.

### Contributions orphelines `/admin/orphan-contributions`

Contributions du périmètre sans personne, signalées par un bandeau sur la liste des personnes. Pour chaque contribution, on peut :

- **Attribuer** la contribution à une personne existante, cherchée par nom ;
- **Créer** une personne et lui attribuer la contribution ;
- **Traiter par lot** : sélectionner plusieurs contributions et les attribuer en une fois.

La recherche affiche le département RH, à défaut l'identifiant interne, pour départager les homonymes.

## Publications

`/publications`, en session d'administration

La liste des publications ajoute l'onglet « Fusions suspectes ».

Dans toute liste de publications ou de thèses, l'icône d'une ligne ouvre un volet de la publication. La même icône figure à gauche du titre, sur la fiche d'une publication. Le volet confronte les métadonnées de chaque source, une colonne par source : identifiants, titre, type, année, revue et ISSN, éditeur, conteneur, volume, numéro, pages, langue, statut OA. Un champ absent de toutes les sources n'a pas de ligne. Une ligne surlignée signale des valeurs différentes selon les sources. Sous la revue et l'éditeur du référentiel figure, en gris, le nom donné par la source quand il diffère. Sous la langue figure la valeur de la source quand la normalisation l'a changée. Un Ctrl+clic sur le titre ouvre la fiche publique.

![Fusions suspectes](../../img/screenshots/admin_publications.png)

## Éditeurs
TODO: à compléter

## Revues
TODO: à compléter
