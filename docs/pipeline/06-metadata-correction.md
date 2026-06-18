# Correction des métadonnées

Deux phases enchaînées, juste avant le [rattachement des publications](07-publications.md), préparent les `source_publications` pour que le matching s'appuie sur des valeurs propres et cohérentes. Les corrections sont écrites sur les colonnes des `source_publications` ; la valeur source d'origine est conservée (dans `raw_metadata`) et chaque correction est recalculée à partir d'elle à chaque run — la passe est ainsi idempotente et se corrige d'elle-même, sans état à entretenir (un re-moissonnage ou un changement de type de revue est rattrapé au run suivant).

## Résolution du concept DOI Zenodo (phase `zenodo_doi`)

Zenodo attribue un DOI distinct à chaque version d'un dépôt, plus un **concept DOI** stable qui couvre toutes les versions. Sans correction, deux versions d'un même jeu de données compteraient pour deux documents.

Cette phase interroge l'API Zenodo pour chaque `source_publication` Zenodo et met en cache son concept DOI dans `external_ids`. Elle se limite à récupérer et mettre en cache : la substitution effective du DOI a lieu à la phase suivante. Séparer les deux permet de rejouer le matching sans re-solliciter Zenodo, et inversement de relancer Zenodo seul si l'API était indisponible. La phase est idempotente (une `source_publication` déjà résolue est ignorée aux runs suivants) ; un échec temporaire de l'API est réessayé au prochain run, avec un coupe-circuit au bout de quelques échecs consécutifs.

> **Évolution envisagée**
> - Étendre la résolution du concept DOI à d'autres entrepôts que Zenodo (en utilisation l'API DataCite au lieu de l'API Zenodo).


## Corrections de métadonnées (phase `metadata_correction`)

Cette phase tourne après [`publishers_journals`](05-publishers-journals.md) — les revues sont typées, donc les règles dépendantes de la revue disposent de données fraîches — et avant le rattachement des publications, qui lit les colonnes corrigées. Trois sous-étapes :

1. **Par enregistrement** : mappe le type de document de la source vers le vocabulaire canonique, puis applique les règles de correction — propres à l'enregistrement ou dépendantes de la revue (par exemple un document de type « thèse » paru dans une revue est reclassé en article).
2. **Substitution Zenodo** : remplace le DOI de version par le concept DOI mis en cache à la phase précédente, pour que concept et versions convergent vers une seule publication.
3. **Par grappe** : regroupe les `source_publications` par DOI pour repérer les incohérences — par exemple un chapitre qui porte par erreur le DOI de l'ouvrage qui le contient — et neutralise le DOI fautif, afin que ces documents cessent d'être rapprochés.

La substitution Zenodo précède le regroupement par grappe, pour que celui-ci opère sur le concept DOI.

> **Évolution envisagée**
> - Élargir les corrections par grappe à d'autres cas (chapitre/chapitre, thèse mistypée en article).
