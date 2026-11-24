#!/bin/sh
set -eu

ROUTES_DIR="/routes/routes"

for route_file in \
  "$ROUTES_DIR/gateway-health.json" \
  "$ROUTES_DIR/users.json" \
  "$ROUTES_DIR/auth.json" \
  "$ROUTES_DIR/products.json" \
  "$ROUTES_DIR/orders.json" \
  "$ROUTES_DIR/notifications.json"
do
  route_name="$(basename "$route_file" .json)"
  echo "Configuring APISIX route: $route_name"
  curl --fail --show-error --silent \
    --retry 30 \
    --retry-delay 2 \
    --retry-connrefused \
    --request PUT \
    --header "X-API-KEY: ${APISIX_ADMIN_KEY}" \
    --header "Content-Type: application/json" \
    --data-binary "@${route_file}" \
    "${APISIX_ADMIN_URL}/routes/${route_name}" >/dev/null

  curl --fail --show-error --silent \
    --header "X-API-KEY: ${APISIX_ADMIN_KEY}" \
    "${APISIX_ADMIN_URL}/routes/${route_name}" >/dev/null
done

echo "APISIX routes configured"
