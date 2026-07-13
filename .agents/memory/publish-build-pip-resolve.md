---
name: Publish build re-resolves requirements.txt
description: Why a publish can fail on pip even though the dev venv works, and how to keep pins publish-safe.
---

# Publish build re-resolves requirements.txt through the package firewall

The publish build runs a fresh `pip install -r requirements.txt` resolve, routed through
Replit's supply-chain firewall (package-firewall.replit.local). Two failure modes seen Jul 2026:

1. **Stale pins after an in-venv upgrade.** Upgrading a package with pip can silently pull up
   its dependencies (e.g. google-genai 1.75.0 forced google-auth 2.40.3→2.55.2) — dev works,
   but requirements.txt still pins the old dep → ResolutionImpossible/backtracking at build time.
2. **Firewall-blocked pinned versions.** Old versions with known vulnerabilities can be 403-blocked
   (Django 5.2.4 was; 5.2.16 allowed). Dev doesn't notice because the package is already installed.

**Why:** dev venv state and requirements.txt drift apart; the build trusts only the manifest.

**How to apply:** after any pip upgrade, update requirements.txt for the package AND any deps pip
bumped; before suggesting publish after dependency changes, run
`timeout 110 .venv/bin/pip install --dry-run --ignore-installed -q -r requirements.txt`
— it must resolve with no ERROR lines (a yanked-version WARNING for pinned newrelic is harmless).
