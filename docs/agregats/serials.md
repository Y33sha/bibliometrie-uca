# Publications en série — cycle de vie

*À jour le 2026-09-06.*

Une publication en série (`serial`) est un support de publication : revue, collection d'ouvrages, plateforme de livres électroniques, recueil d'actes, serveur de preprints, dépôt, média. Près de deux revues sur cinq n'ont aucun ISSN, et autant portent plusieurs formes de leur titre selon la source qui les décrit ; `serial_name_forms` enregistre ces formes. `domain/serials/serial.py` définit sa structure ; la résolution, la fusion et l'enrichissement vivent dans les services et leurs adaptateurs SQL.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `serials` | La revue | `title` / `title_normalized`, `publisher_id`, `openalex_id` (unique), `serial_type`, `oa_model`, `is_in_doaj`, `apc_amount` / `apc_currency`, `doaj_payload`, `publication_count` |
| `serial_issns` | ISSN des revues ; sans revue, ISSN vérifié d'une publication absente de la base | `issn`, `serial_id`, `support`, `linking` (ISSN-L), `status`, `replaced_by`, `sudoc_checked_at`, unicité `(issn, serial_id)` |
| `serial_name_forms` | Formes de nom permettant de reconnaître une revue par son titre | `serial_id`, `form_normalized`, `publisher_id`, unicité `(form_normalized, publisher_id)` |
| `serial_doi_namespaces` | Espaces de noms DOI qui désignent une revue, recalculés par `publishing` | `namespace` (clé), `serial_id`, `dois`, `share` (part des DOI de l'espace qui portent la revue) |

Les tables qui référencent une revue ont des politiques de suppression différentes : `serial_name_forms` et `serial_doi_namespaces` disparaissent avec elle, `apc_payments.serial_id` repasse à nul, tandis que `publications.serial_id` et `source_records.serial_id` n'autorisent aucune suppression tant qu'ils pointent dessus.

## Écriture par le pipeline

**Création et résolution (`normalize`).** Les six normaliseurs appellent `find_or_create_serial` (`pipeline/transformation/publishing/find_or_create.py`), qui essaie successivement l'`openalex_id`, puis les ISSN (`find_serial_by_issn_any`), puis le titre (`find_serial_by_name_form`, qui préfère les revues à ISSN en ligne), et crée la revue en dernier recours avec sa forme de nom. La recherche par titre se limite aux formes de l'éditeur du document ou sans éditeur, et la forme de nom enregistre cet éditeur. `enrich_serial` complète au passage les champs vides, sans jamais écraser une valeur existante, et la revue reçoit les ISSN qu'elle ne porte pas. L'enregistrement source reçoit le `serial_id` de la revue trouvée ou créée. `normalize_openalex` déduit en outre l'`oa_model` du caractère ouvert de la source.

**Enrichissement du référentiel (`publishing`).** L'orchestrateur enchaîne, pour les sources dont les identifiants sont renseignés, la résolution des éditeurs, l'enrichissement depuis OpenAlex — frais de publication et type de revue pour celles restées indéterminées — puis l'import du référentiel DOAJ, qui renseigne `doaj_payload` et `is_in_doaj`. Chaque sous-étape porte ses requêtes. `SerialStore` (`pipeline/transformation/publishing/serials/store.py`) regroupe la recherche, la création et l'enrichissement des revues.

## Écriture par l'API — édition manuelle

Routeur `interfaces/api/routers/serials.py`, commandes dans `application/services/serials/commands.py`, adaptateur `PgSerialRepository`.

**Éditer une revue** (`PUT /api/serials/{id}`). Le repository re-dérive `title_normalized` à l'enregistrement. Si le type de revue change, `requalify_publications_for_serial` rejoue immédiatement le type de document de toutes ses publications et consigne un événement `journal.type_requalified`.

**Fusionner deux revues** (`POST /api/serials/{id}/merge`). `merge_serial_into` repointe successivement `publications`, `source_records`, `apc_payments` et `serial_name_forms`, puis recale le compteur de publications et l'éditeur de la revue conservée. Les ISSN de la source rejoignent la cible, à revérifier dans le Sudoc. Chaque table est traitée explicitement parce qu'aucune suppression en cascade ne peut faire le travail : la base refuse de supprimer une revue tant qu'une publication la référence.

**Prévisualiser un changement de type** (`GET /api/serials/{id}/type-change-impact`). Le chemin d'écriture réel est exécuté puis annulé, ce qui donne l'impact exact sans rien modifier.

## Lecture par le pipeline

**Éditeur de la revue.** `serials.publisher_id` se calcule d'après les publications de la revue (`pipeline/transformation/publishing/serials/serial_publishers.py`) : l'éditeur le plus fréquent parmi ses publications de la dernière année qui en a un ; à égalité, le plus fréquent sur toutes les années ; à égalité encore, le plus petit identifiant. La phase `finalize` le recalcule à chaque run, une fusion de revues pour la revue conservée.

**Compteur de publications.** `pipeline/transformation/publishing/publication_counts.py` recalcule `serials.publication_count`, puis celui des éditeurs. La phase `finalize` le recalcule en totalité, une fois le périmètre posé ; une fusion administrative ne recalcule que les revues concernées.

**Type de revue.** `refresh_from_sources` lit `serial_type_of` pour rejouer les règles de type de document qui en dépendent.

## Lecture par l'API

Port `application/ports/read_models/serials_queries.py`, adaptateur `PgSerialQueries`.

| Point d'entrée | Ce qu'il sert |
|---|---|
| `GET /api/serials`, `/facets` | Liste filtrable et facettes ; la recherche porte sur le titre et sur tous les ISSN, et le filtre « avec publications » s'appuie sur le compteur `publication_count` |
| `GET /api/serials/facets/entities` | Facette éditeur : les premiers éditeurs sous les filtres actifs, décomptés en revues, cherchables par nom — ils sont trop nombreux pour être tous proposés |
| `GET /api/serials/{id}`, `/{id}/dashboard` | Détail de la revue ; le tableau de bord signale les publications hors du cadre annoncé par la revue (`domain/serials/expected.py`) et recompte l'appartenance au périmètre en direct |
| `GET /api/serials/types`, `/oa-models` | Libellés des vocabulaires de type de revue et de modèle *open access*, définis dans `domain/serials/serial.py` |
