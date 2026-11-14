# Playtest log

## Round 1 — 2026-11-12 ~01:30 EST (5 matches + smoke test)
Harness: tests/playtest.py, 1000ms ticks (mechanics identical to 3000ms default).

| # | Match | Ticks | Result |
|---|-------|-------|--------|
| 1 | grazer vs hunter | 30 | hunter plateaus 46c/67e, grazer 62c/89e |
| 2 | grazer vs wall | 30 | wall 44c/180e, grazer 63c/91e |
| 3 | hunter vs wall | 30 | wall 44c/175e, hunter 63c/91e |
| 4 | grazer vs grazer | 30 | 46c/66e vs 63c/88e — same species, spawn luck decides |
| 5 | grazer vs hunter vs wall | 30 | all plateau by tick 10-15, frozen after |
| 6 | grazer vs hunter, seed 7 | 60 | plateau by tick 20 (hunter 60, grazer 49), frozen 40 ticks |

Findings (round 1):
- F1. Species almost never meet: random spawn across 256x256 -> hunter's
  attack and wall's defense never matter; hunter vs wall == grazer vs wall.
- F2. Game freezes after the opening: no deaths, no attacks, no movement
  after ~tick 15. Low-energy cells strand on food-less cells (MOVE costs 2,
  no upkeep, no way to sense food beyond own cell).
- F3. Mirror match decided by spawn luck (food/space near the cluster).
- F4. New console player can die of timeout before loading rules
  (fixed already: client heartbeat, empty intentions every tick).
- F5. Food invisible on both pages (world view colors species only).
- F6. Console onboarding: empty template editor, two separate clicks
  (load rules, then submit) before anything happens.

Fixes for round 2 (implementation/experience layer only):
- Spawn clusters near the world center so species meet and fight.
- Console: default to grazer rules (auto-loaded + auto-playing), editor
  shows the loaded rules; Submit loads the editor content and submits
  in one click.
- Food layer on both world views (green dots), refreshed periodically.
- NOT changed (needs Shu's call, reported as open design question):
  energy economy has no upkeep/scarcity; food is abundant (8% cells,
  +300/epoch). Whether to add upkeep or reduce food is a spec-level
  decision, not silently changed here.

## Round 2 — 2026-11-12 ~02:00 EST (fixes from round 1 + 4 matches)
Fixes applied before this round:
- Spawn: random whole-world -> clusters near center (+/-40, then +/-12).
  Combat now happens (was 0-1 attacks, now 5-8 per 30 ticks).
- Action totals instrumentation: sim counts -> server /api/players totals.
- Console: default grazer rules auto-loaded + auto-playing; editor shows
  the loaded rules; Submit loads editor content and submits in one click.
- Food layer on both world views (green dots); spectator refreshes the
  full snapshot every 30s to keep food honest (food is not in deltas).
- Tick rate: deadline_ms now scales with tick_ms (was 0.30 ticks/sec at
  1000ms ticks, now 1.00). Console heartbeat: empty intentions every
  tick when no rules are loaded, so a new player is not killed as
  "timed out" while reading the page.

| # | Match | Ticks | Result |
|---|-------|-------|--------|
| 7 | grazer vs hunter | 30 | 45 vs 45, 6 attacks — close game |
| 8 | hunter vs wall | 30 | hunter 47, wall 38 (lost cells), 5 attacks, wall armored 10x |
| 9 | grazer vs hunter, seed 3 | 60 | hunter wins early (grazer 41->40), frozen tick 20-60, 7 attacks |
| 10 | grazer_v2 vs hunter_v2 (eat uncapped, move only if en>4) | 60 | WORSE: 3 attacks, 19 eats, frozen by tick 10 — variants rejected, not adopted |

Findings (round 2):
- F7. Combat works now: attacks land, wall's CHANGE armor triggers when
  threatened, hunter wins early fights. But the game still freezes after
  ~tick 15-20: static equilibrium, no deaths, no territory swings.
- F8. The freeze is structural to v0.1 as specified: sense radius 1 and
  eat-own-cell-only make movement blind; no upkeep means stranded cells
  never die and boxed-in cells never free space; no win condition means
  a stabilized game just sits there. Example-rule tuning cannot fix it
  (the v2 variants proved it: more conservative play freezes faster).
- F9. Console default flow verified: fresh console auto-connects and
  auto-plays as grazer (44 cells at tick 8 -> 54 at tick 14), editor
  pre-filled with grazer, food layer present in /api/state.
- Open design questions for Shu (NOT silently changed): upkeep/metabolism?
  larger sense radius? win condition / match timer? world-rules pressure
  (food decay, droughts, moving fertile zones)? Any of these unfreezes
  the game but each touches the spec.

## Round 3 — 2026-11-12 ~02:15 EST (stability, varied seeds)
| # | Match | Ticks | Result |
|---|-------|-------|--------|
| 11 | grazer vs wall, seed 11 | 30 | wall 43, grazer 55; 0 attacks (grazers don't attack), wall armored 9x on contact |
| 12 | hunter vs hunter, seed 5 | 30 | 53 vs 45, 8 attacks — mirror decided by spawn + early fights |
| 13 | wall vs wall, seed 9 | 30 | 42 vs 40, 0 moves, 10 armor changes — pure growth race |
| 14 | grazer vs hunter, 3000ms ticks | 10 | 10 ticks in 32.3s (target 30s); 7 attacks in 10 ticks |

## Round 4 — 2026-11-12 ~02:30 EST (edge cases, all in tests/edge_test.py)
- Empty world snapshot with no players: OK.
- Bad rules (syntax error): rejected with the error message, client stays
  connected and keeps playing: OK.
- Slow rules (decide sleeps 5s): 2s timeout, empty intentions, error
  surfaced in console state, good rules restore and executor recovers: OK.
- Disconnect + reconnect with the same name: cells die, reconnect gets a
  new player_id and fresh starter cells: OK.
- Infinite-loop rule: client survives on heartbeats (cells stay alive,
  40 throughout), timeout error surfaces every tick; executor stays
  stuck until the client restarts (documented limitation).
- Fix from this round: executor `last_error` is now cleared on a
  successful run (was showing a stale timeout forever after recovery).

## Round 5 — 2026-11-12 ~03:00 EST (4-player + spectator names)
| # | Match | Ticks | Result |
|---|-------|-------|--------|
| 15 | grazer vs hunter vs wall vs grazer, seed 4 | 30 | 43/43/31/33, 18 attacks, 26 armor changes — most combat yet; tick timing held (30 ticks in 30.9s) |
- Fix: spectator page seeds player names from /api/players on connect
  (a page opened mid-game used to show #id for existing players).

## Round 6 — 2026-11-12 ~03:15 EST (world rules: temperature)
- Finding: the temperature cycle was decorative — the mean never left
  [12, 28], so reproduce_enabled never flipped.
- Fix: default world rules now steer the mean toward
  20 + 9*sin(tick/30) with proportional control (gain 0.7); /api/players
  exposes mean_temp + constraints; the spectator page shows them.
- Match 16 (grazer vs hunter, 120 ticks): reproduce_enabled flipped
  OFF at tick 50 (mean temp 28.7) and back ON at tick 80 (25.0); the
  hot snap is a real, visible event. Final mean temp 14.2 (heading
  cold). Populations still froze at 46/45 — the snap pauses growth but
  does not unfreeze the game.

## Round 7 — 2026-11-12 ~03:45 EST (balance tournament, 30 ticks each)
| # | Match | Seed | Result | Attacks |
|---|-------|------|--------|---------|
| 7 | grazer vs hunter | 0 | 45 vs 45 tie | 6 |
| 9 | grazer vs hunter | 3 | hunter 53, grazer 40 | 7 (60 ticks) |
| 17 | grazer vs hunter | 21 | hunter 44, grazer 42 | 8 |
| 18 | grazer vs hunter | 22 | hunter 47, grazer 37 | 6 |
| 19 | hunter vs wall | 23 | hunter 48, wall 41 | 4, wall armored 8x |
| 20 | grazer vs wall | 24 | grazer 46, wall 44 | 0, wall armored 12x |

Balance read: hunter > grazer ≈ wall. Hunter's edge is consistent but
modest (2-13 cells over 30 ticks) — it is a strict upgrade over grazer
in combat (attacks only when it can win, gains victim energy). Wall's
armor works but it loses the growth race (never moves). Left as-is:
the examples demonstrate different strategies, and the edge is small
enough for a demo. If Shu wants a tighter balance, the lever is the
hunter's attack margin (currently any strict energy advantage wins).

## Round 8 — 2026-11-12 ~05:00 EST (newbie flow + arbiter crash fix)
- Newbie flow (fresh console -> custom "turtle" rule -> preview -> submit
  -> live play) found a real bug: preview crashed with
  "all keys need to be the same shape".
- Root cause (arbiter): after the precondition filter dropped rows, the
  `strength` array was not filtered, so `np.lexsort` got mismatched key
  lengths. The bundled species pre-check their targets, so it never
  fired before; any newbie rule that does not pre-check (e.g. REPRODUCE
  into an occupied neighbor) crashed the arbiter -- and in the live
  server that would kill the sim process. Fix: `strength = strength[idx]`.
- Second layer (executor): `to_intentions` now drops rows whose src is
  not one of the player's own cells (a full (n,7) return leaves zero
  rows for idle cells; those are bogus MOVE (0,0)->(0,0) intentions).
- Regression test added: tests/arbiter_regression.py (mixed valid/
  invalid/zero/foreign/out-of-bounds intentions -> only the valid ones
  resolve, no crash).
- After the fix the newbie flow works end to end: preview 100 ticks ->
  29 cells, 14 births, 7 eats; submit ok; live play 43 cells at tick 10.
- Full suite re-run after the fix: smoke, e2e, gui, edge, arbiter
  regression -- all pass.

## Round 9 — 2026-11-12 ~05:30 EST (post-fix confirmation + README)
- README updated: arbiter robustness note, /api/players totals + temp,
  temperature snap verified, balance read, full test list.
| # | Match | Seed | Result | Attacks |
|---|-------|------|--------|---------|
| 21 | grazer vs hunter | 41 | hunter 48, grazer 40 | 6 |
| 22 | hunter vs wall vs grazer | 42 | hunter 48, grazer 48, wall 37 | 7, wall armored 14x |
- No regressions from the arbiter/executor fixes; outcomes match the
  round-7 balance picture.

## Round 10 — 2026-11-12 ~06:00 EST (final stability, fresh combos)
| # | Match | Seed | Result | Attacks |
|---|-------|------|--------|---------|
| 23 | wall vs hunter vs hunter vs grazer | 51 | wall 40, hunter2 33, hunter3 28, grazer 22 | 55, wall armored 23x |
| 24 | grazer vs grazer vs hunter | 52 | hunter 48, grazers 47/41 | 12 |
- Match 23 is the most dynamic game yet: 55 attacks, the grazer was
  hammered down to 22 cells, wall held on armor. High player density
  (4 players, close spawn) makes the early game genuinely combative.
  2-player games still stabilize after ~tick 15; 4-player games are
  the most fun configuration in v0.1.
- No new issues in this round. Playtesting stops here: 24 matches total
  across 10 rounds, all verification suites green.

## Core interface candidate — 2026-11-13

- Client breathing and event animations start enabled, with a manual toggle.
- Added the GUI-independent `cellgame.api` facade, a player runtime in species,
  and an authoritative settlement phase in server.kernel. Existing imports remain compatible.
- Contract 1.0.0-rc.1 specifies transport/observation, Python player/world hooks,
  local model messages, authority, identity scope, binary layouts and compatibility.
- Explicit protocol negotiation, strict integer actions, canonical little-endian
  arrays and observation validation cover malformed and future inputs.
- Entity IDs are reconciled before subsequent observations; Cell helpers expose
  visible materials/biomes and distinguish unknown neighbors from empty tiles.
- Passed core/SDK/world-rule regression scripts, HTTP/stdio model checks, UI
  checks, independent JavaScript golden-fixture decoding, legacy/radius/blanket
  and cooperation live-game tests, plus a GUI-free protocol-agent connection.
- Built the wheel and verified its public imports, packaged contract/schema/fixtures,
  CLI discovery and live server/client away from the source checkout. Windows
  console launchers passed using a normal temporary path in the workspace; the
  environment's special `#!sandbox` temporary path failed at the launcher stage.
- Updated two stale test fixtures: v1 env has 12 columns including bonds;
  optional observation layers must stay aligned when removing tiles.
- Persistent Unity membership, generic layer registration, complete lifecycle
  events, resync/replay and an independently distributed core wheel remain future work.
