# Chantier — Listes de revues

## Contexte

Le DOAJ est la seule liste de revues de la base. L'import de son dump CSV (`enrich_serials_from_doaj`, tous les 30 jours) rattache chaque ligne à sa revue par ISSN. La revue reçoit `is_in_doaj`, la ligne nettoyée (`doaj_payload`) et la date de l'import. Le DOAJ type aussi en revue les entrées présentes et classe les revues diamant. La liste des revues a une facette « DOAJ ».

OpenAlex donne, pour chaque source, les listes où elle figure (`listed_in`), y compris sur la source d'un work. L'API `/source-lists` décrit 63 listes : nom, organisme, URL, édition chargée. OpenAlex charge le fichier publié par l'organisme et rattache ses entrées aux sources par ISSN. Seules les revues présentes dans l'édition chargée sont marquées. Chaque niveau d'un classement forme une liste (`norway-1`, `norway-2`). `doaj` se met à jour chaque semaine. `cwts-core`, corpus du Leiden Ranking, vient d'un chargement unique de 2024.

Test du 2026-11-04 sur la base locale :

- 3 294 des 3 308 entrées en vigueur du tableur officiel de la conférence des doyens (édition du 2026-10-01) sont dans `doyens`. Les autres ont un ISSN faux ou absent dans le tableur.
- Les revues `is_in_doaj` sont toutes dans `doaj`. 77 revues de `doaj` n'ont pas `is_in_doaj`, la plupart créées après le dernier import du dump.
- 939 revues sans `openalex_id` se retrouvent par ISSN dans OpenAlex.

`openalex_id` manque dans deux cas :

- La revue a seulement des enregistrements sources HAL, ScanR, Crossref ou WoS : 585 revues, 925 publications.
- La source OpenAlex réunit l'ancien et le nouveau titre, avec l'ISSN-L de l'ancien titre. `attach_serials` écarte l'identifiant : il exige l'égalité des deux ISSN-L. L'ancienne revue garde l'identifiant, même vidée de ses enregistrements sources : « Journal of the American Medical Association » (0002-9955) garde celui de *JAMA* (0098-7484). 116 revues, 498 publications.

Hors OpenAlex : la Master Journal List de Clarivate (revues du Web of Science, CSV par collection, compte gratuit), la liste des sources de Scopus (connexion à Scopus). Les quartiles par catégorie viennent du Journal Citation Reports (abonnement) ou de SCImago (CSV libre, calculé sur Scopus, usage non commercial en citant la source).

## Décisions

- Le DOAJ est une liste parmi d'autres.
- Les listes viennent d'OpenAlex (`listed_in`, `/source-lists`).
- Listes retenues : `doyens`, `doaj`, `medline`, `cwts-core`, `ddh`, `erih-plus`, `norway-1`, `norway-2`, les cinq rangs du classement FNEGE (`fnege-1-star` à `fnege-4`).
- Une liste donne l'appartenance actuelle d'une revue, sans historique.
- L'appartenance au DOAJ vient d'OpenAlex. Le dump du DOAJ donne la fiche DOAJ (`doaj_payload`).
- Une revue du Diamond Discovery Hub est diamant, comme une revue du DOAJ sans APC ni autres frais.
- Chaque niveau d'un classement est une liste, rattachée à son classement (registre norvégien, FNEGE).
- Une seule sous-étape pose `openalex_id`. Une revue à ISSN prend la source OpenAlex de ses ISSN (`/sources`). Une revue sans ISSN prend la source la plus fréquente parmi ses enregistrements sources OpenAlex.
- Une source OpenAlex retrouvée par les ISSN de plusieurs revues donne son identifiant à la revue qui a le plus de publications, et ses listes à toutes.
- Chaque revue est relue dans OpenAlex au terme d'un délai réglable, 7 jours par défaut (`openalex_checked_at`). La lecture d'une revue remplace son identifiant, son type inconnu et ses appartenances.
- La facette « DOAJ » de la liste des revues devient une facette « Listes ». Elle a un sélecteur à trois états (indifférent, présente, absente) par liste et par classement, combinés par un ET.
- Sous un classement indifférent ou présent, une case à cocher par niveau restreint la sélection aux niveaux cochés, combinés par un OU.

## Phasage

### Phase 1 — Modèle

- [x] Table des listes (code OpenAlex, classement, nom, organisme, URL, édition), table des appartenances (revue, liste) (42eb2d92a)

### Phase 2 — Source OpenAlex et listes de chaque revue

- [x] Colonne `serials.openalex_checked_at`, délai de relecture dans `ops.config` (9aa3e39f5)
- [x] Sous-étape de la phase `publishing` : source OpenAlex, type et appartenances des revues à relire (9aa3e39f5)
- [x] `openalex_id` posé par cette seule sous-étape : vote retiré d'`attach_serials`, `enrich_serials_from_openalex` supprimée (9aa3e39f5)

### Phase 3 — DOAJ en liste

- [ ] `is_in_doaj` remplacé par l'appartenance à la liste `doaj`, dump du DOAJ réduit à la fiche DOAJ
- [ ] Revues du Diamond Discovery Hub classées diamant

### Phase 4 — Interface

- [ ] Cases à cocher des niveaux d'une ligne dans le sélecteur à trois états (`PresenceFilterToggle`)
- [ ] Facette « Listes » de la liste des revues
- [ ] Listes d'une revue sur sa page

## Questions ouvertes

1. Quartiles par catégorie : import de SCImago.
