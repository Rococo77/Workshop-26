# Front React/Tailwind : build statique (Vite) puis service par nginx non-root.
# L'image finale ne contient ni Node, ni npm, ni serveur de dev Vite : c'est
# ce qui portait les CVE de node:22-slim (perl-base) et du npm embarqué.
FROM node:22-slim AS build

WORKDIR /app

# Lockfile + npm ci : mêmes versions que celles testées et scannées par Trivy.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# Numéro de groupe (NUM_GROUPE du .env) : embarqué au build par Vite, lu en
# front via import.meta.env.VITE_NUM_GROUPE (pas d'accès à l'env à l'exécution,
# l'image finale ne sert que du statique via nginx).
ARG VITE_NUM_GROUPE
ENV VITE_NUM_GROUPE=$VITE_NUM_GROUPE
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.30.6-alpine3.24

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
