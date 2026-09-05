# Éditeurs — cycle de vie

*À jour le 2026-09-04.*

Un éditeur porte les revues et reçoit les frais de publication. Il se reconnaît par son identifiant OpenAlex quand une source en fournit un, sinon par son nom, via les formes enregistrées dans `publisher_name_forms`. `domain/publishers/publisher.py` définit sa structure — nom, pays, identifiant OpenAlex, type ; le rapprochement, la fusion et l'enrichissement vivent dans les services et leurs adaptateurs SQL.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `publishers` | L'éditeur | `name` / `name_normalized`, `country`, `openalex_id` (unique), `publisher_type`, `pub_count` |
| `publisher_name_forms` | Formes de nom permettant de reconnaître un éditeur | `publisher_id`, `form_normalized` |
| `doi_prefixes` | Correspondance entre un préfixe de DOI et un éditeur | `publisher_id`, `crossref_member_id`, `datacite_client_symbol`, `publisher_checked_at` |

Une forme de nom d'éditeur est unique dans toute la table, là où une forme de titre de revue n'est unique que pour un éditeur donné : deux éditeurs ne peuvent pas revendiquer la même forme de nom.

Trois tables extérieures référencent un éditeur : `journals.publisher_id`, `journal_name_forms.publisher_id` et `apc_payments.publisher_id`.

## Écriture par le pipeline

**Rattachement (`normalize`).** Chaque normaliseur appelle `find_or_create_publisher` (`application/services/publishers/core.py`), qui essaie d'abord l'identifiant OpenAlex, puis se rabat sur la forme de nom — reconnue ou créée — avant de transmettre l'éditeur à la création de la revue. Seul OpenAlex fournit un identifiant d'éditeur.

**Résolution par préfixe de DOI (`publishers_journals`).** Pour chaque préfixe non encore résolu, `resolve_publishers` détermine l'agence d'enregistrement du DOI, interroge Crossref ou DataCite, enregistre les métadonnées obtenues, reconnaît ou crée l'éditeur par sa forme de nom — la même opération que dans `normalize` — et renseigne `doi_prefixes.publisher_id`. Un préfixe n'est interrogé qu'une fois : `publisher_checked_at` retient la tentative, qu'elle ait abouti ou non.

**Enrichissement du pays, hors pipeline.** `interfaces/cli/maintenance/enrich_publishers.py` renseigne le pays depuis OpenAlex, et seulement là où il est absent : une valeur saisie à la main est conservée.

## Écriture par l'API — édition manuelle

Routeur `interfaces/api/routers/publishers.py`, adaptateur `PgPublisherRepository`.

**Éditer un éditeur** (`PUT /api/publishers/{id}`). Seuls les champs transmis sont modifiés ; le repository re-dérive `name_normalized` depuis le nom.

**Fusionner deux éditeurs** (`POST /api/publishers/{id}/merge`). L'opération est refusée si les deux éditeurs portent des ISSN divergents, ou si la fusion créerait un doublon interne. Les revues que les deux se partagent sous un même titre sont fusionnées d'abord, puis `merge_publisher_into` repointe `journals`, `journal_name_forms` et `apc_payments` avant de recaler les compteurs.

## Lecture par le pipeline

`journals.pub_count` est recalculé d'abord, puis `publishers.pub_count` en est la somme. La phase `authorships` fait ce calcul en totalité une fois le périmètre posé ; une fusion administrative ne recalcule que les éditeurs concernés.

## Lecture par l'API

Port `application/ports/read_models/publishers_queries.py`, adaptateur `PgPublisherQueries`.

| Point d'entrée | Ce qu'il sert |
|---|---|
| Liste et facettes | Éditeurs filtrables, avec leur nombre de revues, leur nombre de publications et leurs préfixes de DOI ; facettes par type et par pays |
| Détail et tableau de bord | Types des revues de l'éditeur, types de document et statuts d'accès de ses publications du périmètre, sujets |

## Points d'attention

**La fusion écrit dans des tables d'autres agrégats.** `merge_publisher_into` met à jour `journals`, `journal_name_forms` et `apc_payments` en SQL littéral, hors du périmètre que le repository des éditeurs déclare — comme la fusion de revues, et pour la même raison : repointer les dépendants est le contenu même de l'opération, et elle demande une transaction unique.
