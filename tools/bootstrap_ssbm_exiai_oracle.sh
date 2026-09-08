#!/usr/bin/env bash
set -euo pipefail

readonly EXIAI_RELEASE="exi-ai-0.2.0"
readonly EXIAI_ASSET="Slippi_Online-x86_64-ExiAI.AppImage"
readonly EXIAI_SHA256="87e9ef6d80ed03354a1647d0616016dbc91399aa9e86a69ae5a398edd0a0c2bd"
readonly EXIAI_URL="https://github.com/vladfi1/slippi-Ishiiruka/releases/download/${EXIAI_RELEASE}/${EXIAI_ASSET}"
readonly LIBMELEE_VERSION="0.47.2"
readonly DME_VERSION="1.3.1"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
install_root="${1:-${repo_root}/build/oracle-toolchain/exiai-0.2.0}"
venv_root="${2:-${repo_root}/build/oracle-toolchain/exiai-python}"
artifact="${install_root}/${EXIAI_ASSET}"
launcher="${install_root}/squashfs-root/AppRun"

mkdir -p "${install_root}"

if [[ ! -f "${artifact}" ]]; then
    download="${artifact}.download"
    curl --fail --location --retry 3 --output "${download}" "${EXIAI_URL}"
    mv "${download}" "${artifact}"
fi

actual_sha256="$(sha256sum "${artifact}" | awk '{print $1}')"
if [[ "${actual_sha256}" != "${EXIAI_SHA256}" ]]; then
    echo "unexpected ExiAI artifact SHA-256: ${actual_sha256}" >&2
    exit 1
fi
chmod +x "${artifact}"

if [[ ! -x "${launcher}" ]]; then
    extract_root="$(mktemp -d)"
    cleanup() {
        rm -rf -- "${extract_root}"
    }
    trap cleanup EXIT
    (
        cd "${extract_root}"
        "${artifact}" --appimage-extract >/dev/null
    )
    mv "${extract_root}/squashfs-root" "${install_root}/squashfs-root"
    trap - EXIT
    rmdir "${extract_root}"
fi

python3 -m venv "${venv_root}"
"${venv_root}/bin/python" -m pip install --disable-pip-version-check \
    "melee==${LIBMELEE_VERSION}" \
    "dolphin-memory-engine==${DME_VERSION}"

"${venv_root}/bin/python" - <<'PY'
import importlib.metadata

expected = {
    "melee": "0.47.2",
    "dolphin-memory-engine": "1.3.1",
}
observed = {name: importlib.metadata.version(name) for name in expected}
if observed != expected:
    raise SystemExit(f"unexpected oracle Python packages: {observed}")
PY

version="$({ "${launcher}" --version 2>&1 || true; } | head -n 1)"
if [[ "${version}" != "Faster Melee - Slippi (3.5.1) - ExiAI" ]]; then
    echo "unexpected ExiAI launcher version: ${version}" >&2
    exit 1
fi

printf 'ssbm-exiai-oracle-bootstrap=pass\nlauncher=%s\npython=%s\n' \
    "${launcher}" "${venv_root}/bin/python"
