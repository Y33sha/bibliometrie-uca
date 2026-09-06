# Correction des métadonnées

*À jour le 2026-09-06.*

La phase `metadata_correction` prépare les `source_publications` pour que le [rattachement des publications](07-publications.md) s'appuie sur des valeurs propres. Elle tourne après [`publishers_journals`](05-publishers-journals.md), dont le typage des revues alimente les règles dépendantes de la revue.

Les corrections sont écrites sur les colonnes des `source_publications` ; la valeur d'origine est conservée dans `raw_metadata`, et chaque correction est recalculée à partir d'elle à chaque exécution. Un re-moissonnage ou un changement de type de revue est donc rattrapé à l'exécution suivante, sans état à entretenir.

1. **`journal_by_doi`** — renseigne `journal_id` lorsqu'il est vide et que le DOI permet d'identifier la revue.

2. **`correct_unary`** — mappe le type de document de la source vers le vocabulaire canonique, puis applique les règles de correction qui s'appliquent à un enregistrement isolé. Ces règles corrigent le type de document, le statut *open access* et les identifiants associés au document.
    *Exemples : un document typé « thèse » paru dans une revue est retypé en article, et perd les identifiants de thèse que la source lui avait attribués ; un article avec un titre préfixé « Erratum: » est retypé en erratum ; un statut `embargoed` dont la date d'embargo est échue passe à `green`.*

3. **`correct_by_cluster`** — rapproche les `source_publications` partageant un même DOI et déduit le DOI que doit porter chaque membre du groupe.

   - **Convergence** — un entrepôt comme Zenodo attribue un DOI distinct à chaque version d'un dépôt, plus un **DOI concept** stable couvrant toutes les versions. Le DOI concept est lu dans les métadonnées DataCite du dépôt (relation « est une version de »). Il remplace le DOI de version sur chaque `source_publication`, qui convergent ainsi vers une seule publication.
   - **Divergence** — un même DOI porté par des documents en réalité distincts, comme un chapitre qui porte le DOI de l'ouvrage qui le contient. Le DOI est retiré des documents qui le portent à tort, pour éviter qu'ils fusionnent.
