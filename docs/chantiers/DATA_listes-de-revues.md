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
- Une liste donne l'appartenance actuelle d'une revue, sans historique. Chaque import remplace les appartenances.
- Chaque niveau d'un classement est une liste, rattachée à son classement (registre norvégien, FNEGE).
- La facette « DOAJ » de la liste des revues devient une facette « Listes ». Elle a un sélecteur à trois états (indifférent, présente, absente) par liste et par classement, combinés par un ET.
- Sous un classement indifférent ou présent, une case à cocher par niveau restreint la sélection aux niveaux cochés, combinés par un OU.

## Phasage

### Phase 1 — Modèle

- [ ] Table des listes (code OpenAlex, classement, nom, organisme, URL, édition), table des appartenances (revue, liste)

### Phase 2 — Source OpenAlex et listes de chaque revue

- [ ] Sous-étape de la phase `publishing` : source OpenAlex de chaque revue par ISSN (`/sources`), appartenances aux listes retenues (question 1)
- [ ] `openalex_id` des revues sans enregistrement source OpenAlex ou rattachées à une source OpenAlex de plusieurs titres (question 1)
- [ ] Retrait de l'identifiant d'une revue vidée de ses enregistrements sources OpenAlex

### Phase 3 — DOAJ en liste

- [ ] `is_in_doaj` lu dans les appartenances (question 2)

### Phase 4 — Interface

- [ ] Cases à cocher des niveaux d'une ligne dans le sélecteur à trois états (`PresenceFilterToggle`)
- [ ] Facette « Listes » de la liste des revues
- [ ] Listes d'une revue sur sa page

## Questions ouvertes

1. `openalex_id` posé par la recherche par ISSN et par `attach_serials` d'après les enregistrements sources OpenAlex : priorité entre les deux. Type des revues lu dans la même requête, à la place d'`enrich_serials_from_openalex`.
2. Dump du DOAJ : il reste nécessaire à `doaj_payload` (classement diamant, page de la revue). Appartenance au DOAJ lue dans le dump ou dans OpenAlex.
3. Quartiles par catégorie : import de SCImago.
