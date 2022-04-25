#!/usr/bin/env bash

set -eo pipefail

REGISTRY_PORT=8443
REGISTRY_NAME=tplbuild-test-registry
REGISTRY_IMAGE=registry:2
export TEST_BASE_IMAGE_NAME

CONTAINERS_REGISTRIES_CONF=$(mktemp)
export CONTAINERS_REGISTRIES_CONF
echo "${CONTAINERS_REGISTRIES_CONF}"

cat - > "${CONTAINERS_REGISTRIES_CONF}" <<-EOF
unqualified-search-registries = ["docker.io"]

[[registry]]
location="localhost:${REGISTRY_PORT}"
insecure=true
EOF
trap 'rm "${CONTAINERS_REGISTRIES_CONF}"' EXIT

start-registry() {
  stop-registry
  docker run -d -p "${REGISTRY_PORT}:5000" --name "${REGISTRY_NAME}" "${REGISTRY_IMAGE}"
}

stop-registry() {
  docker rm -f "${REGISTRY_NAME}" || true
}

start-registry
trap stop-registry EXIT

CLIENTS=(docker buildx podman)
for CLIENT in "${CLIENTS[@]}"; do
  export TEST_BASE_IMAGE_NAME="localhost:${REGISTRY_PORT}/base-${CLIENT}"
  export TEST_CLIENT_TYPE="${CLIENT}"
  PYTHONPATH=. python3 -m pytest -sv --cov=tplbuild -m build tests
done
