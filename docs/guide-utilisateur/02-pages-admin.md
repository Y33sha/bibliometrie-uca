# Pages d'administration

*A compléter et mettre à jour.*

## Pipeline

### Configuration

`/admin/config`

Configuration du [moissonnage](../pipeline/02-harvest.md) :
- années interrogées (modes *daily* et *full*);
- délais de réinterrogation des sources ;
- définition et CRUD des périmètres (`uca`, `alliance_uca`);
- périmètre utilisé à différentes étapes du pipeline (extraction, détection des affiliations, création de personnes).

Les identifiants d'accès aux sources (clés API, compte ScanR, adresse du *polite pool*) sont des secrets et se règlent dans l'environnement du serveur, hors de l'interface : cf. [workflow admin](03-workflow-admin.md#identifiants-daccès-aux-sources).

## Logs
TODO: à compléter

## Référentiels

### Structures

#### Liste `/structures`

En session d'administration, la liste des structures permet d'en créer.



#### Détails `/structures/{id}`, onglet « Gestion »

Gestion du CRUD des structures, et de leurs relations et formes de noms.

Pour chaque structure:
- **Détails** (nom, acronyme, identifiant ROR, collection HAL, identifiants dans les sources);
- **Tutelles**;
- **Formes de noms** pour l'identification des structures dans les adresses.

### Personnes

`/persons`, en session d'administration

La liste des personnes ajoute des facettes d'administration et des onglets de triage : formes ambiguës, conflits d'identifiant, doublons par nom. L'icône d'une ligne ouvre un volet de gestion de la personne :

- **Édition du nom**.
- **Exclusion** : écarter une fausse entité (mauvais parsing, noms d'équipes de recherche…) ou une personne rattachée au périmètre par erreur.
- **Identifiants** : [ORCID](../glossaire.md#orcid), [idHAL](../glossaire.md#idhal), [IdRef](../glossaire.md#idref), compte HAL, avec statut (en attente, confirmé, rejeté). Les boutons ✓ et ✗ permettent de confirmer ou rejeter. Ajout d'identifiants.
- **Formes de nom** : chaque personne a des formes de nom normalisées issues des sources. Un badge orange indique une forme **ambiguë** (partagée avec une autre personne). Cliquer sur une forme ouvre un modal permettant de consulter les contributions liées et de les détacher.
- **Fusion** : le bouton "Fusionner" permet de chercher un doublon et de fusionner deux personnes. Bloqué si les deux ont une fiche RH.

#### Contributions orphelines (`/admin/orphan-contributions`)

Contributions du périmètre sans personne (`person_id = NULL`), signalées par un bandeau sur la liste des personnes. Pour chaque contribution, on peut :

- **Attribuer** à une personne existante (recherche par nom)
- **Créer** une nouvelle personne et lui attribuer la contribution
- **Traitement par lot** : sélectionner plusieurs contributions et les attribuer en une fois

Le dropdown de recherche affiche le département RH (si existant) ou l'id interne (sinon) pour départager les homonymes.

### Publications

`/publications`, en session d'administration

La liste des publications ajoute l'onglet « Fusions suspectes ». L'icône d'une ligne ouvre un volet qui confronte les métadonnées données par chaque source, une colonne par source : identifiants, titre, type, année, revue et ISSN, éditeur, conteneur, volume, numéro, pages, langue, statut OA. Un champ absent de toutes les sources n'a pas de ligne. Une ligne surlignée signale des valeurs différentes selon les sources. Sous la revue et l'éditeur du référentiel figure, en gris, le nom donné par la source quand il diffère ; sous la langue, la valeur que donnait la source quand la normalisation l'a changée. Un Ctrl+clic sur le titre ouvre la fiche publique.

### Éditeurs
TODO: à compléter

### Revues
TODO: à compléter

## Adresses

### Affiliations des adresses

`/admin/addresses`

Contrôle des adresses d'affiliation résolues automatiquement par la [phase `affiliations`](../pipeline/04-affiliations.md) du pipeline.
Confirmer ou rejeter manuellement les associations adresse → structure.

#### Qualité de la détection

`/admin/feedback`

Affiche les faux positifs et faux négatifs dans la détection de structures dans les adresses:
- **faux négatifs**: affiliations adresse-structure non détectées par le script mais créées manuellement => action nécessaire: repérer les formes de nom non détectées et les ajouter dans l'onglet « Gestion » de la structure.
- **faux positifs**: affiliations détectées par le script mais rejetées manuellement => action nécessaire: supprimer une forme de nom trop permissive ou lui ajouter un contexte plus contraignant.

Les ajouts/suppressions de formes de noms seront prises en compte à la prochaine exécution du pipeline ([phase `affiliations`](../pipeline/04-affiliations.md)).

### Liens adresses-pays

`/admin/countries`

Attribution et correction des pays liés aux adresses. Chaque adresse affiche ses pays retenus et les moyens qui les ont trouvés. Les pays trouvés et non retenus sont proposés en pointillés ; un clic ajoute le pays.
Les corrections se propagent automatiquement aux publications liées, sans besoin de relancer le pipeline.
