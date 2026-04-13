# Roadmap — Bibliométrie UCA

2. Seed de démarrage (TODO_LAURA: générer un seed de novo)
Sans ça, impossible de redéployer le projet. Quelqu'un qui clone le repo ne peut pas lancer l'application — il manque les données de référence (structures UCA, relations, périmètres). C'est bloquant pour la transmissibilité.

3. Tests (TODO_CLAUDE: tests d'idempotence phases restantes + TODO_LAURA: creuser les types de tests)
Le pipeline touche à toute la base. Sans couverture de test sur create_persons, build_authorships et les phases critiques, chaque modification est un risque. La DSI ne pourra pas faire évoluer le code en confiance.

4. Finir la transition config en base (TODO_LAURA: settings.py → config DB)
Des paramètres hardcodés dans des fichiers Python locaux = pas déployable facilement. La DSI ne pourra pas configurer l'instance sans toucher au code.

5. Refactoring des normaliseurs (TODO_CLAUDE: DOCTYPE_MAP, factoriser find_publication)
5 scripts qui dupliquent la même logique avec des variantes subtiles. En cas de bug ou d'évolution, il faut modifier 5 fichiers en gardant la cohérence. C'est le principal risque de maintenabilité.

6. Observabilité pipeline (TODO_CLAUDE: rapport de synthèse + TODO_LAURA: logs post-pipeline)
Sans logs exploitables, la DSI ne saura pas si un run s'est bien passé ni quoi faire en cas de problème.

7. Réimport et pérennité des données (TODO_LAURA: hash structures, authorships au réimport, excluded perdus)
Ce sont des bombes à retardement : tout fonctionne tant qu'on ne re-importe pas, mais un full re-run pourrait casser des données manuellement corrigées.

Les points 1-2 sont existentiels (pas de projet sans eux). Les points 3-5 sont la maintenabilité quotidienne. Les points 6-7 sont la fiabilité opérationnelle.

## Quick wins

2. Publi 79637 : authorship source rejetée → rejeter de l'authorship vérité (TODO_LAURA l.123)
Un cas ponctuel à investiguer en base puis corriger via le service. Rapide si c'est un cas isolé.

3. Harmoniser noms de routes API / URL frontend (TODO_LAURA l.25)
Un audit rapide des routes pour lister les incohérences, puis renommage. Mécanique mais sans risque.

4. Rendre tous les tableaux triables (ROADMAP l.54)
Si les tableaux utilisent déjà un composant partagé, ajouter le tri est assez systématique. Je peux vérifier l'état actuel.

5. Afficher les abstracts dans publications/id (ROADMAP l.58)
Si les abstracts sont déjà en base, c'est juste un affichage supplémentaire côté frontend. Très peu de code.

6. Filtre corresponding_is_uca (TODO_LAURA l.93)
Si is_corresponding et is_uca existent déjà sur les authorships, c'est un filtre backend + une checkbox frontend.


## Gros chantiers (à planifier)

### Mega-authorships et alignement inter-sources
Publications > 50 auteurs : désalignement des positions entre HAL/OpenAlex/WoS → faux conflits. Table `authorship_alignments` + algorithme de matching par noms. En attendant, exclusion des publis > 50 auteurs du mode "conflit de sources".

### Relations entre publications
Modéliser les relations : est traduction de, est preprint de, fait partie de (chapitre → ouvrage), corrigendum, etc.

### Pages supplémentaires
Sujets, éditeurs, revues (avec liens DOAJ, APC). Évaluer la pertinence avant de développer.

### Uniformisation compatibilité noms (Python vs SQL)
Les fonctions `names_compatible` existent en Python (utils/names.py) et en SQL (admin_person_duplicates.py). Idéalement unifier, mais les requêtes SQL sont plus performantes pour le matching en masse.

