# Chantier — Table des ISSN

## Contexte

Une revue porte ses ISSN dans trois colonnes de `journals` (`issn`, `eissn`, `issnl`) et ses valeurs écartées dans `rejected_issns`. Sur 10 974 revues, 7 598 ont un `issn`, 8 283 un `eissn`, 8 945 un `issnl`, 213 des valeurs écartées ; 1 435 sont sans ISSN. 451 revues ont un ISSN-L distinct de leurs ISSN papier et électronique. Les revues portent 16 332 ISSN distincts ; aucun n'est partagé entre deux revues.

Limites du modèle :

- une revue a au plus un ISSN papier, un ISSN électronique et un ISSN-L. Un support CD-ROM, ou les ISSN d'une revue absorbée par une fusion, n'ont pas de place ;
- une valeur écartée n'a pas de motif : forme invalide, clé de contrôle fausse, ISSN annulé ou erroné selon le portail ISSN ;
- l'unicité d'un ISSN entre revues repose sur le code : `find_journal_by_issn_any` cherche dans trois colonnes et un tableau.

Le support que donnent les sources est peu fiable : ScanR et OpenAlex l'attribuent à l'ordre des valeurs. Seule la vérification Sudoc le connaît. Crossref, HAL, WoS et ScanR donnent l'ISSN papier et l'ISSN électronique sans ISSN-L ; OpenAlex et le Sudoc donnent l'ISSN-L. Aucune règle ne dépend du support : recherche, DOAJ, Sudoc et fusion comparent des valeurs.

## Décisions

Table `journal_issns`, une ligne par ISSN et par revue. Clé technique `id` ; unicité de `(issn, journal_id)`, NULL compris (`NULLS NOT DISTINCT`) :

| Colonne | Contenu |
|---|---|
| `issn` | Forme normalisée si la valeur est valide, valeur reçue sinon. |
| `journal_id` | Revue, facultative, `ON DELETE SET NULL`. Sans revue, l'ISSN a été vérifié au Sudoc et sa publication est absente de la base. |
| `support` | `print`, `electronic`, `other`, ou NULL si inconnu. |
| `linking` | ISSN-L. Une revue en a au plus un (index unique partiel sur `journal_id`). |
| `status` | `active`, `malformed`, `cancelled`, `related_title`, `supplement`, `unverified`. |
| `replaced_by` | ISSN qui remplace celui-ci : titre suivant, forme corrigée d'une valeur mal formée. |
| `sudoc_checked_at` | Date de la vérification au Sudoc. La progression se mesure en ISSN vérifiés. |

- Un même ISSN peut figurer dans plusieurs revues, pour ne perdre aucune information : les doublons se traitent à l'usage, et l'unicité de l'ISSN se rétablira a posteriori si elle s'avère possible. Les règles de fusion qui reposent sur un ISSN partagé restent en place. Des titres successifs sont soit des revues distinctes, chacune avec ses ISSN, soit une revue fusionnée : les ISSN des titres précédents rejoignent alors la revue gardée, avec le statut `related_title`.
- L'ISSN-L est un drapeau sur la ligne de sa valeur. Son arrivée pose le drapeau sur la ligne existante, sans réécrire son support.
- La recherche par ISSN ignore les lignes `malformed`.
- Une ligne sans revue, retrouvée par son ISSN, est rattachée à la revue que la normalisation crée.
- `unverified` : ISSN valide mis de côté avant la table, sans motif connu. La vérification Sudoc lui donne son statut.
- Le comportement est inchangé : mêmes rattachements entre publications, revues et monographies. L'API garde ses champs `issn`, `eissn` et `issnl`, dérivés des lignes.

## Phasage

### 1. Schéma

- [x] Migration `b3f6d2a8c417` : création de la table, report des trois colonnes, de `rejected_issns` et de `journals.sudoc_checked_at`, suppression des colonnes. Les valeurs sont mises en majuscules ; une valeur rejetée valide devient `unverified`, sans date de vérification : sa revue retourne dans la file Sudoc.
- [x] Domaine (`domain/journals/issns.py`) : `JournalIssn`, supports et statuts, validation d'une saisie manuelle, contradiction entre les ISSN de deux revues homonymes (fusion d'éditeurs).
- [x] Droits de l'API sur `journal_issns` dans `roles.sql`.
- [x] Application : migration, `roles.sql` rejoué, `schema.sql` régénéré. En base : 16 332 ISSN actifs, 21 mal formés, 199 à revérifier.

### 2. Code

- [x] Normalisation et recherche : `find_or_create_journal` ajoute à la revue trouvée les ISSN qu'elle ne porte pas, avec leur support ; `find_journal_by_issn_any` ignore les valeurs mal formées. Une ligne sans revue retrouvée par son ISSN est rattachée à la revue.
- [ ] `biblio.journal` des enregistrements : la liste complète des ISSN avec leur support, pour toutes les sources. `get_issns` (Crossref) garde un ISSN par support : 49 notices en déclarent deux du même support (revues IEEE). Renormalisation depuis le raw store pour les retrouver.
- [x] Vérification Sudoc (`issn_check`) : chaque ISSN reçoit support, statut et date. Plusieurs ISSN d'un même support restent actifs. Un titre précédent désigne l'ISSN-L de la revue comme successeur (`replaced_by`). Un ISSN d'une autre publication est gardé sans revue, vérifié : il ne ramène plus la revue dans la file.
- [x] Import DOAJ, fusion des doublons (règles sur les ISSN actifs et inactifs), suppression des revues vides.
- [x] Administration et lecture : repository, read models, API (`issns` en liste, `issn_details` au détail), frontend (liste, fiche publique, édition des ISSN en tableau).
- [x] Import des APC.

### 3. Documentation

- [ ] Mise à jour de `docs/agregats/journals.md` et des pages du pipeline qui décrivent les ISSN.

## Questions ouvertes

- **Fusion de revues.** Les ISSN de la revue absorbée rejoignent la revue gardée avec leur support et leur statut, à revérifier au Sudoc ; l'ISSN-L de la revue gardée l'emporte. À confirmer à l'usage.
