# Pages d'administration

## Pipeline

### Configuration (`/admin/config`) {#admin-config}

Paramètres des imports:
- email (polite pool);
- clé API WOS;
- années interrogées (modes weekly et full);
- paramètres de requête par source;
- définition et CRUD des périmètres (`uca`, `uca_wide`);
- périmètres utilisés à différentes étapes du pipeline.

## Logs
TODO: à compléter

## Référentiels

### Structures (`/admin/structures`) {#admin-structures}

Gère le CRUD sur l'ensemble des structures du périmètre UCA + les co-tutelles des laboratoires (ONR, écoles, autres universités) + le CHU.

Pour chaque structure:
- **Détails** (nom, acronyme, identifiant ROR, collection HAL);
- **Relations** (2 relations: tutelle, partenaire);
- **Identification** dans les publications: Gestion des formes de nom (pour l'identification dans les adresses)


### Gestion des personnes (`/admin/persons`)

Gestion du référentiel de personnes :

- **Édition du nom**.
- **Rejet** : marquer une personne comme fausse entité (mauvais parsing, noms d'équipes de recherche…).
- **Identifiants** : ORCID, idHAL, IdRef avec statut (en attente, confirmé, rejeté). Les boutons ✓ et ✗ permettent de confirmer ou rejeter. Ajout d'identifiants.
- **Formes de nom** : chaque personne a des formes de nom normalisées issues des sources. Un badge orange indique une forme **ambiguë** (partagée avec une autre personne). Cliquer sur une forme ouvre un modal permettant de consulter les authorships liées et de les détacher.
- **Fusion** : le bouton "Fusionner" permet de chercher un doublon et de fusionner deux personnes. Bloqué si les deux ont une fiche RH.

#### Authorships orphelines (`/admin/orphan-authorships`)

Authorships UCA dont l'auteur n'est pas encore identifié (`person_id = NULL`). Pour chaque authorship, on peut :

- **Attribuer** à une personne existante (recherche par nom)
- **Créer** une nouvelle personne et lui attribuer l'authorship
- **Traitement par lot** : sélectionner plusieurs authorships et les attribuer en une fois

Le dropdown de recherche affiche le département RH (si existant) ou l'id interne (sinon) pour départager les homonymes.

### Éditeurs
TODO: à compléter

### Revues
TODO: à compléter

## Adresses

### Contrôle des affiliations des adresses (`/admin/addresses`)

Contrôle des adresses d'affiliation résolues automatiquement par la phase `resolve_addresses` du pipeline.
Confirmer ou rejeter manuellement les associations adresse → structure.

#### Qualité de la détection (`/admin/feedback`)

Fait ressortir les faux positifs et faux négatifs dans la détection de structures dans les adresses:
- **faux négatifs**: affiliations adresse-structure non détectées par le script mais créées manuellement => repérer les formes de nom non détectées, et les ajouter dans admin/structures.
- **faux positifs**: affiliations détectées par le script mais rejetées manuellement => supprimer une forme de nom trop permissive ou lui ajouter un contexte contraignant.

Les corrections seront prises en compte à la prochaine exécution du pipeline (phase `resolve_addresses`).

### Gestion des liens adresses-pays (`/admin/countries`)

Attribution et correction des pays liés aux adresses.
Les corrections se propagent automatiquement aux publications liées, sans besoin de relancer le pipeline.

## Interfaces de dédoublonnage

### Doublons de publications (`/admin/duplicates`)

Paires de publications potentiellement identiques (titre normalisé identique, même type, même année).

Pour chaque paire, on peut :

- **Fusionner** : absorber une publication dans l'autre
- **Marquer comme distinctes** : indiquer que ce n'est pas un doublon
- **Passer** : reporter la décision

### Doublons de personnes (`/admin/person-duplicates`)

Paires de personnes potentiellement identiques. Mêmes opérations que pour les doublons de publications.

Deux modes de détection des candidats au dédoublonnage:
- Par similitude de noms (tolérance aux initiales et aux noms composés vs simples);
- Par conflit entre sources (deux personnes en même position auteur sur la même publication).
