#!/usr/bin/env bash

TPLBUILD_IMAGE="${TPLBUILD_IMAGE:-msg555/tplbuild}"

RUN_FLAGS=(
  -v "/var/run/docker.sock:/var/run/docker.sock"
  -v "${HOME}/.docker:/home/me/.docker:ro"
  -v "${PWD}:/work"
  -w /work
  -u "$(id -u):$(id -g)"
  -e HOME=/home/me
  --rm
)

for GID in $(id -G); do
  RUN_FLAGS+=(--group-add "${GID}")
done

docker run "${RUN_FLAGS[@]}" "${TPLBUILD_IMAGE}" "${@}"
