#!/usr/bin/env sh
# Install shared git hooks (blocks direct push to main).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
git config core.hooksPath .githooks
echo "Git hooks installed. core.hooksPath = .githooks"
echo "Direct pushes to 'main' are blocked locally. Use branch 'dev' for integration."
