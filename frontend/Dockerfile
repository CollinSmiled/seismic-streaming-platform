FROM node:25-alpine@sha256:bdf2cca6fe3dabd014ea60163eca3f0f7015fbd5c7ee1b0e9ccb4ced6eb02ef4 AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
ARG VITE_MAPBOX_ACCESS_TOKEN=""
RUN npm run build

FROM caddy:2-alpine@sha256:d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f
# Ports 8080/8443 do not need the base image's privileged-port file capability.
RUN setcap -r /usr/bin/caddy \
    && addgroup -g 10001 seismic && adduser -D -u 10001 -G seismic seismic \
    && mkdir -p /srv /data /config && chown -R 10001:10001 /srv /data /config
COPY --from=build /app/dist /srv
COPY deploy/Caddyfile /etc/caddy/Caddyfile
USER 10001:10001
EXPOSE 8080 8443
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
