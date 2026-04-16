# Notes techniques (Claude)

## Uniformisation compatibilité de noms (Python vs SQL)

Les fonctions de compatibilité de noms existent en deux versions :
- Python : `utils/names.py` (`names_compatible`, `first_names_compatible`, etc.)
- SQL : requêtes dans `backend/routers/admin_person_duplicates.py` (`PERSON_DUP_QUERIES`)

Les deux implémentent la même logique mais indépendamment. À réévaluer si la logique diverge.
