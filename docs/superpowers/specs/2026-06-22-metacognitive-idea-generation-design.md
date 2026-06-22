# Metacognitive Idea Generation Design (Phase 2: learn from outcomes)

## Objective

Make looptight's idea generation learn from outcomes. Today the loop generates
ideas from a single-shot prompt (`prompts.PLANNING_GOAL`) over five discovery
sources (`lint`, `todo`, `skipped-test`, `status-next`, `task-file`), with no
memory of which ideas actually paid off. This design adds the missing layer: a
record of each idea's real outcome, a model built from that record, and feedback
that steers the next round of generation.

The existing `metacog.py` already covers "should I keep iterating on *this*
task?" (value-aware stopping within one task's iteration loop, grounded in
value-of-computation). This is the second layer: metacognition over the
*planning* loop itself, so the system gets smarter about *what to work on*.

The guiding loop is **monitor -> self-model -> control**, with one hard rule:
the configured `verify` command stays the ground-truth outcome signal. The
self-model is built from objective pass/merge facts, never from an agent claiming
it did well.

## Decisions

These were settled during design (see the design conversation and the infra
review that revised the storage layer):

1. **Learn from outcomes** is the goal, the deepest metacognition lever.
2. **Specific-idea memory first**, category statistics layered on top.
3. **Positive signal is shared and verifiable; negative signal is local.**
   `landed` is recorded as a git commit trailer that any clone can independently
   re-verify. `failed` lives in the repo-private coordinator database and does
   not cross a repository boundary.
4. **Reuse existing machinery**: commit trailers and ancestry checks from
   `integration_queue.py`, attempt semantics and storage from `coordinator.py`,
   source weights from `ranking.py`. Add no runtime dependencies (`json` and
   `hashlib` only).
5. The self-model is **advisory**: if it is missing, empty, or unreadable, idea
   generation degrades to today's behavior.

### Why this storage shape

An earlier proposal used a sharded, git-tracked JSONL log so the experience
memory could be shared across developers and written by many parallel
orchestrators. An infrastructure review rejected it for reasons confirmed in the
code:

- **"Verify is the checker" is unenforceable on a self-reported line.** Once a
  shard is pulled over git, a `landed` line is just text another party wrote,
  with no way to re-derive that the claimed result reached the verified ref.
- **The advisory lock is single-host.** `IntegrationLock` is `fcntl.flock`
  (`integration_queue.py`), so a lock-guarded compaction step cannot serialize
  compactors on two machines. Two of them would diverge and delete each other's
  shards, recreating the merge conflict that sharding was meant to avoid.
- **Per-round outcome commits collide with a written non-goal.** A content-free
  "this failed" commit every round in a 24/7 daemon is exactly the
  "model-generated project memory after every failure" that `docs/SPEC.md` lists
  as a non-goal.

The resolution keeps the multi-developer goal for the part that can be made
correct. Git history is already a shared, append-only, conflict-free,
independently verifiable log. We annotate it with `landed` trailers instead of
building a parallel log. Shared *negative* learning needs a provenance or signing
story and is deferred (see Deferred work).

## Goal and Non-Goals

In scope (MVP):

- Record `landed` and `failed` outcomes, keyed by a stable idea identity.
- Build a bounded self-model: per-identity outcome history plus per-category
  yield statistics.
- Feed the model back into generation three ways: suppress recently-failed ideas
  (bounded cooldown), reweight ranking by category yield (clamped), and inject a
  token-bounded experience summary into the planning prompt.

Out of scope (Deferred work, below):

- Shared *negative* learning across untrusted developers (needs provenance).
- A `churn` outcome state. It overlaps the existing empty-diff handling in
  `swarm.py` and risks penalizing an honest "no necessary change exists".
- Recording outcomes from the pure session-native `next`/`verify` path, where
  looptight does not own the commit.
- Predicted-value (EVOC) scoring of candidates before doing them.

## Idea Identity

The current task fingerprint (`tasks.py`, `sha256` of `location + title`) is the
wrong key here. `location` is `file:line` and `title` is a ruff message or TODO
text, so the fingerprint rotates whenever a line moves or a message is reworded
(same idea, new key) and collides across different ideas sharing a line. Keying
outcomes on it would let suppression lapse on any unrelated edit and let
`aggregate` rows accumulate without bound.

Add a separate, deliberately lossy idea identity in a small new module
(`idea_identity.py`), computed in one place and used by both the write path and
the read path so the two cannot drift:

| Source | Identity tuple |
|--------|----------------|
| `lint` | `(lint, normalized-path, rule-code)` (drop line and message text) |
| `todo` | `(todo, normalized-path, normalized-comment-text)` (drop line) |
| `skipped-test` | `(skipped-test, normalized-test-id)` |
| `status-next`, `task-file` | `(source, normalized-title)` using the existing `ranking._normalized` |

The identity is the `sha256` of the joined tuple, truncated for compactness. The
line-precise `tasks.py` fingerprint stays unchanged for task *claims*.

## Architecture

```
            ┌──────────── git history (verifiable, shared) ────────────┐
            │  integration commits carry: Looptight-Outcome: <id> landed <sha>  │
            └───────▲───────────────────────────────────────────┬──────┘
   (1) MONITOR      │ trailer on the existing commit (landed)     │ (2) SELF-MODEL
   verify-gated ────┤                                             ▼   verified-landed + local-failed
   integrator       │ failed -> coordinator DB (repo-private)   cached aggregate
                    │   (no commit, never pushed)                 │  keyed by idea identity
                    └─────────────────────────────────────────────┘
                                                                  │ (3) CONTROL
                                  ┌───────────────────────────────┴───────────────┐
                          deterministic (discovery + ranking)        generative (planner prompt)
                          cooldown-suppress failed ids                token-bounded experience summary
                          clamped reweight by category yield          (grounding rail kept last)
```

### (1) Monitor: the write path

The verify-gated integrator owns this. The agent never writes here.

- **`landed`**: when the integrator merges a verified branch and advances the
  ref, it adds a trailer to that same commit:
  `Looptight-Outcome: <idea-id> landed <result-sha>`. This is atomic with the
  work, recoverable via `git log --grep` exactly like the existing
  `Looptight-Integration-ID` trailer, and adds zero new commits. Reuse the
  trailer-writing path already in `integration_queue.py`
  (`_trailer_commit_on_ref`).
- **`failed`**: when a task exhausts its attempts or its verify never passes,
  the integrator records `(idea-id, category, failed, attempt-count, timestamp)`
  in a new coordinator table. No commit, repo-private, never pushed.

Reconcile with the existing empty-diff path: `swarm.py` already marks an empty
diff as `failed` ("agent produced no changes"). That stays the single source of
truth for "no change produced"; we do not add a second, disagreeing path, and we
do not penalize a planner that correctly returns "no necessary change exists".

### (2) Self-model: the read path

A pure function builds a bounded model from two inputs:

- **Verified landed**: scan integration commits for `Looptight-Outcome ... landed
  <sha>` trailers, and count a record only if `merge-base --is-ancestor <sha>
  <target>` holds (reuse `integration_queue._is_ancestor`). This is what makes
  the shared signal tamper-evident: a forged trailer whose sha never reached the
  ref is ignored.
- **Local failed**: read the coordinator table.

The model exposes, keyed by idea identity: `landed` count, `failed` count, last
outcome and when, plus per-category aggregate yield (landed / (landed + failed)).

**Caching.** Scanning `git log` on every `next`/plan does not scale on a
long-lived repo. The coordinator holds an incrementally refreshed cached
aggregate (repo-private), rebuilt only from trailers newer than the last scanned
commit, so reads are O(new commits), not O(history).

### (3) Control: feedback into generation

Two consumers, both reading the same model.

Deterministic, inside discovery and ranking:

- **Cooldown suppression, not a blacklist.** An idea whose identity has a recent
  `failed` and no later `landed` is suppressed for a bounded window (N rounds, or
  until its evidence text changes so the identity changes), mirroring the
  coordinator's `attempts` / `max_attempts` requeue semantics. After the window
  it is re-admitted. A persistently failing idea routes to the existing
  `metacog` ESCALATE path (human attention), not silent permanent suppression.
- **Clamped reweight.** Ranking multiplies a source's weight by a factor derived
  from its category yield, clamped to a tight band (for example `[0.5, 1.5]`) and
  applied *under* `_SOURCE_WEIGHT` so curated `task-file` / `status-next` intent
  always dominates. A source is never zeroed. This bounds the rich-get-richer
  dynamic that would otherwise push the loop toward trivial lint nits and away
  from hard but valuable work.

Generative, in the planning prompt:

- A token-bounded experience summary is appended to `PLANNING_GOAL`: a short list
  of recently-failed identities to avoid and the top category yields, regenerated
  from the cached aggregate (not raw history). The grounding rail ("if no
  necessary improvement is supported by repository evidence, make no changes")
  stays last and dominant so the summary cannot dilute it.

## Concurrency and the multi-developer model

- **Positive learning is shared and parallel-safe by construction.** `landed`
  flows through git history. Many parallel integrators produce many commits;
  there is no shared mutable file to conflict on, and `merge-base --is-ancestor`
  anchors verification. A fresh clone inherits "what works" for free.
- **Negative learning is local.** `failed` and cooldown state live in the
  coordinator database, which already serializes many sessions on one machine
  (WAL, leases). A fresh clone relearns "what fails" locally over time.
- **The asymmetry is deliberate and documented**, so behavior is predictable:
  trust shared positive signal, keep unverifiable negative signal local.

## Integrity and Error Handling

- Outcomes derive from verify results and merge facts, never from agent
  self-report.
- A `landed` trailer is trusted only after an ancestry check; a forged or
  dangling one is ignored.
- Corrupt or partial state (an unreadable cache, a malformed trailer) is skipped,
  never fatal. The self-model degrades to empty, and generation falls back to
  today's behavior. A learning signal must never block a build or fail verify.
- Suppression is always escapable (bounded window, or identity change on evidence
  change), so the loop cannot permanently blacklist work that becomes valid
  again.

## Bounding and Cost

- Zero net new commits: `landed` rides the existing integration commit, `failed`
  is database-only.
- The cached aggregate is bounded (counts per identity and per category, pruned
  by age and capped in size), matching the "keep state bounded, git is the
  archive" ethos.
- The injected experience summary is hard-bounded to top-K items.

## Files

New:

- `src/looptight/idea_identity.py` plus `tests/test_idea_identity.py`: the
  per-source lossy identity and its stability and collision tests.
- `src/looptight/experience.py` plus `tests/test_experience.py`: the self-model
  reader (verified-landed scan, local-failed read, cached aggregate) and the
  control helpers (cooldown decision, clamped reweight, summary builder).

Modified:

- `src/looptight/coordinator.py`: a `failed`/cooldown table and the cached
  aggregate; attempt-based cooldown helpers.
- `src/looptight/integration_queue.py`: write the `landed` trailer on the
  integration commit; expose the verified-landed scan.
- `src/looptight/discovery.py` and `src/looptight/ranking.py`: apply cooldown
  suppression and the clamped reweight, both advisory and order-stable.
- `src/looptight/prompts.py` (or a thin builder beside it): assemble the bounded
  experience summary with the grounding rail kept last.
- Docs: `docs/architecture.md` (the Phase 2 loop), `docs/SPEC.md` if any output
  contract changes (the trailer is additive and internal).

## Testing (TDD)

1. Identity: same idea across line moves and message rewording yields one
   identity; genuinely different ideas do not collide; identity is stable across
   the equivalent `status-next` / `task-file` routing.
2. Monitor: a verified merge writes exactly one `landed` trailer with the result
   sha; a failed task writes one coordinator row; an empty-diff path is not
   double-recorded; a planner "no changes" is never recorded as failure.
3. Self-model: a `landed` trailer whose sha is an ancestor of the target counts;
   a dangling or forged trailer does not; the cache rebuilds incrementally and
   equals a full scan.
4. Control: a recently-failed identity is suppressed, then re-admitted after the
   window or on evidence change; the reweight stays within the clamp and never
   reorders curated sources below automated ones; the prompt summary is bounded
   and keeps the grounding rail last.
5. Concurrency: many integrators writing trailers in parallel produce a correct
   union with no conflict (mirror the existing multiprocess coordinator tests).
6. Degradation: missing or corrupt experience state leaves discovery, ranking,
   and the prompt byte-for-byte at today's behavior.
7. Gate: `looptight verify --json` returns `pass` before commit.

## Deferred work (Phase 3)

- **Shared negative learning across untrusted developers.** Needs a provenance
  or signing scheme so a `failed` signal from another party cannot poison
  everyone's suppression and ranking. Until then, negative signal is local.
- **`churn` as a distinct outcome.** Revisit only if `landed` vs `failed` proves
  insufficient, and only after reconciling it with the empty-diff path.
- **Session-native outcome recording.** Needs a way for looptight to observe an
  outcome it did not commit. Until then, the self-model is an orchestrator
  feature, and the pure session-native `next` path is steered only by the
  git-verifiable `landed` signal, not by swarm-only `failed` data.
- **Predicted-value (EVOC) candidate scoring**, tying the planning loop directly
  into the value-of-computation model in `metacog.py`.
