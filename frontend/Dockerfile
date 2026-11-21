FROM node:26-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5 AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
ARG VITE_MAPBOX_ACCESS_TOKEN=""
RUN npm run build

FROM caddy:2-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0
# Ports 8080/8443 do not need the base image's privileged-port file capability.
RUN setcap -r /usr/bin/caddy \
    && addgroup -g 10001 seismic && adduser -D -u 10001 -G seismic seismic \
    && mkdir -p /srv /data /config && chown -R 10001:10001 /srv /data /config
COPY --from=build /app/dist /srv
COPY deploy/Caddyfile /etc/caddy/Caddyfile
USER 10001:10001
EXPOSE 8080 8443
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
