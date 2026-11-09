# 0003. Apache License 2.0 for code and specification

- **Status:** Accepted
- **Date:** 2026-11-08
- **Decided by:** Ian Leonard

## Context

Agloe is built in public, and its format is meant to become a standard that others implement. The license must be settled before the first commit, because changing it later needs every contributor's consent.

## Options considered

1. **Apache License 2.0.** Permissive, with an explicit patent grant. Used by OpenAPI, Kubernetes and Swift.
2. **MIT.** The shortest permissive license, with no patent grant.
3. **MIT or Apache 2.0, at the user's choice.** The Rust ecosystem's convention; maximizes compatibility.
4. **MPL 2.0, GPL or AGPL.** Copyleft licenses that require sharing changes, which companies often avoid.
5. **A separate documentation license, such as CC BY 4.0, for the specification text.**

## Decision

Agloe's code and specification are both licensed under the Apache License 2.0.

- The patent grant protects everyone who implements the format, which matters for a standard.
- One license for everything is simpler than separate licenses for code and text.
- Contributions are covered by the license's own section 5, so no separate contributor agreement is needed.
- Section 6 grants no trademark rights, so others may implement the format but may not call their version Agloe.

## Consequences

- Copyleft is ruled out, because adoption is the point of a standard.
- The NOTICE file names the copyright holder.
