# Pipeline

## Configuration `/admin/config`

Configuration du [moissonnage](../../pipeline/02-harvest.md) :

- années interrogées (modes *daily* et *full*) ;
- délais de réinterrogation des sources ;
- définition des périmètres (`uca`, `alliance_uca`) ;
- périmètre employé à chaque étape du pipeline (moissonnage, détection des affiliations, création de personnes).

Les identifiants d'accès aux sources (clés API, compte ScanR, adresse du *polite pool*) sont des secrets. Ils se règlent dans l'environnement du serveur, hors de l'interface : cf. [workflow](04-workflow.md#identifiants-daccès-aux-sources).

![Configuration](../../img/screenshots/admin_config.png)

## Logs
TODO: à compléter
