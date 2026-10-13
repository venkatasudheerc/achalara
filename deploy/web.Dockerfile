# The web front: the built app, served over HTTPS, with /api passed to the backend.
FROM node:20-alpine AS build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Empty on purpose: the app calls the API on its own address, so there is one
# site, one certificate and no cross-site cookie to configure.
ENV VITE_API_BASE_URL=""
RUN npm run build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/frontend/dist /srv/www
