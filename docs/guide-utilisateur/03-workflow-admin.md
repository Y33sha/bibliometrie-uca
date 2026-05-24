# Workflow admin

*à compléter*

## En amont du pipeline

### Définition des structures
Pas de moissonnage possible sans structures. Pas de repérage des affiliations (étape affiliations du pipeline) sans formes de nom.

### Configuration du pipeline

## En aval du pipeline

### Rapports de pipeline


### Contrôle des affiliations
Facultatif, mais permet de perfectionner progressivement le repérage des structures dans les adresses:
- Confirmation/rejet manuel des liens adresse-structure, individuellement ou par batch;
- Contrôle qualité: visualiser les divergences entre détection automatisée et contrôle manuel => permet de repérer les formes de nom non détectées (à ajouter) ou trop laxistes (à supprimer, ou ajouter contexte plus contraignant).

Les ajouts ou suppressions de formes de noms deviennent effectifs au pipeline suivant. Les actions manuelles ne sont pas écrasées par le *re-run* du pipeline.


### Gestion du référentiel de personnes

- Fusion des doublons
- Détachement des authorships attribuées à tort
- Vérification des identifiants de personne
- Correction du nom
- Authorships orphelines: rattachement à une personne existante ou création de personne

### Gestion des référentiels d'éditeurs et de revues

- Doublons d'éditeurs: possibilité de fusionner ('Elsevier' vs 'Elsevier BV' selon source).
- Doublons de revues: idem
- Enrichissement des informations sur les éditeurs et revue ->> clarifier ce qui est fait automatiquement par le pipeline


### Legacy
- Pages dédoublonnage: à améliorer ou supprimer
