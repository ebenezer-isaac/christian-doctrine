#!/bin/bash
# Creates the app user on first start of an empty volume (mongo image init hook).
set -euo pipefail
: "${CD_APP_MONGO_PASSWORD:?set in mongo.env}"
mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin christian_doctrine --eval "
  db.createUser({ user: \"cd_app\", pwd: process.env.CD_APP_MONGO_PASSWORD, roles: [{ role: \"readWrite\", db: \"christian_doctrine\" }] });
"
