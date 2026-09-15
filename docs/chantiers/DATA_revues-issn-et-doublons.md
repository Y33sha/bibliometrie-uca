# Chantier — Revues : ISSN vérifiés, doublons et préfixes DOI

## Contexte

La table `journals` compte 13 815 revues. Leurs ISSN sont stockés dans trois colonnes (`issn`, `eissn`, `issnl`) tels que les sources les donnent. 25 valeurs sont invalides : clé de contrôle fausse, `(Internet)`, un ISBN. Certaines portent un `x` minuscule, qui empêche l'égalité avec la forme majuscule. 3 946 revues sont sans ISSN.

`find_or_create_journal` (`application/services/journals/core.py`) rapproche une revue par `openalex_id`, puis par ses ISSN cherchés dans les trois colonnes, puis par titre normalisé. Des doublons subsistent :

- 229 ISSN sont portés par plusieurs revues, soit 458 revues ;
- 1 491 revues partagent leur titre normalisé avec une autre.

La fusion de deux revues se fait à la main, dans l'administration des revues (`merge_journals`).

Le value object `ISSN` (`domain/publications/identifiers.py`) vérifie la clé de contrôle et produit la forme `NNNN-NNNC`. Il normalise `source_publications.external_ids.issn`, rempli par Crossref. Sur 9 397 couples (revue, ISSN d'un enregistrement Crossref rattaché à la revue), 24 sont discordants : l'ISSN de l'enregistrement est absent des ISSN de la revue.

Le script de maintenance `interfaces/cli/maintenance/seed_journals_doi_prefix.py` calcule `journals.doi_prefix` : le plus long préfixe commun des DOI des publications de la revue. La phase `metadata_correction` lit `doi_prefix` (`resolve_journal_by_doi`) pour rattacher à une revue un enregistrement qui a un DOI et aucun `journal_id`. 304 revues ont un `doi_prefix`. 13 partagent le même préfixe qu'une autre, 12 ont un préfixe qui préfixe celui d'une autre.

La phase `publishers_journals` interroge l'API OpenAlex Sources par `openalex_id` (`enrich_journals_from_openalex.py`, 8 661 revues) et importe le dump DOAJ.

### Sources de référence

| Source | Accès | Interrogation | Champs utiles | Licence |
|---|---|---|---|---|
| OpenAlex Sources | Clé gratuite | Filtre `issn:a\|b\|c`, 100 résultats par page | `display_name`, `issn_l`, `issn[]` sans le support | CC0 |
| Mir@bel `/api/titres` | Gratuit | Jusqu'à 200 ISSN par requête | `issn`, `issnl`, `support` (papier ou électronique), `statut`, `sudocppn`, éditeurs | Réutilisation libre avec mention de la source |
| Sudoc `issn2ppn`, puis notice `{ppn}.xml` | Gratuit, sans clé | Plusieurs ISSN par requête | ISSN, ISSN-L, titre, éditeur, ISSN de l'autre support | Licence ouverte Etalab |
| Crossref `/journals/{issn}` | Gratuit | Un ISSN par requête | `title`, `publisher`, `issn-type` (print ou electronic) | Libre |
| Portail ISSN | Payant (web service dès 8 976 € en 2024) | API | Tout, dont le statut « annulé » ou « erroné » | Commerciale |
| Journal Checker Tool | Gratuit | Un ISSN par requête | Titre, ISSN, éditeur, conformité au Plan S | CC BY 4.0 |

Couverture mesurée sur 199 revues tirées au hasard parmi celles à ISSN valide : 174 sont présentes dans le Sudoc, 106 dans Mir@bel. Une seule revue est présente dans Mir@bel et absente du Sudoc. 24 sont absentes des deux.

## Décisions

- Chaque écriture d'un ISSN de revue passe par le value object `ISSN`.
- La cohérence entre les ISSN d'un enregistrement et ceux de sa revue est vérifiée.
- Une source de référence, interrogée dans la phase `publishers_journals`, confirme les ISSN d'une revue. Elle fournit son titre de référence, son ISSN-L et ses ISSN par support. Le périmètre se limite aux revues qui ont au moins un ISSN.
- Deux revues de même ISSN-L de référence sont fusionnées automatiquement.
- Le sort du titre de référence est décidé après un audit des titres divergents.
- Le PPN Sudoc de la revue est stocké.
- La phase `publishers_journals` calcule `doi_prefix` à chaque exécution, pour toutes les revues.
- Un `doi_prefix` identifie une seule revue, indépendamment des autres revues : aucun DOI d'une autre revue ne commence par lui, et il n'est ni préfixe ni prolongement d'un autre `doi_prefix`. Il contient au moins un caractère après la barre oblique, car la partie qui précède identifie l'éditeur. Sans chaîne qui remplit ces conditions, `doi_prefix` est NULL.
- `resolve_journal_by_doi` est réécrit : au plus un `doi_prefix` correspond à un DOI.

## Phasage

### 1. Normalisation des ISSN des revues

- [ ] Les écritures d'ISSN (`find_or_create_journal`, import DOAJ, édition dans l'administration) passent par le value object `ISSN`. Une valeur invalide est écartée et journalisée.
- [ ] La recherche par ISSN (`find_journal_by_issn_any`) porte sur la valeur normalisée.
- [ ] Script oneshot : normalisation du stock, liste des valeurs écartées.

### 2. Source de référence

- [ ] Choix de la source.
- [ ] Migration : PPN, ISSN-L de référence, titre de référence, date de vérification.
- [ ] Sous-étape de `publishers_journals` : interrogation par lot des revues à vérifier, enregistrement des champs de référence.
- [ ] Mesure : revues confirmées, ISSN inconnus de la source.
- [ ] Audit des titres divergents : nombre et nature des différences.

### 3. Cohérence des ISSN

- [ ] Contrôle des ISSN des enregistrements face à ceux de leur revue vérifiée.
- [ ] Traitement des discordances.

### 4. Fusion des revues séparées à tort

- [ ] Revues partageant un ISSN-L de référence : fusion automatique par `merge_journals`.
- [ ] Revues de même titre sans ISSN commun : proposées dans l'administration des revues.

### 5. Préfixes DOI des revues

- [ ] Sous-étape de `publishers_journals` qui calcule `doi_prefix` pour toutes les revues : plus long préfixe commun des DOI de la revue, retenu s'il identifie la revue.
- [ ] Contrainte d'unicité sur `doi_prefix`.
- [ ] Recalcul du stock, dont les 25 revues à préfixe identique ou emboîté.
- [ ] Réécriture de `resolve_journal_by_doi`.
- [ ] Retrait de `seed_journals_doi_prefix` et de ses tests.

## Questions ouvertes

- **Source.** Le Sudoc est pressenti, comme source la plus étendue. Faut-il une seconde source pour les revues absentes du Sudoc (12 % de l'échantillon) : OpenAlex, déjà interrogée, ou Crossref ?
- **Titre.** Hypothèse à tester sur l'audit : le titre actuel rejoint les formes de nom, le titre de référence remplace `title`.
- **Discordances.** Un enregistrement dont l'ISSN désigne une autre revue est-il rattaché à cette revue automatiquement, ou signalé ?
