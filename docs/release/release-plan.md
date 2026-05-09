# Release plan

## Release preparation

1. Keep code and generated corpus artifacts in separate repositories.
2. Verify no secrets are committed.
3. Bump `VERSION` and `pyproject.toml` together when the runtime changes.
4. Add or update the matching entry in `CHANGELOG.md`.
5. Verify tests pass from a clean checkout.
6. Run `python scripts/validate_versioning.py`.
7. Generate corpus index and packaging/provenance report when public artifacts changed.
8. Review public-facing language for provenance, authorship boundaries, and historical-only migration notes.

## Version-control and release gates

- `VERSION`, `pyproject.toml`, and `CHANGELOG.md` agree before release.
- Runtime/package renames are called out under the current changelog entry.
- Compatibility aliases and legacy artifact paths are documented before old names are removed.
- Release commits should be tagged after validation when publishing a public runtime release.

## Public release gates

- License selected and checked in.
- Secrets rotated if necessary.
- README updated with provenance and no-human-authorship framing.
- Corpus packaging/provenance lint scanner passes: no TODO placeholders, no fake citations, no missing evidence bundles.
- Website/catalog generated.
