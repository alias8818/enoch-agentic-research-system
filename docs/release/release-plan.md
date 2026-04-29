# Release plan

## Release preparation

1. Keep code and generated corpus artifacts in separate repositories.
2. Verify no secrets are committed.
3. Verify tests pass from a clean checkout.
4. Generate corpus index and quality report.
5. Review public-facing language for provenance, authorship boundaries, and historical-only migration notes.

## Public release gates

- License selected and checked in.
- Secrets rotated if necessary.
- README updated with provenance and no-human-authorship framing.
- Corpus quality scanner passes: no TODO placeholders, no fake citations, no missing evidence bundles.
- Website/catalog generated.
