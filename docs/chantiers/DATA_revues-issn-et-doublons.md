# Chantier — Revues : ISSN vérifiés, doublons et préfixes DOI

## Contexte

La table `journals` compte 13 815 revues. Leurs ISSN sont stockés dans trois colonnes (`issn`, `eissn`, `issnl`) tels que les sources les donnent. 25 valeurs sont invalides : clé de contrôle fausse, `(Internet)`, un ISBN. Certaines portent un `x` minuscule, qui empêche l'égalité avec la forme majuscule. 3 946 revues sont sans ISSN.

`find_or_create_journal` (`application/services/journals/core.py`) rapproche une revue par `openalex_id`, puis par ses ISSN cherchés dans les trois colonnes, puis par titre normalisé. Des doublons subsistent :

- 229 ISSN sont portés par plusieurs revues, soit 288 revues ;
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

Mesure sur 1 000 ISSN de revues tirés au hasard : 832 sont présents dans le Sudoc, et chacun renvoie une seule notice. 826 notices donnent l'ISSN-L (`011$f`), 831 le support (`182$c` : `n` papier, `c` électronique). La zone `452` (ISSN de l'autre support) figure dans 186 notices, `011$y` (ISSN annulé) dans 16. Face au support Sudoc, la colonne `issn` contient 206 ISSN papier et 279 électroniques, `eissn` 11 papier et 451 électroniques. `issnl` diffère de l'ISSN-L du Sudoc pour 21 revues sur 511.

## Décisions

- Chaque écriture d'un ISSN de revue passe par le value object `ISSN`.
- La cohérence entre les ISSN d'un enregistrement et ceux de sa revue est vérifiée.
- Le Sudoc, interrogé dans la phase `publishers_journals`, sert de source de référence. Il confirme les ISSN d'une revue et fournit son titre, son ISSN-L et le support de chaque ISSN. Le périmètre se limite aux revues qui ont au moins un ISSN.
- L'ISSN-L du Sudoc est écrit dans `issnl`. Deux revues de même ISSN-L sont fusionnées automatiquement.
- Ordre de traitement : cohérence des ISSN de chaque revue, fusion des revues de même ISSN-L, puis placement et complément des ISSN. Un ISSN d'une autre publication est rangé parmi les ISSN rejetés et signalé.
- Le titre en base reste la référence. La notice Sudoc porte le titre propre, sans le sous-titre, donc elle donne souvent un titre plus court.
- Les ISSN rejetés (`journals.rejected_issns`) sont soit fautifs, tels que reçus des sources, soit périmés (autre support comme le CD-ROM, ISSN annulé, titre précédent ou suivant), soit d'une autre publication. Ils servent au rapprochement. La sous-étape Sudoc corrige les fautifs.
- La phase `publishers_journals` calcule `doi_prefix` à chaque exécution, pour toutes les revues.
- Un `doi_prefix` identifie une seule revue, indépendamment des autres revues : aucun DOI d'une autre revue ne commence par lui, et il n'est ni préfixe ni prolongement d'un autre `doi_prefix`. Il contient au moins un caractère après la barre oblique, car la partie qui précède identifie l'éditeur. Sans chaîne qui remplit ces conditions, `doi_prefix` est NULL.
- `resolve_journal_by_doi` est réécrit : au plus un `doi_prefix` correspond à un DOI.
- Un chapitre ou un livre crée ou retrouve une revue seulement s'il porte un ISSN, celui de sa collection. Sans ISSN, son conteneur est le livre lui-même, dont le titre va dans `container_title`, sauf si un recueil d'actes existant porte ce titre. Un article de congrès garde son recueil d'actes, avec ou sans ISSN.
- Le titre type en recueil d'actes une revue sans ISSN, quel que soit son type : une édition datée, ou « proceedings » sans société savante, académie ni institution. *PNAS* et *Proceedings of the Royal Society B* sont des revues.
- Le typage par les documents s'applique aux seuls conteneurs `unknown`.

## Phasage

### 1. Normalisation des ISSN des revues

- [x] Les écritures d'ISSN (`find_or_create_journal`, édition dans l'administration) passent par le value object `ISSN`. Dans le pipeline, une valeur invalide est écartée et journalisée. Dans l'administration, elle est refusée.
- [x] La recherche par ISSN (`find_journal_by_issn_any`, import DOAJ) porte sur la valeur normalisée.
- [x] Script oneshot `backfill_normalize_journal_issns` : normalisation du stock, liste des valeurs écartées.

### 2. Source de référence

- [x] Choix de la source : le Sudoc.
- [x] Migration : `journals.rejected_issns`, `journals.sudoc_checked_at`.
- [x] `find_or_create_journal` conserve les ISSN invalides dans `rejected_issns`. Script oneshot : réinjection des 25 valeurs supprimées par `backfill_normalize_journal_issns`.
- [x] Lecture des notices Sudoc : ISSN, ISSN-L, support, ISSN annulés, ISSN de l'autre support.
- [x] Sous-étape de `publishers_journals`, pour les revues à vérifier : cohérence des ISSN de chaque revue, correction des ISSN rejetés, écriture de l'ISSN-L dans `issnl`, placement de chaque ISSN dans la colonne de son support. Une revue qui reçoit un ISSN nouveau redevient à vérifier.
- [x] Premier passage : 8 219 revues vérifiées, 7 153 présentes dans le Sudoc, 6 712 modifiées. Son journal révèle trois défauts des règles : un CD-ROM codé comme électronique, un troisième ISSN sans colonne, des ISSN-L différents entre les notices papier et en ligne d'une même revue.
- [x] Règles revues : support lu dans `183$a`, regroupement des ISSN par ISSN-L ou par `452`, ISSN périmés rangés parmi les rejetés, rapprochement sur les ISSN rejetés.
- [x] Second passage sur les 255 revues signalées. Il révèle des retraits à tort (variantes de titre, CD-ROM, titres précédents) et des ISSN papier sans notice mis de côté faute de colonne.
- [x] Règles revues : plus de retrait, un ISSN d'une autre publication rejoint les rejetés ; réunion du papier et de l'en ligne de titres emboîtés ; support indiqué par `452$t`.
- [x] Troisième passage : 38 revues signalées. Il révèle l'arrêt du papier au profit de l'en ligne codé comme un changement de titre, et des ISSN d'un même support laissés en place.
- [x] Règles revues : changement de support distingué d'un changement de titre, égalité départagée par la succession des titres, ISSN d'un même support départagés par l'ISSN-L, CD-ROM reconnu à son titre.
- [x] Quatrième passage : 14 revues signalées, dont 8 égalités ou ambiguïtés propres au Sudoc. Il révèle des ISSN de la revue bloqués parmi les rejetés par les passages précédents.
- [x] Règles revues : ISSN rejetés valides réexaminés, CD-ROM hors des groupes, changement de support reconnu sans notice par la mention de support.
- [x] Cinquième passage : 2 revues signalées, toutes deux sur un titre précédent réel. Les ISSN retirés par les premiers passages ont retrouvé leurs colonnes. 161 revues gardent un ISSN rejeté valide : supplément, titre parallèle, notice en double ou publication distincte.
- [x] Audit des titres divergents sur 300 revues, dont 270 présentes dans le Sudoc : 223 titres identiques, 23 plus complets en base, 9 plus complets dans la notice, 8 divergents, 7 proches. Les divergences sont des titres abrégés en base (« EPL », « Can J Cardiol »), des titres précédents et des traductions.

### 3. Cohérence des ISSN

- [x] Mesure : 49 couples (revue, ISSN d'un enregistrement) discordants, sur 156 documents. 25 ISSN sont ceux de la revue elle-même, 19 sont absents du Sudoc, 5 désignent une autre revue de la base, dont deux doublons à fusionner.
- [x] Les ISSN des enregistrements d'une revue, absents de ses ISSN, entrent dans la vérification Sudoc : ils complètent la revue quand la notice l'y rattache, et rejoignent les ISSN rejetés sinon. L'enregistrement reste rattaché à sa revue.

### 4. Fusion des revues séparées à tort

- [x] Audit : 140 groupes de revues partagent un ISSN-L vérifié, toutes des paires, pour 522 publications. Les cinq groupes à titres différents sont bien la même revue : abréviation, graphie, titre de volume WoS. 14 valeurs d'ISSN sont partagées par des revues d'ISSN-L différents, dont treize sont la même revue en double et une désigne deux publications distinctes.
- [x] Revues partageant un ISSN-L de référence : fusion automatique par `merge_journals`, sous-étape de `publishers_journals`.
- [x] Revues partageant un ISSN de colonne sous un titre emboîté : même fusion automatique. Elle couvre dix des treize doublons à ISSN-L différents. L'éditeur ne sert pas de contrôle : deux revues sur treize seulement partagent la même fiche d'éditeur, le référentiel des éditeurs ayant lui-même ses doublons.
- [x] Index partiel sur `source_publications.journal_id`, que chaque fusion interroge.
- [x] Revues de même titre, seules à le porter, dont au moins une sans ISSN : même fusion automatique. Un premier passage a fusionné 623 paires, dont celles où l'une des revues était vide. L'audit y relève des homonymes : un livre fusionné dans une revue de même titre y a laissé sa forme de nom, ou y a pris les ISSN de la revue. La règle se limite aux paires dont les enregistrements partagent un préfixe DOI.
- [x] Revues vides, sans enregistrement, publication ni paiement APC : supprimées, avec leurs formes de nom. Le premier passage en supprime 1 374.
- [x] Journalisation des fusions et des suppressions : titre, éditeur et ISSN de chaque revue.
- [x] Réparation ciblée des homonymes relevés par l'audit, par `backfill_repair_homonym_journal_merges` :
    - formes de nom égarées : Livestock Science, Psychologie du travail et des organisations, Food Science & Nutrition, Food Science and Technology, Lectures ;
    - ISSN de revue portés par un livre : Reliability Engineering, Artificial Intelligence in Medicine ;
    - enregistrements d'un livre ou d'actes rattachés à la revue homonyme : Livestock Science, Lectures.
- [x] Onglets « Titres identiques » et « ISSN partagés » dans l'administration des revues, sans mémoire des paires distinctes. Le bouton « Garder celle-ci » y fusionne les autres revues du groupe. Après les fusions et les suppressions, il reste 11 700 revues. Les doublons potentiels comptent 45 groupes de même titre (21 sans ISSN, 13 dont une seule revue a un ISSN, 11 titres portés par trois revues ou plus) et 3 ISSN de colonne partagés. Les 18 paires de même titre dont les deux revues ont un ISSN sont des homonymes probables.
- Doublons d'éditeurs : Elsevier et Springer ont chacun une soixantaine de fiches. Ces doublons recréent des revues en double, la recherche d'une revue par titre se limitant à son éditeur. Sur 10 918 éditeurs, 6 771 n'ont ni revue ni préfixe DOI ; 1 747 d'entre eux portent encore des formes de nom de revue.
    - [x] Clé de nom (`publisher_name_key`) : crochets, années, « on behalf of », parenthèses et formes juridiques finales retirés. Le trouve-ou-crée des normaliseurs et `resolve_publishers` rapprochent les éditeurs par cette clé.
    - [x] La fusion d'éditeurs transfère les préfixes DOI de l'éditeur absorbé.
    - [x] Oneshot `backfill_merge_publisher_name_variants` : fusion des éditeurs de même clé. À blanc : 853 fusions, 1 refusée (Duncker & Humblot, revues homonymes aux ISSN divergents).
    - [x] Sous-étape `delete_empty_publishers` : suppression des éditeurs sans revue, sans préfixe DOI, sans paiement APC et sans forme de nom de revue.
    - [x] Marques et groupes : l'usage décide, revue par revue. Une marque reste l'éditeur que donnent les sources (Routledge, Dove Medical Press), et aucune fusion automatique ne la range dans son groupe. Un rattachement d'usage (Elsevier Masson dans Elsevier) passe par la fusion d'éditeurs de l'administration. Le préfixe DOI donne le déposant Crossref, souvent le groupe (Informa UK Limited pour Taylor & Francis), parfois une plateforme (CAIRN.INFO, OpenEdition, CCSD) : il ne sert pas de référence.
- [ ] Volet latéral pour les revues et les éditeurs, à l'image de ceux des publications et des personnes.
- [ ] Contrainte d'unicité sur `issn` et `eissn`, une fois ces doublons traités. `issnl` reste sans contrainte : un titre et son supplément le partagent.

### 5. Préfixes DOI des revues

- [ ] Sous-étape de `publishers_journals` qui calcule `doi_prefix` pour toutes les revues : plus long préfixe commun des DOI de la revue, retenu s'il identifie la revue.
- [ ] Contrainte d'unicité sur `doi_prefix`.
- [ ] Recalcul du stock, dont les 25 revues à préfixe identique ou emboîté.
- [ ] Réécriture de `resolve_journal_by_doi`.
- [ ] Retrait de `seed_journals_doi_prefix` et de ses tests.

### 6. Livres, chapitres et recueils d'actes

- [x] Mesure : aucun normaliseur ne filtre sur le type de document avant `find_or_create_journal`. Crossref rattache à une « revue » ses 1 983 chapitres et ses 1 437 articles de congrès, le plus souvent sans ISSN. Les faux conteneurs de livres comptent 141 `ebook_platform` (pseudo-sources OpenAlex « … eBooks »), 530 `unknown` et 199 `journal` sans ISSN.
- [x] Mesure : chez Crossref, l'ISSN départage les chapitres. Sans ISSN, le conteneur est le livre ; avec ISSN, une collection de livres ou d'actes. 95 % des articles de congrès n'ont pas d'ISSN : leur type `proceedings-article` suffit.
- [x] Normalisation, toutes sources, sur le type brut : un chapitre ou un livre crée ou retrouve une revue seulement s'il porte un ISSN. Un article de congrès garde son recueil, avec ou sans ISSN.
- [x] Normalisation : un livre ou un chapitre sans ISSN rejoint un recueil d'actes existant de même titre (`journal_type = proceedings`), sans jamais créer de revue.
- [x] Normalisation OpenAlex : une source `ebook platform` ne crée pas de revue, comme un dépôt.
- [x] Oneshot : détacher de leur « revue » les chapitres et livres qui tombent sous ces règles. La suppression des revues vides emporte ensuite les fausses revues. Les recueils d'actes sont épargnés. À blanc : 4 308 enregistrements détachés de 910 revues, 1 375 publications recalculées, 849 revues vidées.
- [x] Crossref : Springer décrit le congrès dans `assertion` (`conference_name`, `conference_acronym`…) sur 463 chapitres, dont 226 dans des collections typées `book_series`. `event` figure sur 98 % des `proceedings-article`, jamais sur un `book-chapter`. La normalisation range le nom et l'acronyme du congrès dans `meta.conference`. Un chapitre sans ISSN qui porte ce signal garde son recueil. La règle `CONFERENCE_DECLARED_TO_CONFERENCE_PAPER` type ces chapitres en articles de congrès.
- [x] Stock Crossref : réhydrater le staging depuis le raw store, puis renormaliser Crossref.
- [x] Typage automatique des conteneurs dans `publishers_journals` (`type_proceedings_journals`) : un conteneur `unknown` dont la majorité stricte des enregistrements sont des articles de congrès, d'après leur type brut, devient `proceedings`. Ce signal retrouve 263 des 288 conteneurs `proceedings` existants, et en propose 325 parmi les `unknown`.
- [x] File de l'administration pour les 232 conteneurs typés `journal` que ce signal désigne comme recueils d'actes : onglet « Recueils d'actes probables » de `admin/journals`. Les vraies revues qui publient les résumés d'un congrès (*Value in Health*, *Diabetologia*) y restent : une colonne qui retiendrait leur vérification attend de savoir si ce résidu gêne.
- [x] Typage par le titre dans `type_proceedings_journals` : une revue sans ISSN dont le titre nomme une édition datée devient `proceedings` (`names_a_dated_event`). Ne comptent ni une période (« 1960–2015 »), ni une année seule entre parenthèses, ni un titre qui contient « journal ». Mesure : 95 revues typées `journal` et 3 `unknown`, toutes des actes ; 447 des recueils sans ISSN déjà typés sont retrouvés.
- [x] Typage par un titre d'actes : une revue sans ISSN dont le titre contient « proceedings », sans « society », « academy » ni « institution », devient `proceedings` (`names_proceedings`). Les revues ainsi nommées (*PNAS*, *Proceedings of the Institution of Civil Engineers*) sont écartées par leur ISSN, puis par ces mots. Mesure : 10 revues typées `journal`, toutes des actes.
- [ ] Titres de revue parasites, surtout `unknown` : « 22 Seiten (2023). », « 1-26 (2021). », « Journal of high energy physics 2018(7) ». Source et nettoyage à établir.
- [ ] ISBN : seul Crossref est lu (`external_ids.isbn`). HAL (TEI `idno type="isbn"`) et WoS (identifiants `isbn`, `eisbn`) le fournissent aussi, DataCite surtout en texte libre. Le DOI contient un ISBN pour 3 464 chapitres, 465 livres et 1 287 articles de congrès (`10.1007/978-3-030-58080-3_309-1`).

## Questions ouvertes

- **Seconde source.** Faut-il une seconde source pour les ISSN absents du Sudoc (17 % de l'échantillon) ?
- **Recueils et collections.** La table `journals` range au même niveau les recueils d'actes et la collection qui les réunit (*Communications in Computer and Information Science*, *IFIP AICT*). Faut-il une table des monographies, identifiées par leur ISBN et rattachées à leur collection ?
- **Groupes d'éditeurs.** Faut-il compter les publications par groupe (Informa, Springer Nature, Elsevier) ? Un lien de groupe entre éditeurs y répondrait, sans fusion.
