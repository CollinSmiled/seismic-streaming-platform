#!/bin/sh
set -eu
# psql reads the password from its environment and quotes it as a SQL literal.
# Keep application credentials out of command arguments.
export SEISMIC_APP_PASSWORD="$(cat /run/secrets/postgres_password)"
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=ON_ERROR_STOP=1 <<'SQL'
\getenv app_password SEISMIC_APP_PASSWORD
CREATE ROLE seismic LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'app_password';
ALTER DATABASE seismic OWNER TO seismic;
SQL
unset SEISMIC_APP_PASSWORD
