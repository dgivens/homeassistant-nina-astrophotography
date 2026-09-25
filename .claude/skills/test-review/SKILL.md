---
name: test-review
description: >-
  Review a test suite for verbosity and scope creep — flags tests that are
  bloated, redundant, or that validate behavior owned by other packages,
  third-party libraries, or the standard library instead of the unit under
  test. Language-agnostic (Go, Python, TypeScript, Rust, and others).
---

# Test Review

A good test earns its place by pinning down one behavior that *this* unit owns,
in the fewest lines that make a failure obvious. Most test bloat comes from
tests drifting away from that: re-proving a dependency works, restating the same
path five times, or building elaborate scaffolding the assertion never reads.

Your job is to find that drift and cut it — without weakening real coverage.
Read the code under test (the SUT) and the tests that exercise it before judging
anything; "out of scope" only means something once you know what the unit's
actual contract is.

This is a review, not a rewrite. Propose cuts and tightenings; don't silently
restructure a passing suite unless asked.

## What to look for

Work through these lenses. They overlap — one test can fail several — so judge
the test as a whole, not lens by lens.

**Scope to the unit under test.** Every test should assert behavior this unit
owns. A test that fills an LRU cache and checks the *eviction order* is testing
the cache library, not your wrapper around it. A test that asserts
`json.Unmarshal` parsed a number is testing the stdlib. Testing a thin wrapper
is fine; re-testing what it wraps is the library author's job. When you see this,
say what the test is *actually* exercising and what the in-scope assertion would
be instead.

**Re-validating guarantees.** Drop assertions for things the type system, the
argument parser, or the constructor already enforce. Checking that a field you
just passed to a constructor comes back unchanged is tautological. Defensive
assertions for states that upstream code makes impossible add noise and a false
sense of coverage.

**Redundancy.** Two tests that drive the same code path. Table/parametrized
cases where several inputs all exercise one branch (three different valid emails
all hitting the "valid" path — keep one representative, plus the boundary and
invalid cases that hit *distinct* branches). Collapse them unless the split
genuinely documents separate intent.

**Verbosity.** Tests longer than the behavior they pin down. Setup that
constructs far more state than the assertion reads. One sprawling assertion that
hides which property failed — or, conversely, ten assertions that should be one
structural equality. Aim for: a reader sees the input, the action, and the
expected result without scrolling.

**Overspecified fixtures and helpers.** A fixture bigger or cleverer than any
test needs — returning a call-log nothing asserts on, supporting options no
caller passes. A bespoke helper where a language idiom is plainly simpler. A
fixture defined at a scope wider than its only user.

**Mocking boundary.** Mocks should sit at the edge this unit owns — deep enough
that you're not re-implementing a collaborator inside the test, shallow enough
that a refactor of the SUT's internals doesn't silently turn the mock into a
no-op. Flag mocks that assert against another package's interface.

**Coverage holes.** Tightening is not the same as gutting. While you're in here,
name real, untested behavior the suite should cover — but don't manufacture
cases for impossible inputs to pad the count.

**Consistency.** Match the conventions already in the suite (table tests,
fixtures, naming). Flag new patterns invented for no reason — but don't impose an
external style the codebase doesn't use.

## Examples

**Out of scope → tighten to the contract.**
- Before: a `Cache.Get` test that inserts past capacity and asserts the oldest
  key was evicted. That's the LRU library's behavior.
- After: assert `Get` returns what `Put` stored, and that a miss returns the
  documented sentinel. That's *your wrapper's* contract.

**Redundant table cases → one representative + the distinct branches.**
- Before: `{"a@b.com", true}, {"x@y.org", true}, {"p@q.io", true}, {"nope", false}`
- After: `{"a@b.com", true}, {"nope", false}, {"", false}, {"@b.com", false}` —
  one valid case, plus the invalid shapes that exercise *different* rejections.

**Overspecified fixture → drop what nothing reads.**
- Before: `newFakeClient()` returns a struct carrying a `calls []Request` log,
  but no test inspects `calls`.
- After: return the fake without the log. Add it back the day a test asserts on
  it.

## Output

Lead with a one-line verdict and an impact rating: **High / Medium / Low** (how
much the bloat actually costs in maintenance and false confidence).

Then a short, severity-ranked list of findings. For each: `file:line`, what's
wrong (which lens), why it matters, and the concrete cut or rewrite — a
before/after snippet when it clarifies the change. Separate must-fix from
nice-to-have.

Be brief and honest. If a test is already minimal and correctly scoped, leave it
alone — and if the whole suite is sound, say so in a sentence and stop. Don't
manufacture complexity to have something to report; an empty finding list on a
tight suite is a good outcome, not a failed review.
