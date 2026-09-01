# Image de base épinglée par empreinte, l'étiquette conservée à côté pour la lisibilité
# et pour le robot de mise à jour, qui suit les deux. Une étiquette se redéplace sur une autre
# image ; l'empreinte désigne celle qui a été examinée.
FROM node:24-slim@sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e

# Répertoire de travail de la composition de développement, qui y monte les sources
# depuis le poste et garde les dossiers générés dans des volumes anonymes.
WORKDIR /app

# `npm ci` installe les versions de `package-lock.json`, comme l'intégration.
COPY package*.json ./
RUN npm ci

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
