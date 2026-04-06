# Roadmap — Bibliométrie UCA

Chantiers restants, classés par effort. Consolidation des TODO_LAURA.md et TODO_CLAUDE.md.

## Chantiers moyens (quelques heures)

### Automatisation pays des adresses (country_name_forms)
Table `country_name_forms` avec les formes de noms de pays (français, anglais, variantes). Script de parsing des adresses pour détecter les pays automatiquement → `suggested_countries`, validables manuellement. Voir TODO_CLAUDE pour le détail.

### Cron imports + dumps
Automatiser les imports périodiques (hebdomadaires) et les dumps de sauvegarde. Docker cron ou systemd timer.

### Tests d'idempotence du pipeline
Vérifier que lancer deux fois chaque phase produit le même résultat. Fixtures + double exécution + compteurs. Voir TODO_CLAUDE pour le détail.


## Gros chantiers (à planifier)

### Mega-authorships et alignement inter-sources
Publications > 50 auteurs : désalignement des positions entre HAL/OpenAlex/WoS → faux conflits. Table `authorship_alignments` + algorithme de matching par noms. En attendant, exclusion des publis > 50 auteurs du mode "conflit de sources".

### Nouvelles sources
ArXiv, PubMed, ScanR, theses.fr. Chaque source = extraction + normalisation + intégration au pipeline.

### Relations entre publications
Modéliser les relations : est traduction de, est preprint de, fait partie de (chapitre → ouvrage), corrigendum, etc.

### Pages supplémentaires
Sujets, éditeurs, revues (avec liens DOAJ, APC). Évaluer la pertinence avant de développer.

### Uniformisation compatibilité noms (Python vs SQL)
Les fonctions `names_compatible` existent en Python (utils/names.py) et en SQL (admin_person_duplicates.py). Idéalement unifier, mais les requêtes SQL sont plus performantes pour le matching en masse.


## Bugs et bizarreries à investiguer

- openalex répète des auteurs : publi 77832
- claire richard : pourquoi 0 publi UCA sur page admin?
- publi 103567 : structures identifiées sur HAL (UCA, Inserm) → pourquoi?
- personne 57907 : comprendre comment "Damien Boyer" est devenu une forme de nom
- publi 79637 : authorship source rejetée → la rejeter de l'authorship vérité
- trous dans la numérotation des auteurs HAL : diagnostiquer et résoudre
- HAL compte-rendu → type "autre" au lieu d'article
- publications "article" avec source OA et revue inconnue → souvent des preprints
- document dumas : ouvrir sur dumas, pas HAL
- preprints en accès gold → corriger
- authorship supprimée mais publi apparaît toujours (julie gardette)


## Améliorations d'interface (non prioritaires)

- Mémoriser filtres et les rétablir au rechargement
- Rendre les filtres sticky
- Rendre tous les tableaux triables
- Interface pour afficher le staging JSON (pour vérification)
- Différencier interfaces à usage interne vs externe (rôles)
- Groupes de pays (UE, continents) pour la recherche par facettes
- Afficher les abstracts
