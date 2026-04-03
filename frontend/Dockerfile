FROM node:22-slim

WORKDIR /app

COPY package*.json ./
RUN npm install

# En dev, le code source est monté en volume (pas copié)
EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
