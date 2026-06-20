# Correction des métadonnées

La phase `metadata_correction` tourne après [`publishers_journals`](05-publishers-journals.md) — les revues sont typées, donc les règles dépendantes de la revue disposent de données fraîches — et juste avant le [rattachement des publications](07-publications.md), qui lit les colonnes corrigées. Elle prépare les `source_publications` pour que le matching s'appuie sur des valeurs propres et cohérentes.

Les corrections sont écrites sur les colonnes des `source_publications` ; la valeur source d'origine est conservée (dans `raw_metadata`) et chaque correction est recalculée à partir d'elle à chaque run — la passe est ainsi idempotente et se corrige d'elle-même, sans état à entretenir (un re-moissonnage ou un changement de type de revue est rattrapé au run suivant). Deux sous-étapes.

## Par enregistrement

Mappe le type de document de la source vers le vocabulaire canonique, puis applique les règles décidables sur un enregistrement seul — propres à l'enregistrement ou dépendantes de la revue. Par exemple : un document de type « thèse » paru dans une revue est reclassé en article ; un titre préfixé « Erratum: » est reclassé en erratum.

## Par grappe de DOI

Regroupe les `source_publications` partageant un même DOI et déduit, pour chaque groupe, le DOI que doit porter chacun de ses membres. Deux familles de cas :

1. **Convergence** — un entrepôt comme Zenodo attribue un DOI distinct à chaque version d'un dépôt, plus un **DOI concept** stable qui couvre toutes les versions. Le DOI concept est lu dans les métadonnées DataCite du dépôt (relation « est une version de ») et appliqué à toutes les `source_publications` portant un DOI de version : concept et versions convergent ainsi vers une seule publication.
2. **Divergence** — un DOI partagé par des documents en réalité distincts (un chapitre qui porte le DOI de l'ouvrage qui le contient ; des chapitres de titres différents portant le DOI de leur ouvrage hôte) est neutralisé sur le ou les mauvais documents, afin qu'ils cessent d'être rapprochés.

> **Évolution envisagée**
> - Élargir les cas par grappe (par exemple une thèse classée à tort comme article au sein d'une grappe).
