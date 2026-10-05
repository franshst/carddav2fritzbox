# Contract: Build Commands (`docker/build.sh`)

**Feature**: 003-docker-multiarch-build | **Date**: 2026-08-30

Source: `FR-001`, `FR-002`, `FR-006`, `FR-007`, `FR-009` and `spec.md` User Stories 1–3. Per user update 2026-08-30, all image construction lives in a **separate `docker/build.sh`** distinct from `docker/deploy.sh`. Raw `docker build`/`buildx` strings are encapsulated inside `build.sh`; docs and CI call the script.

## Script location & permissions

- **Path**: `docker/build.sh` at repository root
- **Executable**: `chmod +x docker/build.sh`
- **Separation**: `docker/deploy.sh` MUST NOT contain `docker build`/`buildx` (verification: `! grep -q "docker build" docker/deploy.sh`)

## Interface

```
docker/build.sh [OPTIONS]

Options:
  -t, --tag <registry>/carddav2fritzbox:<tag>   Image reference (default: carddav2fritzbox:local for native)
      --push                                     Cross-build linux/amd64,linux/arm64 and push manifest list (requires -t with a registry)
      --platform <list>                          Override platforms (default native = host; with --push default = linux/amd64,linux/arm64)
  -f, --file <path>                              Dockerfile path (default: docker/Dockerfile)
  -h, --help                                     Show usage
```

**Canonical invocations**:

| Goal | Command | Result |
|------|---------|--------|
| Native build (one arch, on that host) | `docker/build.sh` | `carddav2fritzbox:local` for host arch |
| Native with custom tag | `docker/build.sh -t <registry>/carddav2fritzbox:<tag>` | Local image with that tag, single arch |
| Cross-build & push (both archs, single host) | `docker/build.sh --push -t <registry>/carddav2fritzbox:<tag>` | Pushed manifest list with `linux/amd64` + `linux/arm64` |
| Help | `docker/build.sh --help` | Exit 0, prints usage |

## Encapsulated raw commands (what the script runs)

For reference / fallback when the script is not used:

**Native**:
```bash
docker build -f docker/Dockerfile -t carddav2fritzbox:local .
```

**Cross-build** (`--push`):
```bash
# Prerequisites one-time per host/CI:
#   docker buildx create --use   (if no builder exists)
#   docker run --privileged --rm tonistiigi/binfmt --install all   # QEMU binfmt (or docker/setup-qemu-action in CI)

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t <registry>/carddav2fritzbox:<tag> \
  -f docker/Dockerfile \
  --push \
  .
```

**Post-condition after `--push`**: Registry holds a manifest list / OCI index at `<registry>/carddav2fritzbox:<tag>` with exactly two manifests.

**Verification**:

```bash
docker buildx imagetools inspect <registry>/carddav2fritzbox:<tag>
# Expect:
#   Name:      <…>@sha256:…   Platform: linux/amd64
#   Name:      <…>@sha256:…   Platform: linux/arm64

# Alternative (older Docker):
docker manifest inspect <registry>/carddav2fritzbox:<tag>
# Expect "manifests": [ { "platform": {"architecture":"amd64","os":"linux"} }, { "platform": {"architecture":"arm64","os":"linux"} } ]
```

## Fallback (separate pushes + manual manifest, if buildx --push is not viable)

The script may implement this as fallback; equivalently runnable by hand:

```bash
docker buildx build --platform linux/amd64 -t <registry>/carddav2fritzbox:<tag>-amd64 --push -f docker/Dockerfile .
docker buildx build --platform linux/arm64 -t <registry>/carddav2fritzbox:<tag>-arm64 --push -f docker/Dockerfile .
docker manifest create <registry>/carddav2fritzbox:<tag> \
  --amend <registry>/carddav2fritzbox:<tag>-amd64 \
  --amend <registry>/carddav2fritzbox:<tag>-arm64
docker manifest push <registry>/carddav2fritzbox:<tag>
```

## CI example (GitHub Actions) — calls the script

```yaml
- uses: docker/setup-qemu-action@v3
- uses: docker/setup-buildx-action@v3
- uses: docker/login-action@v3
  with: { registry: ghcr.io, username: ${{ github.actor }}, password: ${{ secrets.GITHUB_TOKEN }} }
- run: docker/build.sh --push -t ghcr.io/<org>/carddav2fritzbox:${{ github.ref_name }}
- run: docker buildx imagetools inspect ghcr.io/<org>/carddav2fritzbox:${{ github.ref_name }}
```

Raw `build-push-action` with `platforms:` is acceptable when the repo already uses it, but the script remains the documented path for local use.

## Error cases

| Condition | Expected behavior |
|-----------|-------------------|
| QEMU binfmt not installed, `--push` attempted | Build fails early; helper prints hint to install binfmt / use `docker/setup-qemu-action` |
| Dockerfile pins `--platform=linux/amd64` in FROM | arm64 build fails; violates FR-004 — script build fails, remove the pin |
| `--push` without a registry tag (e.g., `carddav2fritzbox:local`) | Script exits with error: pushing requires a registry reference |
| `buildx build --platform linux/amd64,linux/arm64 --load` attempted directly | Fails: `--load` only supports single platform; script uses `--push` or per-arch `--load` |

## Contract test

```bash
# After cross-build --push via the script:
REGISTRY=ghcr.io/<org>/carddav2fritzbox
TAG=test-multiarch
docker/build.sh --push -t "$REGISTRY:$TAG"
assert_contains_platform() { docker buildx imagetools inspect "$1" | grep -q "linux/$2"; }
assert_contains_platform "$REGISTRY:$TAG" amd64
assert_contains_platform "$REGISTRY:$TAG" arm64

# Separation check:
! grep -q "docker build" docker/deploy.sh || { echo "FAIL: deploy.sh must not build"; exit 1; }
 test -x docker/build.sh || { echo "FAIL: build.sh not executable"; exit 1; }
```
