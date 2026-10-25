# Schéma `publishing`

*À jour le 2026-10-12.*

Revues, monographies, éditeurs et frais de publication.

## Tables

- **`serials`** : référentiel des revues.
- **`serial_issns`** : ISSN des revues, vérifiés sur les notices du Sudoc.
- **`serial_name_forms`** : formes de noms normalisées pour reconnaître une revue (parallèle à `person_name_forms` et `structure_name_forms`).
- **`serial_doi_namespaces`** : espaces de noms DOI qui désignent une revue, recalculés par la phase `publishing`.
- **`monographs`** : livres et volumes d'actes de congrès.
- **`platforms`** : lieux qui hébergent des publications (entrepôts, serveurs de preprints, plateformes d'éditeurs), nommés d'après leur source OpenAlex. Le type vient de la liste fermée des plateformes connues (`domain/platforms/registry.py`), à défaut entrepôt.
- **`publishers`** : référentiel des éditeurs.
- **`publisher_name_forms`** : formes de noms normalisées pour reconnaître un éditeur.
- **`doi_prefixes`** : cache préfixe DOI → agence d'enregistrement (Crossref / DataCite) et éditeur, alimenté par les phases `resolve_ra` et `publishing`.
- **`apc_payments`** : paiements de frais de publication, importés de fichiers CSV, voir [doc sources](../sources/10-imports-manuels.md#données-apc). `open_access_fee` distingue les APC des autres frais. `lab_structure_id` et `budget_structure_id` rattachent le paiement à son laboratoire et à son payeur. Un payeur du périmètre fait du paiement un paiement de l'établissement, seul retenu par les lectures.

## Propriété des tables

| Table | Auteur | Écrit par |
|---|---|---|
| `serials`, `serial_name_forms` | mixte | créés et enrichis par le pipeline ; édités et fusionnés en admin (`application/services/serials/commands.py`) |
| `publishers`, `publisher_name_forms` | mixte | créés et enrichis par le pipeline ; édités et fusionnés en admin (`application/services/publishers/commands.py`) |
| `doi_prefixes` | pipeline | phases `resolve_ra` et `publishing` |
| `platforms` | pipeline | phase `normalize`, d'après les localisations OpenAlex et HAL et les identifiants arXiv et PMCID (`pipeline/ingestion/common/locations.py`) ; une plateforme connue (`domain/platforms/registry.py`) en prend le nom et le type |
| `apc_payments` | import CSV | `interfaces/cli/imports/import_apc.py` |
