#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

OUTPUT_DIR="docs"

# start from scratch, so pages of removed/renamed modules don't linger
rm -rf "$OUTPUT_DIR"

# pdoc skips private (`_*.py`) submodules when walking a package,
# so every module file is passed explicitly to include them in the docs.
poetry run pdoc -o "$OUTPUT_DIR" $(find adcm_aio_client -name '*.py' -not -path '*/__pycache__/*' | sort)
