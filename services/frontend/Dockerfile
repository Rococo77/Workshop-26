# Front React/Tailwind servi par Vite. Pour le démonstrateur, mode dev (HMR).
# En production : build statique + nginx (voir docs/architecture.md).
FROM node:22-slim

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev"]
