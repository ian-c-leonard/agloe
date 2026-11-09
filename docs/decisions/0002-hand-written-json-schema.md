# 0002. A hand-written JSON Schema is the source of truth

- **Status:** Accepted
- **Date:** 2026-11-08
- **Decided by:** Ian Leonard

## Context

The schema defines what a valid FILE looks like. Agloe is first a data format, stored for years and exchanged between tools, so its schema is the contract every other implementation builds on. It must be language-neutral, readable and impossible to drift.

## Options considered

1. **JSON Schema written by hand.** The source is the published contract itself, and validators exist in every major language. It is verbose to write.
2. **Schema written in program code, with JSON Schema generated from it** (Pydantic, TypeBox, Zod). Concise and pleasant, but the published contract becomes an output of one language's library.
3. **LinkML, a modeling language that generates JSON Schema.** Rich modeling and documentation, but one more toolchain and one more layer to drift.

Comparable data formats keep a hand-maintained JSON Schema beside a written specification: OpenAPI, CycloneDX (Ecma standard ECMA-424) and STAC. Protocols defined by TypeScript-centric teams, such as the Model Context Protocol, write TypeScript first and generate the schema.

## Decision

The schema is written by hand in JSON, using JSON Schema 2020-12, and is the single source of truth for the shape of a FILE.

- The written specification is authoritative. The schema checks structure; the COMPILER checks everything the schema cannot express.
- Python models are generated from the schema, never the other way round, and the build checks that they match.
- Every number the COMPILER calculates with is exact: times are standard timestamps converted to whole seconds, money is in whole minor units such as pence or cents, and rates are exact decimal text such as "1.2". The schema never uses binary floating-point numbers for these.

## Consequences

- The schema is verbose; keeping the core vocabulary small keeps it manageable.
- Exact numbers suit CP-SAT, which works only in whole numbers, and protect the rule that the same FILE gives the same answer.

## Confirmation

CI validates every example FILE against the schema, regenerates the Python models and fails if they differ from the committed ones.
