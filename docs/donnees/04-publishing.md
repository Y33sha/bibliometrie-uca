# Schéma `publishing`

*À jour le 2026-10-12.*

Revues, monographies, éditeurs et frais de publication.

## Tables

- **`journals`** : référentiel des revues.
- **`journal_issns`** : ISSN des revues.
- **`journal_name_forms`** : formes de noms normalisées pour reconnaître une revue (parallèle à `person_name_forms` et `structure_name_forms`).
- **`journal_doi_namespaces`** : espaces de noms DOI qui désignent une revue, recalculés par la phase `publishers_journals`.
- **`monographs`** : livres et volumes d'actes de congrès.
- **`publishers`** : référentiel des éditeurs.
- **`publisher_name_forms`** : formes de noms normalisées pour reconnaître un éditeur.
- **`doi_prefixes`** : cache préfixe DOI → agence d'enregistrement (Crossref / DataCite) et éditeur, alimenté par les phases `resolve_ra` et `publishers_journals`.
- **`apc_payments`** : données de paiement d'APC, reliées aux publications concernées, provenant d'un import CSV, voir [doc sources](../sources/10-imports-manuels.md#données-apc). Deux colonnes les rattachent aux structures : `lab_structure_id` pour le laboratoire, `budget_structure_id` pour le financeur — c'est ce dernier qui décide du classement « interne » d'un paiement. Aucun script du dépôt ne les renseigne : les imports chargent seulement du texte, et les rattachements viennent de chargements conduits hors du dépôt. Sur une base reconstruite depuis le seed, elles restent vides et les filtres APC par structure ne rendent rien.

## Propriété des tables

| Table | Auteur | Écrit par |
|---|---|---|
| `journals`, `journal_name_forms` | mixte | créés et enrichis par le pipeline ; édités et fusionnés en admin (`application/services/journals/commands.py`) |
| `publishers`, `publisher_name_forms` | mixte | créés et enrichis par le pipeline ; édités et fusionnés en admin (`application/services/publishers/commands.py`) |
| `doi_prefixes` | pipeline | phases `resolve_ra` et `publishers_journals` |
| `apc_payments` | import CSV | `interfaces/cli/imports/import_apc.py` |
