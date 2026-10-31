# Correction des métadonnées

*À jour le 2026-10-30.*

La phase `metadata_correction` prépare les `source_records` pour que le [rattachement des publications](07-publications.md) s'appuie sur des valeurs propres. Elle tourne après [`publishing`](05-publishing.md) : le typage des revues alimente les règles dépendantes de la revue.

Les corrections sont écrites sur les colonnes des `source_records` ; la valeur d'origine est conservée dans `corrections`, et chaque correction est recalculée à partir d'elle à chaque exécution. Un identifiant retiré reste dans `source_record_identifiers`, avec la règle qui le retire (`removed_by`).

- **`serial_by_doi`** — renseigne `serial_id` lorsqu'il est vide et que les DOI actifs de l'enregistrement source tombent dans l'espace de noms d'une seule revue (`serial_doi_namespaces`, calculée par [`publishing`](05-publishing.md)).

- **`correct_unary`** — applique les règles de correction qui s'appliquent à un enregistrement isolé. Ces règles corrigent le type de document et les identifiants associés au document. Un dépôt HAL introuvable dans HAL (`failed_lookups`) est retiré des identifiants, des liens et des localisations.
    *Exemples : un document typé « thèse » paru dans une revue est retypé en article, et perd ses identifiants de thèse ; un article avec un titre préfixé « Erratum: » est retypé en erratum.*

- **`doi_targets`** — relie le DOI d'une forme secondaire au DOI de l'œuvre principale présente en base et connue de doi.org. Par exemple, un entrepôt comme Zenodo attribue un DOI à chaque version d'un dépôt, plus un **DOI concept** couvrant toutes les versions, que déclarent les métadonnées DataCite. Un DOI à suffixe de version a pour cible sa forme sans version quand c'est le DOI d'un enregistrement source, sinon sa version la plus récente en base. La [réconciliation](07-publications.md) lit la cible à la place du DOI : les formes d'une œuvre rejoignent sa publication.

- **`remove_identifiers`** — retire un DOI des enregistrements sources qui l'ont à tort. Un groupe réunit les enregistrements sources qui ont un même DOI.

   - **Documents distincts** — des documents distincts ont le même DOI : un chapitre d'un autre titre a le DOI de son ouvrage, une communication celui de son volume d'actes, un dépôt HAL celui d'un autre article. Le DOI reste aux seuls documents désignés.
   - **DOI inexistant** — un DOI que doi.org ne connaît pas (`failed_lookups`, source `doi_org`) est retiré de tous les enregistrements sources qui le citent.

- **`matchable`** — calcule `is_matchable` d'après les valeurs corrigées. Un enregistrement source écarté reste hors de la [réconciliation](07-publications.md) : préfixe DOI exclu, titre de paratexte, enregistrement DataCite d'une forme secondaire, enregistrement ScanR issu d'un dépôt HAL introuvable, enregistrement OpenAlex ou ScanR sans DOI, lien ni clé de confirmation.
