# Chantier — Statut open access tiré des copies

## Contexte

Le statut open access d'une publication combine le statut déclaré par chaque source et le verdict d'Unpaywall sur son DOI (`publication_oa_status`, `domain/publications/metadata.py`). Sans verdict, le statut le plus ouvert des sources l'emporte. Le statut déclaré par une source est invérifiable : il ne renvoie à aucune copie.

Une copie (`source_record_locations`) a seulement un booléen `is_oa`. La normalisation HAL convertit un embargo actif en `is_oa = false`, et la date de fin d'embargo reste sur l'enregistrement source (`source_records.embargo_until`). À l'échéance, une règle de correction fait passer le statut `embargoed` à `green`, mais la copie reste fermée. Le lien texte intégral, choisi parmi les copies ouvertes, ignore alors le fichier HAL.

### Mesures du 2026-10-30

Simulation sur les 76 591 publications du périmètre (`interfaces/cli/oneshot/measure_oa_floor.py`). Le plancher d'une publication vient de sa meilleure copie ouverte, et le verdict d'Unpaywall le relève. Une copie d'archive donne `green`. Une autre copie ouverte compte côté éditeur : une revue `full_oa` donne `gold`, ou `diamond` si le DOAJ indique ni APC ni autres frais ; une revue `subscription` donne `hybrid` avec une licence ouverte, `bronze` sans.

94,9 % des publications gardent leur statut. Écarts :

| Passage | Publications | Cause |
|---|---|---|
| `diamond` conservé | 3 404 sur 3 409 | le DOAJ des revues suffit |
| `green` → `bronze` | 2 710 | copies d'archive absentes du registre des plateformes, comptées côté éditeur |
| `closed` → ouvert | 346 | copies dites ouvertes par ScanR ou OpenAlex, verdict Unpaywall fermé |
| `embargoed` → `closed` | 116 | embargo absent des copies |
| ouvert → `closed` | environ 100 | statut ouvert déclaré par une seule source, sans copie ni verdict |

**Archives absentes du registre.** theses.fr (1 089 copies), `hdl.handle.net`, archives institutionnelles, serveurs de preprints derrière `doi.org` (bioRxiv, `10.1101`). OpenEdition, Cairn et Persée sont côté éditeur.

**Copies ouvertes douteuses.** 186 copies ScanR sur `doi.org` sont dites ouvertes, contre le verdict d'Unpaywall. 80 copies HAL sont dites ouvertes par ScanR ou OpenAlex, alors que l'enregistrement HAL les dit fermées. Les copies Persée sont réellement ouvertes.

**Absence de verdict.** 29 385 publications n'ont pas de DOI, et 5 061 DOI n'ont pas de verdict Unpaywall.

## Décisions

- Le statut d'une publication se déduit de ses copies et du modèle de sa revue, dans cet ordre :
  1. copie ouverte côté éditeur, sous licence ouverte : `hybrid` dans une revue `subscription` ou de modèle inconnu, `gold` dans une revue `full_oa` ou hors revue, `diamond` dans une revue `diamond` ;
  2. sinon, copie d'archive ou de serveur de preprints ouverte : `green`, avant `bronze` ;
  3. sinon, copie ouverte côté éditeur sans licence : `bronze` ;
  4. sinon `embargoed`, `closed` ou `unknown`.
- Sans copie ouverte côté éditeur, le modèle de la revue ne donne aucun statut.
- Le verdict d'Unpaywall relève les accès constatés, jamais ne les abaisse.
- Le statut ignore les statuts déclarés par les sources. La colonne `source_records.oa_status` disparaît.
- L'embargo d'un enregistrement source est dans la table des embargos. L'ouverture d'une copie se calcule à la lecture : `is_oa` et embargo absent ou échu. Un enregistrement source sous embargo actif donne `embargoed`.
- L'embargo déclaré par theses.fr, sans copie ni date, donne `embargoed`.
- Sans copie ouverte ni verdict : `closed` avec une copie, un verdict, pour une thèse en cours ou réservée à l'intranet de son établissement ; `unknown` sans aucune information.
- HAL décide de l'ouverture des copies de ses propres dépôts : quand l'enregistrement source HAL d'un dépôt est dans la publication, sa description l'emporte sur celle des autres sources.
- L'identifiant HAL désigne un dépôt, quel que soit le portail. Une copie HAL a l'adresse de son dépôt sur `hal.science`, quel que soit le portail. Seul DUMAS garde son portail : ses dépôts sont absents de `hal.science`.
- Pour une communication ou un poster, une annexe HAL (diaporama, poster, résumé) tient lieu de fichier déposé.
- Un dépôt HAL réduit à des annexes désigne une communication (`conference`), sauf DOI, revue ou volume d'actes donnés par une source.

## Phasage

### Phase 1 — Copies fiables

- [x] Registre des plateformes : theses.fr, `hdl.handle.net`, archives institutionnelles, serveurs de preprints reconnus par préfixe DOI. Pages du DOAJ, du DOAB et de PubMed écartées des copies. Reste `green` → `bronze` : 789 publications, à copie sur une plateforme d'éditeurs (OpenEdition, Cairn) ou à lien `doi.org` de ScanR. 2d9d97af7
- [x] La description d'une copie par sa propre plateforme prime : une copie HAL suit l'enregistrement HAL. `green` → `closed` : 1 019 publications. Parmi elles, 270 enregistrements sources HAL sans fichier, 224 dépôts HAL sans fichier principal, environ 300 publications dont la seule copie ouverte était une page du DOAJ, de PubMed ou une liste de Glasgow. ef34b5ae0
- [x] `is_oa` de ScanR sur les liens `doi.org` : mesurer contre Unpaywall, l'écarter s'il est peu fiable. Copies ouvertes à DOI vérifié par Unpaywall, hors DOI d'archive : verdict `closed` ou `green` pour 5,6 % des copies ScanR, 4,6 % des copies OpenAlex. ScanR est aussi fiable qu'OpenAlex.
- [x] HAL décide pour ses seuls dépôts : OpenAlex réunit parfois deux dépôts HAL sous un work. 22104f7d2
- [x] Adresse unique d'un dépôt HAL, toutes sources confondues ; script `canonicalize_hal_location_urls` pour le stock. bff127b5c
- [x] Annexes HAL (`fileAnnexes_s`) moissonnées ; annexe d'une communication ou d'un poster tenue pour fichier déposé ; dépôt réduit à des annexes typé communication. Mesure sur l'API HAL : 540 publications passent de `closed` à `green`. 62e867b50, bff127b5c
- [x] Stock : annexes absentes des payloads HAL moissonnés avant 62e867b50. Le retrait de champs inutiles du moissonnage HAL change tous les payloads. Chaque dépôt repasse donc en normalisation à sa prochaine lecture, annexes comprises. 27a98a5dd
- [x] 806 enregistrements sources HAL sans localisation en local (701 publications, dont 310 sans aucune copie). Leurs payloads sont absents du raw store, donc de la relecture du stock qui a créé les localisations. Même remède. 27a98a5dd
- [x] Registre : OSF, posters et diaporamas de F1000Research, preprints JMIR. fcd982c57

### Phase 2 — Embargo sur les copies

- [x] Colonne `embargo_until` sur `source_record_locations`, retirée de `source_records`. La migration reporte la date sur les copies HAL et remet leur `is_oa` à vrai. 711dbf64a
- [x] Ouverture d'une copie calculée à la lecture (lien texte intégral, statut). La règle de correction lit la date sur la copie. 711dbf64a

### Phase 3 — Statut tiré des copies

- [x] Mesure (`measure_oa_floor`) : accord avec Unpaywall de 97 % sur ouvert ou fermé, de 96 % sur la copie côté éditeur. f6a93aab6
- [x] Fonction de décision du domaine (`domain/publications/open_access.py`). fcd982c57
- [x] Statut calculé dans la consolidation et dans la phase `oa_status`. 0466fb7ba
- [x] Recalcul du stock (`recompute_oa_statuses`) : 6 675 publications changent de statut à blanc en local. Écart restant avec la mesure : 389 publications, dont 374 à annexes HAL absentes des payloads.
- [x] Publication 9705, déposée sur Zenodo : son DOI mène à Zenodo, le bouton d'accès affichait « via l'éditeur ». 303d519f6
- [x] Publication 78490, fermée alors que son DOI KISTI mène au PDF : aucune localisation éditeur, ni verdict d'Unpaywall. Pris en charge par le chantier [Adresses enregistrées des DOI](2026-10-31_DATA_adresses-enregistrees-des-doi.md).

### Phase 4 — Documentation

- [x] Règle du statut dans `docs/pipeline/11-enrichissements.md`, Unpaywall dans `docs/sources/`. 0466fb7ba

### Phase 5 — Embargos

- [x] Table des embargos : embargo d'une copie HAL, avec sa date de fin ; embargo déclaré par theses.fr, sans date. Elle remplace `embargo_until` des localisations et le statut `embargoed` déclaré par theses.fr. 71ceed221
- [x] Thèse réservée à l'intranet dans `source_extras`. Thèse en cours et thèse réservée à l'intranet `closed`, statuts déclarés ignorés. 168568f69
- [x] Adresse d'un dépôt HAL écrite par une seule fonction. L'adresse d'une thèse TEL est sur `hal.science`, qui affiche toutes les thèses TEL. theses.hal.science affiche seulement les thèses TEL avec fichier déposé. Stock : `canonicalize_hal_location_urls`. 27fa9b584
- [x] Colonne `source_records.oa_status` retirée, avec les dérivations des normaliseurs et les règles de correction associées. a3bdf2ae2
