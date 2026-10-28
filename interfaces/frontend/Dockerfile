# Image de développement du frontend, pour la composition de développement, qui monte les sources dans `/app`.
FROM node:26-slim@sha256:36793bcbb160a6a16cede1e62b93f84e26b78a972a8a4c0b879c1c12f22761ec

WORKDIR /app

# Versions de `package-lock.json`.
COPY package*.json ./
RUN npm ci

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
