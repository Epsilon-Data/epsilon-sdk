#!/bin/sh
# Blocks commits that introduce secrets. Install gitleaks: brew install gitleaks
# (or https://github.com/gitleaks/gitleaks/releases). CI runs the same scan.
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks git --pre-commit --staged --redact --no-banner
else
  echo "warning: gitleaks not installed (brew install gitleaks) - skipping local secret scan, CI will run it" >&2
fi
