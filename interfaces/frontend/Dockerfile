FROM node:25-slim

# Répertoire de travail de la composition de développement, qui y monte les sources
# depuis le poste et garde les dossiers générés dans des volumes anonymes.
WORKDIR /app

# `npm ci` installe les versions de `package-lock.json`, comme l'intégration.
COPY package*.json ./
RUN npm ci

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
