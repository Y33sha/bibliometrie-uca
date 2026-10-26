# Publications en série — cycle de vie

*À jour le 2026-10-25.*

Une publication en série (`serial`) réunit des documents sous un même titre : revue, collection d'ouvrages, recueil d'actes, serveur de preprints, dépôt, média. Son type (`serial_type`) les distingue ; une revue est une publication en série de type `journal`. Près de deux publications en série sur cinq n'ont aucun ISSN, et autant ont plusieurs formes de leur titre selon la source qui les décrit ; `serial_name_forms` enregistre ces formes. `domain/serials/serial.py` définit sa structure ; la résolution, la fusion et l'enrichissement vivent dans les services et leurs adaptateurs SQL.

Un livre ou un volume d'actes est une monographie, rattachée à sa collection par `monographs.serial_id`. Une plateforme d'ebooks n'est pas une publication en série : son titre (« ENS Éditions eBooks ») n'est le titre d'aucun conteneur.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `serials` | La publication en série | `title` / `title_normalized`, `publisher_id`, `openalex_id` (unique), `serial_type`, `oa_model`, `is_in_doaj`, `doaj_payload`, `publication_count`, `manual_fields` |
| `serial_issns` | ISSN des publications en série ; sans publication en série, ISSN vérifié d'une publication absente de la base | `issn`, `serial_id`, `support`, `linking` (ISSN-L), `status`, `replaced_by`, `sudoc_checked_at`, unicité `(issn, serial_id)` |
| `serial_name_forms` | Formes de nom permettant de reconnaître une publication en série par son titre | `serial_id`, `form_normalized`, `publisher_id`, unicité `(form_normalized, publisher_id)` |
| `serial_doi_namespaces` | Espaces de noms DOI qui désignent une publication en série, recalculés par `publishing` | `namespace` (clé), `serial_id`, `dois`, `share` (part des DOI de l'espace qui la désignent) |

Les tables qui référencent une publication en série ont des politiques de suppression différentes : `serial_name_forms` et `serial_doi_namespaces` disparaissent avec elle, `apc_payments.serial_id` et `monographs.serial_id` repassent à nul, tandis que `publications.serial_id` et `source_records.serial_id` n'autorisent aucune suppression tant qu'ils pointent dessus.

## Écriture par le pipeline

**Création et résolution (`normalize`).** Les six normaliseurs appellent `find_or_create_serial` (`pipeline/transformation/publishing/find_or_create.py`), qui essaie successivement l'`openalex_id`, puis les ISSN (`find_serial_by_issn_any`), puis le titre (`find_serial_by_name_form`, qui préfère les entrées à ISSN en ligne), et crée la publication en série en dernier recours avec sa forme de nom. La recherche par titre se limite aux formes de l'éditeur du document ou sans éditeur, et la forme de nom enregistre cet éditeur. `enrich_serial` complète au passage les champs vides, sans jamais écraser une valeur existante, et l'entrée reçoit les ISSN qui lui manquent. L'enregistrement source reçoit le `serial_id` de l'entrée trouvée ou créée. `normalize_openalex` déduit en outre l'`oa_model` du caractère ouvert de la source.

**Enrichissement du référentiel (`publishing`).** Les sous-étapes de la phase ([publishing](../pipeline/05-publishing.md)) vérifient les ISSN dans le Sudoc, fusionnent les doublons et calculent les espaces de noms DOI. Elles posent aussi le type : celui de la source OpenAlex pour une entrée de type inconnu, `proceedings` d'après les documents ou le titre, `journal` pour une entrée de type inconnu qui contient surtout des articles, `book_series` pour une collection de monographies, `journal` pour une entrée présente dans le DOAJ. L'import du DOAJ renseigne `doaj_payload` et `is_in_doaj`, et OpenAlex les frais de publication. Chaque sous-étape contient ses requêtes. `SerialStore` (`pipeline/transformation/publishing/serials/store.py`) regroupe la recherche, la création et l'enrichissement des publications en série.

**Éditeur (`finalize`).** `serials.publisher_id` se calcule d'après les publications (`pipeline/transformation/publishing/serials/serial_publishers.py`) : l'éditeur le plus fréquent parmi ses publications de la dernière année qui en a un ; à égalité, le plus fréquent sur toutes les années ; à égalité encore, le plus petit identifiant. La phase `finalize` le recalcule à chaque run, une fusion pour l'entrée conservée.

**Compteur de publications (`finalize`).** `pipeline/transformation/publishing/publication_counts.py` recalcule `serials.publication_count`, puis celui des éditeurs. La phase `finalize` le recalcule en totalité, une fois le périmètre posé ; une fusion administrative recalcule seulement les entrées concernées.

**Suppression (`finalize`).** Une publication en série sans enregistrement source, sans publication, sans monographie et sans paiement APC est supprimée, avec ses formes de nom.

## Écriture par l'API — édition manuelle

Routeur `interfaces/api/routers/serials.py`, commandes dans `application/services/serials/commands.py`, adaptateur `PgSerialRepository`. Un titre, des ISSN, un type ou un modèle open access saisis à la main sont marqués dans `manual_fields`, et le pipeline les laisse en l'état.

**Éditer une publication en série** (`PUT /api/serials/{id}`). Le repository re-dérive `title_normalized` à l'enregistrement. Si le type change, `requalify_publications_for_serial` rejoue immédiatement le type de document de toutes ses publications et consigne un événement `serial.type_requalified`.

**Fusionner deux publications en série** (`POST /api/serials/{id}/merge`). `merge_serial_into` repointe successivement `publications`, `source_records`, `apc_payments`, `monographs` et `serial_name_forms`, puis recale le compteur de publications et l'éditeur de l'entrée conservée. Les ISSN de la source rejoignent la cible, à revérifier dans le Sudoc. Chaque table est traitée explicitement parce qu'aucune suppression en cascade ne peut faire le travail : la base refuse de supprimer une entrée tant qu'une publication la référence.

**Prévisualiser un changement de type** (`GET /api/serials/{id}/type-change-impact`). Le chemin d'écriture réel est exécuté puis annulé, ce qui donne l'impact exact sans rien modifier.

## Lecture par le pipeline

**Type.** `refresh_from_sources` lit `serial_type_of` pour rejouer les règles de type de document qui en dépendent : un média donne `media`, un recueil d'actes `conference_paper`, un serveur de preprints `preprint` (`domain/source_records/metadata_correction/rules.py`).

**Espaces de noms DOI.** La phase `metadata_correction` rattache à une publication en série l'enregistrement source sans `serial_id` dont le DOI tombe dans un de ses espaces de noms.

## Lecture par l'API

Lecture `infrastructure/read_models/serials/`, classe `SerialQueries`. L'administration nomme l'entité « Publications en série » (`/admin/serials`) ; les pages publiques gardent « Revues » (`/journals`).

| Point d'entrée | Ce qu'il sert |
|---|---|
| `GET /api/serials`, `/facets` | Liste filtrable et facettes ; la recherche porte sur le titre et sur tous les ISSN, et le filtre « avec publications » s'appuie sur le compteur `publication_count` |
| `GET /api/serials/facets/entities` | Facette éditeur : les premiers éditeurs sous les filtres actifs, décomptés en publications en série, cherchables par nom — ils sont trop nombreux pour être tous proposés |
| `GET /api/serials/{id}`, `/{id}/dashboard` | Détail ; le tableau de bord signale les publications hors du cadre annoncé par le type et le modèle open access (`domain/serials/expected.py`) et recompte l'appartenance au périmètre en direct |
| `GET /api/serials/types`, `/oa-models` | Libellés des vocabulaires de type et de modèle *open access*, définis dans `domain/serials/serial.py` |
