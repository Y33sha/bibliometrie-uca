# Schéma `publishing`

*À jour le 2026-10-25.*

Publications en série, monographies, éditeurs, plateformes et frais de publication.

## Tables

- **`serials`** : référentiel des publications en série : revues, collections d'ouvrages, recueils d'actes, serveurs de preprints, dépôts, médias. Le type (`serial_type`) les distingue. L'éditeur (`publisher_id`) se calcule d'après les publications.
- **`serial_issns`** : ISSN des publications en série, vérifiés sur les notices du Sudoc.
- **`serial_name_forms`** : formes de noms normalisées pour reconnaître une publication en série (parallèle à `person_name_forms` et `structure_name_forms`).
- **`serial_doi_namespaces`** : espaces de noms DOI qui désignent une publication en série, recalculés par la phase `publishing`.
- **`monographs`** : livres et volumes d'actes de congrès, rattachés à leur collection (`serial_id`).
- **`platforms`** : lieux qui hébergent des publications sans les publier : entrepôts, serveurs de preprints, plateformes d'éditeurs. Une plateforme se reconnaît par son identifiant OpenAlex. Une plateforme de la liste fermée des plateformes connues (`domain/platforms/registry.py`) en prend le nom et le type ; une autre prend le nom que lui donne OpenAlex et le type entrepôt.
- **`publishers`** : référentiel des éditeurs.
- **`publisher_name_forms`** : formes de noms normalisées pour reconnaître un éditeur.
- **`doi_prefixes`** : cache préfixe DOI → agence d'enregistrement (Crossref / DataCite) et éditeur, alimenté par les phases `resolve_ra` et `publishing`. Le titulaire d'un préfixe est l'éditeur d'origine de ses DOI.
- **`apc_payments`** : paiements de frais de publication, importés de fichiers CSV, voir [doc sources](../sources/10-imports-manuels.md#données-apc). `open_access_fee` distingue les APC des autres frais. `lab_structure_id` et `budget_structure_id` rattachent le paiement à son laboratoire et à son payeur. Un payeur du périmètre fait du paiement un paiement de l'établissement, seul retenu par les lectures.

## Propriété des tables

| Table | Auteur | Écrit par |
|---|---|---|
| `serials`, `serial_name_forms` | mixte | créés et enrichis par le pipeline ; édités et fusionnés en admin (`application/services/serials/commands.py`) ; éditeur recalculé par la phase `finalize` |
| `monographs` | pipeline | phase `normalize` ; fusionnées, rattachées à leur collection et typées par la phase `publishing` |
| `publishers`, `publisher_name_forms` | mixte | créés et enrichis par le pipeline ; édités et fusionnés en admin (`application/services/publishers/commands.py`) |
| `doi_prefixes` | pipeline | phases `resolve_ra` et `publishing` |
| `platforms` | pipeline | phase `normalize`, d'après les localisations (`pipeline/ingestion/common/locations.py`) |
| `apc_payments` | import CSV | `interfaces/cli/imports/import_apc.py` |
