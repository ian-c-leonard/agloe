# 0004. The rules in words, with a reference checker that defines the right answer

- **Status:** Accepted
- **Date:** 2026-11-14
- **Decided by:** Ian Leonard

## Context

The COMPILER's answers must be right, and a person must be able to see why. Reading a solver model does not show whether its answer is right, and a solver cannot check itself. A set of principles on paper cannot be run, so its contradictions stay hidden until code depends on them.

## Options considered

1. **Build the CP-SAT model straight from the foundation.** The rules would exist only inside solver code. Nothing independent would say what the right answer is.
2. **Settle the whole foundation on paper before any code.** Nothing on paper can be tested, so mistakes in the rules would surface late.
3. **State each rule in words on one page, apply that page directly in a slow program with no solver, and require anything faster to agree with it.** This is how a proof checker stands beside a prover, and how the WebAssembly specification has a reference interpreter.

## Decision

The rules exist twice, and the two must agree.

- [`spec/rules.md`](../../spec/rules.md) states exactly what the COMPILER checks, in words a person can read in one sitting.
- The reference checker, `src/agloe/reference.py`, applies that page directly. It tries every possibility and uses no solver. It defines the right answer for small TRIPs.
- The CP-SAT COMPILER must give the same answers as the reference checker on every example and on random small TRIPs.
- A new rule enters in a fixed order: the page, the reference checker with its tests, the examples, and then the fast implementation.

## Consequences

- The reference checker is slow on purpose and handles only small TRIPs, so agreement is tested on small TRIPs.
- A mistake shared by the page and the reference checker would pass every agreement test. The page stays short enough for a person to check, and every example states its expected answer.
- The tests compare the reference checker's own shortcuts with slower methods that try every start time.
