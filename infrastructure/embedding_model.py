"""Nom du modèle d'embeddings, seul dans son module : la construction de l'image Docker le lit pour télécharger le modèle avant de copier le code."""

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
"""Modèle multilingue à 384 dimensions. Il lit les 128 premiers tokens du texte, soit environ 500 caractères."""
