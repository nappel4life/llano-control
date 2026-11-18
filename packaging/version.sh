#!/usr/bin/env bash
# Steht die Version fest: aus llanotool/__init__.py, und auf einem Marken-Tag
# (v1.2.3) nimmt die Bau-Umgebung die Marke. Gibt Zeilen der Art VERSION=1.0.0
# aus, die man in eine Umgebungsdatei schreiben kann.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Unter Windows heisst der Aufrufer nur "python".
PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"
VERSION="${VERSION:-$("$PYTHON" -c 'import llanotool; print(llanotool.__version__)')}"

case "${GITHUB_REF:-}" in
    refs/tags/v*) VERSION="${GITHUB_REF#refs/tags/v}" ;;
esac

echo "VERSION=$VERSION"
