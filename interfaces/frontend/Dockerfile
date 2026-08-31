FROM node:22-slim

# WORKDIR aligné sur le montage du compose dev (`.:/repo`) : le frontend
# doit voir l'arborescence repo complète (notamment `docs/`, lu par le glob
# Vite de la route /docs via `../../../../../docs`).
WORKDIR /repo/interfaces/frontend

# `npm ci` installe les versions de `package-lock.json`, comme l'intégration.
COPY package*.json ./
RUN npm ci

# En dev, le code source et docs/ sont montés en volume (pas copiés)
EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
