# Every Compat (Wood Good) + Stone Zone in TBA

Added in TBA 2.0.12, in a trimmed setup ("slim"). This page records what the two mods do, how TBA
configures them, why, and the benchmark behind the decision.

## What they are

- **Every Compat (Wood Good)** (CurseForge `every-compat`, project 628539) and **Every Compat
  (Stone Zone)** (`stone-zone`, project 1154622), by MehVahdJukaar and Xelbayria. Both need Moonlight
  Lib (`selene`), which TBA already had.
- They don't ship a fixed list of blocks. At startup, while the game registers blocks, they look at the
  installed mods and **generate** the missing combinations: a Create window or a Macaw's door for every
  modded wood, a Macaw's bridge or Chipped variant for every modded stone, and so on. Textures and
  models are generated from the source blocks.
- Recommended by a member in #join-creative (2026-11-19); the owner asked for a test before adding.

## What TBA ships: the same mods, plus two skip lists

TBA uses the **unmodified** jars, referenced from the stores like every other mod (`mods/every-compat.pw.toml`,
`mods/stone-zone.pw.toml`, Modrinth copies in `scripts/mr-sources/`). The trimming is done with the mods'
own config files, which ship in the pack's `config/` folder like the pack's other configs:

| File | Setting | Value | Effect |
|---|---|---|---|
| `config/everycomp-hazardous.toml` | `[module] blacklist` | `["chipped"]` | No Chipped module. This list applies to both mods, so it drops the Chipped variants of modded woods and leaves (about 1,190) and stones (about 1,430) |
| `config/stonezone-hazardous.toml` | `[stonetype] blacklist` | `["excessive_building:.*", "meadow:.*", "arts_and_crafts:.*", "dustydecorations:.*"]` | Stone Zone makes nothing from these mods' stones. Every block whose model failed to load came from these stone types |

Everything else in the two files is the mods' generated default. Result in 2.0.12: **1,352 generated
blocks** instead of about 5,000 (the benchmarked slim setup had 1,604; the arts_and_crafts and
dustydecorations entries were added afterwards to remove the broken models).

What players get (server log, TBA 2.0.12):

| Module | Blocks |
|---|---|
| Macaw's Furniture | 364 (wood) |
| Macaw's Doors / Windows / Trapdoors | 132 / 107 + 28 stone / 102 |
| Macaw's Roofs | 84 wood + 49 stone |
| Macaw's Fences and Walls | 36 wood + 83 leaves |
| Macaw's Bridges / Lights and Lamps / Paths and Pavings | 36 / 18 / 6 |
| Woodworks | 42 wood + 83 leaves |
| Handcrafted | 81 wood + 14 stone |
| Storage Drawers | 42 |
| Beautify (Decorate) | 18 |
| Create | 12 |
| Friends&Foes, Mighty Mail, Farmer's Delight | 6, 6, 3 |

### Rules that come with it

- **Client and server must match.** The authors call these files "hazardous" because they change
  which blocks exist. A client with different lists can't join (registry mismatch). The pack ships the
  same files in the `.mrpack` (server and Prism) and the `.zip` (CurseForge app), so they match as
  long as nobody edits them by hand.
- **Changing a list is a pack release**, like adding or removing a mod: everyone updates together.
  Removing an entry after release puts blocks back. Adding one removes blocks, and any already placed
  in the world turn into air.
- **New mods can add blocks.** Any mod with woods or stones added later gets generated variants
  automatically. After such a change, check the client log for `Every Compat ... models could not be
  loaded (json missing or broken)`. If it appears, add that mod's namespace to the matching skip list.
  Also check that the block count hasn't jumped: the server log's registry counts, or the client's
  private memory in world.
- **Store review:** nothing special. The jars are store references, not bundled files, and config
  files are normal pack overrides. The `audit-artifacts.py` gate covers both.

## Benchmark (2026-11-20)

### Setup

- Laptop `theblockacademy`: 20 threads, 32 GB RAM (about 16.7 GB free at rest), Windows.
- The TBA 2.0.12 prep pack (StreamCraft 0.38.0) built three ways:
  - **base**: without the two mods;
  - **full**: both mods, default config;
  - **slim**: both mods with the skip lists above, minus the arts_and_crafts / dustydecorations
    entries that were added after this run.
- Each build ran a dedicated server (from its `.mrpack` via mrpack4server) and a Prism client on the
  same laptop. Server settings: ports 25566 / RCON 25576, seed `tba-bench-2026`, view and simulation
  distance 10, creative (`files/every-compat-bench/bench-server.properties`).
- One round per build:
  1. Boot the server.
  2. Measure the idle server 45 s after boot.
  3. Run the testkit session (`tba run`: join, teleport 300 blocks out at y=200 into fresh chunks,
     stay 150 s, quit like a player).
  4. Measure in world 75 s after the join.
  5. Stop the server.

  Builds alternated round by round.
- Measurements:
  - ModernFix's "Dedicated server took X seconds to load";
  - a sampler (`files/every-compat-bench/sampler.py`) logging private memory and free RAM every 5 s;
  - heap after `jcmd GC.run` at each measure point;
  - "Can't keep up" lag spikes in the server log.

  The sampler killed all Java if free RAM stayed under 1.5 GB for 3 samples (to keep the laptop
  usable). Raw data: `files/every-compat-bench/run1-full/` and `run2-slim/`; orchestrator
  `files/every-compat-bench/bench.py`.

### Run 1: full vs base (4 rounds each)

| Round | Server boot (s) | Server idle heap after GC (MB) | Client private, peak (MB) | Lowest free RAM (MB) |
|---|---|---|---|---|
| base-1 | 42.4 | 2,112 | not captured | 3,350 |
| base-2 | 43.6 | 1,769 | 12,446 | 2,713 |
| base-3 | 42.6 | 1,783 | not captured | 2,001 |
| base-4 | 44.4 | 1,734 | not captured | 2,468 |
| full-1 | 47.1 | 1,769 | not captured | 1,581 |
| full-2 | 46.7 | 1,771 | 13,730 | 1,304 (killed) |
| full-3 | 47.9 | 1,772 | 13,839 | 1,273 (killed) |
| full-4 | 46.8 | 1,775 | 13,984 | 1,293 (killed) |

"Not captured": the first sampler picked the wrong process for the client (fixed before run 2).

- Server boot: 43.3 → 47.1 s on average (about +4 s).
- Idle server heap: unchanged.
- Client: about +1.3 to 1.5 GB private memory.
- Client startup to the title screen: about 143 → 145 s, inside the noise.
- Generated blocks: about 5,000.
  - Chipped stone: 1,430.
  - Chipped wood and leaves: about 1,190.
  - Create: 414.
  - Macaw's Furniture: 364.
  - Macaw's Roofs: 336.
  - The rest are smaller modules.
- Broken models: 156 in Stone Zone (Macaw's bridges, stairs and railings in Excessive Building and
  Meadow stones).

### Run 2: slim vs base (3 rounds each)

| Round | Server boot (s) | Server idle heap (MB) | Client heap after GC, in world (MB) | Client private, in world (MB) | Lowest free RAM (MB) | Lag spikes (ms) |
|---|---|---|---|---|---|---|
| base-1 | 44.0 | 1,716 | (killed) | 12,005 | 785 (killed) | 3,413, 4,772 |
| base-2 | 43.7 | 1,696 | 4,694 | 12,783 | 2,512 | 2,034 |
| base-3 | 45.2 | 1,724 | 4,738 | 12,687 | 2,484 | 2,100 |
| slim-1 | 46.1 | 1,705 | (client did not start) | n/a | 1,092 | n/a |
| slim-2 | 44.4 | 1,701 | 5,246 | 13,664 | 1,923 | 2,497 |
| slim-3 | 47.8 | 1,730 | 5,029 | 13,499 | 1,466 | 2,035 |

- slim-1 is invalid:
  - First attempt: the testkit's 10 s RCON timeout fired while the server caught up after the
    teleport (one 15.5 s spike). The server was not hung.
  - Rerun: Prism refused because the previous client was still closing.
  - slim-1's free-RAM and peak numbers mix in that leftover client.
- Server boot: about +2 s.
- Server idle heap and lag spikes: no difference.
- Client: about +0.4 GB heap after GC and about +0.85 GB private memory in world.
- Client startup: noisy (base 134–168 s, slim 134–151 s), no measurable difference.
- Generated blocks: 1,604.
- Broken models: 33, all Stone Zone Macaw's bridges, support piers, stairs and railings on Arts and
  Crafts (gypsum, soapstone) and Dusty Decorations (seastone) stones. Fixed for 2.0.12 by the two
  extra skip-list entries.

### Caveats

- The low-memory kill hit **base** once too (run 2 base-1). Running the server and client on one
  32 GB machine sits close to that limit, so "full ran out of memory, base didn't" (3 of 4 vs 0 of 4
  in run 1) overstates it. The real cost is the per-client memory numbers.
- Only 2 complete in-world rounds per build in run 2.
- Errors also present in base, not caused by these mods:
  - 93 leaf-model errors (tfc/afc) from a resource pack;
  - a REI Chipped-plugin error.

### Decision

Ship slim. It costs about +0.85 GB client RAM and about +2 s of server boot, with no server memory or
lag cost, for about 1,600 matching blocks (1,352 after the broken-model fix). Full would cost +1.3 to 1.5 GB per player for about 2,600
extra Chipped variants, plus broken models.

## Re-running the benchmark

`files/every-compat-bench/bench.py` is the orchestrator used here. It wraps
`LocalServer/scripts/testkit.py`'s `tba_run`:

- the server log is read over ssh and RCON goes through an ssh tunnel;
- server and client both run on the laptop, never on the business PC.

It needs:

- one Prism instance per build (`TBA-<v>-<build>`, via `testkit tba install` from a build of each
  variant);
- one server folder per build (`C:\Users\slash\bench-srv-<build>`) with a scheduled task
  `TKSRV<build>` that starts it;
- `sampler.py` running in the laptop's interactive session.

Commands: `py -3 bench.py warm <b1,b2>` once, then `py -3 bench.py cycle <n> <b1,b2>` per round.
