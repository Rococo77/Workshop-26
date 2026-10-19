# Front React/Tailwind servi par Vite. Pour le démonstrateur, mode dev (HMR).
# En production : build statique + nginx (voir docs/architecture.md).
FROM node:22-slim

WORKDIR /app

# Lockfile + npm ci : mêmes versions que celles testées et scannées par Trivy.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev"]
