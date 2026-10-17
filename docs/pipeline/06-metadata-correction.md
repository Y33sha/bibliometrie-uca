# Correction des métadonnées

*À jour le 2026-09-19.*

La phase `metadata_correction` prépare les `source_publications` pour que le [rattachement des publications](07-publications.md) s'appuie sur des valeurs propres. Elle tourne après [`publishers_journals`](05-publishers-journals.md), dont le typage des revues alimente les règles dépendantes de la revue.

Les corrections sont écrites sur les colonnes des `source_publications` ; la valeur d'origine est conservée dans `raw_metadata`, et chaque correction est recalculée à partir d'elle à chaque exécution.

1. **`journal_by_doi`** — renseigne `journal_id` lorsqu'il est vide et que le DOI tombe dans l'espace de noms d'une revue (`journal_doi_namespaces`, calculée par [`publishers_journals`](05-publishers-journals.md)).

2. **`correct_unary`** — mappe le type de document de la source vers le vocabulaire unifié, et la langue vers le code du référentiel `languages` d'après les formes de `language_forms`. Une langue absente du référentiel, comme `und`, devient NULL. La passe applique ensuite les règles de correction qui s'appliquent à un enregistrement isolé. Ces règles corrigent le type de document, le statut *open access* et les identifiants associés au document.
    *Exemples : un document typé « thèse » paru dans une revue est retypé en article, et perd les identifiants de thèse que la source lui avait attribués ; un article avec un titre préfixé « Erratum: » est retypé en erratum ; un statut `embargoed` dont la date d'embargo est échue passe à `green`.*

3. **`correct_by_cluster`** — rapproche les `source_publications` partageant un même DOI et déduit le DOI que doit porter chaque membre du groupe.

   - **Convergence** — un entrepôt comme Zenodo attribue un DOI distinct à chaque version d'un dépôt, plus un **DOI concept** stable couvrant toutes les versions. Le DOI concept est lu dans les métadonnées DataCite du dépôt (relation « est une version de »). Il remplace le DOI de version sur chaque `source_publication`, qui convergent ainsi vers une seule publication.
   - **Divergence** — des documents distincts ont le même DOI : un chapitre a le DOI de son ouvrage, une communication celui de son volume d'actes, un dépôt HAL celui d'un autre article. Le dépôt HAL n'a alors aucun auteur commun avec la notice Crossref, et moins de 35 % des mots du titre. Le DOI est retiré des documents qui l'ont à tort, pour éviter qu'ils fusionnent. Les documents qui gardent le DOI perdent aussi les dépôts HAL qu'ils partagent avec les autres, comme la notice OpenAlex d'un volume qui recopie le dépôt d'une communication.
   - **DOI inexistant** — un DOI que doi.org ne connaît pas (`failed_lookups`, source `doi_org`) est retiré de toutes les notices qui le citent. Il leur revient dès que doi.org le connaît.
