#!/usr/bin/env bash
# carddav2fritzbox — build script for multi-arch image (FR-001, FR-002, FR-006).
# Separate from deploy.sh per FR-011 / plan Structure Decision. See
# specs/003-docker-multiarch-build/contracts/build-commands.md for contract.
#
# Base image python:3.13-alpine publishes linux/amd64 + linux/arm64
# (research.md §1). No arch-specific Dockerfile logic required.
#
# Usage:
#   docker/build.sh                          # native build, tag carddav2fritzbox:local
#   docker/build.sh -t <registry>:<tag>      # native build with custom tag
#   docker/build.sh --push -t <registry>:<tag>  # cross-build linux/amd64,linux/arm64 and push manifest list
#   docker/build.sh -h | --help              # usage
#
# Options:
#   -t, --tag <ref>       Image reference (default: carddav2fritzbox:local for native)
#       --push            Cross-build and push manifest list (requires -t with a registry)
#       --platform <list> Override platforms (default native: host; with --push default: linux/amd64,linux/arm64)
#   -f, --file <path>     Dockerfile path (default: docker/Dockerfile)
#   -h, --help            Show this help
#
# Verification after --push:
#   docker buildx imagetools inspect <registry>:<tag>  # expect linux/amd64 + linux/arm64

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_DOCKERFILE="docker/Dockerfile"
DEFAULT_TAG="carddav2fritzbox:local"
DEFAULT_PLATFORMS_PUSH="linux/amd64,linux/arm64"

TAG="${DEFAULT_TAG}"
DOCKERFILE="${DEFAULT_DOCKERFILE}"
PUSH=0
PLATFORM=""

usage() {
  sed -n '2,23p' "$0" | sed 's/^# \?//'
}

error() { echo "ERROR: $*" >&2; }

while [ $# -gt 0 ]; do
  case "$1" in
    -t|--tag)
      [ $# -ge 2 ] || { error "--tag requires an argument"; exit 2; }
      TAG="$2"; shift 2 ;;
    --tag=*)
      TAG="${1#--tag=}"; shift ;;
    -f|--file)
      [ $# -ge 2 ] || { error "--file requires an argument"; exit 2; }
      DOCKERFILE="$2"; shift 2 ;;
    --file=*)
      DOCKERFILE="${1#--file=}"; shift ;;
    --push)
      PUSH=1; shift ;;
    --platform)
      [ $# -ge 2 ] || { error "--platform requires an argument"; exit 2; }
      PLATFORM="$2"; shift 2 ;;
    --platform=*)
      PLATFORM="${1#--platform=}"; shift ;;
    -h|--help)
      usage; exit 0 ;;
    --)
      shift; break ;;
    -*)
      error "unknown option '$1'"; usage >&2; exit 2 ;;
    *)
      error "unknown positional argument '$1'"; usage >&2; exit 2 ;;
  esac
done

# Resolve Dockerfile path relative to repo root for docker commands
if [[ "${DOCKERFILE}" != /* ]]; then
  DOCKERFILE_ABS="${REPO_ROOT}/${DOCKERFILE}"
else
  DOCKERFILE_ABS="${DOCKERFILE}"
fi
if [ ! -f "${DOCKERFILE_ABS}" ]; then
  error "Dockerfile not found: ${DOCKERFILE} (${DOCKERFILE_ABS})"
  exit 2
fi

# Validation for --push (FR-006, error case: pushing requires registry)
if [ "${PUSH}" -eq 1 ]; then
  if [ "${TAG}" = "${DEFAULT_TAG}" ]; then
    error "--push requires -t <registry>/carddav2fritzbox:<tag> (refusing to push ${DEFAULT_TAG})"
    exit 2
  fi
  # Heuristic: local tags without registry contain no '.' or ':' with '/' — warn but allow if user insists?
  # Require at least a '/' or '.' or ':' with registry semantics; simplest: require '/' in tag when pushing
  if [[ "${TAG}" != */* ]]; then
    error "--push requires a registry-qualified tag (e.g. ghcr.io/org/carddav2fritzbox:1.0), got '${TAG}'"
    exit 2
  fi
  if [ -z "${PLATFORM}" ]; then
    PLATFORM="${DEFAULT_PLATFORMS_PUSH}"
  fi
fi

# Native build (no --push): use plain docker build (no buildx required)
if [ "${PUSH}" -eq 0 ]; then
  # If user explicitly passed --platform with native build, pass it through (single arch)
  BUILD_ARGS=(build)
  if [ -n "${PLATFORM}" ]; then
    BUILD_ARGS+=(--platform "${PLATFORM}")
  fi
  BUILD_ARGS+=(-f "${DOCKERFILE}" -t "${TAG}" "${REPO_ROOT}")
  echo "== Native build: docker ${BUILD_ARGS[*]} ==" >&2
  exec docker "${BUILD_ARGS[@]}"
fi

# Cross-build + push path
# Ensure buildx builder exists
if ! docker buildx version >/dev/null 2>&1; then
  error "docker buildx not found; install Docker Engine >= 19.03 with buildx"
  exit 3
fi

# Use existing builder if available, otherwise create one
if ! docker buildx inspect >/dev/null 2>&1; then
  echo "Creating buildx builder 'carddav2fritzbox'..." >&2
  docker buildx create --name carddav2fritzbox --use >/dev/null
  docker buildx inspect --bootstrap >/dev/null 2>&1 || true
else
  # Try to bootstrap for QEMU
  docker buildx inspect --bootstrap >/dev/null 2>&1 || true
fi

echo "== Cross-build + push: TAG=${TAG} PLATFORM=${PLATFORM} FILE=${DOCKERFILE} ==" >&2
echo "   (If this fails with 'no matching manifest' or exec format error, install QEMU: docker run --privileged --rm tonistiigi/binfmt --install all)" >&2
# shellcheck disable=SC2086
# Build and push manifest list (required for multi-platform with default docker driver)
# Fallback documented in contracts/build-commands.md § Fallback: separate per-arch pushes + manifest create
set -x
docker buildx build \
  --platform "${PLATFORM}" \
  -t "${TAG}" \
  -f "${DOCKERFILE_ABS}" \
  --push \
  "${REPO_ROOT}"
set +x

echo >&2
echo "Pushed ${TAG} (${PLATFORM}). Verify:" >&2
echo "  docker buildx imagetools inspect ${TAG}" >&2
