# TBA Recovery Plan — Backups, Then Pack Refresh

Hand-off document. Pick up on the Windows desktop PC. Steps are dependency-ordered: each one
gates the next. Steps marked **[PROD — owner approval]** touch the live Bloom.host server and
need an explicit go from the owner at the moment they run.

## Findings (investigation, 2026-11-03, read-only)

**Backups — there is no working backup of the live world.**

- Advanced Backups (AB, `AdvancedBackups-fabric-1.21-3.7.1.jar`) last completed a backup at
  `2026-05-23 18:07` (`/backups/world/differential/backup_2026-05-23_18-07-48-full.zip`, 22.7 GB).
  Right after writing it, the backup thread died:
  ```
  [AB Active Backup Thread/ERROR]: Uncaught exception in thread "AB Active Backup Thread"
  java.lang.NullPointerException: Cannot invoke "java.io.File.getName()" because "file" is null
    at ...advancedbackups.core.backups.BackupWrapper.getDependent(BackupWrapper.java:351)
    at ...advancedbackups.core.backups.BackupWrapper.checkSize(BackupWrapper.java:502)
    at ...advancedbackups.core.backups.BackupWrapper.finishBackup(BackupWrapper.java:344)
    at ...advancedbackups.core.backups.ThreadedBackup.run(ThreadedBackup.java:116)
  ```
  (log: `/logs/2026-05-23-7.log.gz`).
- Likely trigger: `config.advancedbackups.purge.size=5.0` (GB) in `/config/AdvancedBackups.properties`
  is smaller than a single full backup (22.7 GB), so the size-purge path runs on every finish and
  hits the null dependent. Unconfirmed until reproduced.
- The server has not restarted since that boot (uptime ~3,946 h at investigation), so AB stayed
  dead despite `enabled=true` and a 12 h uptime schedule. A restart alone revives it only until
  the next size check.
- Bloom panel backups: manual only, **no schedules**, **5/5 slots used**. Existing:
  2026-05-04, 05-07, 05-22, 05-23, 06-12 (55–78 GB each). A new panel backup needs a slot freed.
- Offsite: `theblockacademy/scripts/backup-sync.py` (GitHub Actions `sync-backups.yml`, every 6 h)
  lists only top-level `.zip` files in `/backups`, `/world/backups`, `./backups`. AB writes to
  `/backups/world/differential/`, so the job "succeeds" and uploads nothing —
  `tba-storage/server-backups/` in DO Spaces is empty.
- Newest restorable world: panel backup 2026-06-12. Everything built since is unprotected.

**Pack / server.**

- Live server and repo both on pack **1.0.7** (MC 1.21.1, Fabric 0.18.3, 192 mods). Repo clean.
- StreamCraft in the pack is **0.8.25**; current stable is 0.21.2+.
- Server log spams `Validation failed (offline?): java.lang.UnsupportedOperationException: JsonNull`
  every 5 min, plus occasional `Handshake validation failed` on player join, since the 1.0.7 boot.
  Suspected: old StreamCraft server-side validation vs. the current theblockacademy backend.
  Unconfirmed.
- Live `/modpack-info.json` URL still uses `github.com/mindfulent/TBA/...` (redirects fine;
  the next `update-pack` should write the `slashdaemon` URL). The repo's local
  `modpack-info.json` (0.9.95) is the LocalServer copy, stale but harmless.
- Disk: 55.7 GB used of 180 GB. `.mrpack4server/modpack/` is empty (no cache bloat).

## Prerequisites on the desktop PC

1. `git pull` in `Projects/TBA` and `Projects/theblockacademy`.
2. `python devenv/bin/devenv pull TBA` → writes `TBA/.env` (SFTP + Pterodactyl creds).
3. `pip install paramiko rich` if missing.
4. Sanity check (read-only): `python server-config.py status` and `python server-config.py backup list`.
5. Confirm local free disk for a world copy: the world is roughly 25–55 GB depending on whether
   DistantHorizons SQLite and BlueMap tiles are included.

## Phase 1 — Secure a current copy of the world

Nothing else proceeds until a restorable copy newer than 2026-06-12 exists off the server.

1. **Local SFTP pull (no server change).** Download `/world` to the desktop. Preferred route:
   LocalServer's `python server-config.py download-world` (excludes DistantHorizons by default;
   see `docs/BACKUP-STRATEGY.md`). Pulling a live world can catch region files mid-write; accept
   that for this first copy, or follow it with step 2.
2. **[PROD — owner approval] Consistent copy.** Either:
   - send `save-off` + `save-all flush`, pull `/world` again, then `save-on`; or
   - delete the oldest panel backup (2026-05-04) and create a new panel backup from the Bloom panel.
3. Verify the copy: open it in LocalServer (MC 1.21.1 Fabric, pack 1.0.7) and check spawn plus
   a known recent build loads.
4. Store the copy on the Synology NAS (`192.168.0.176`) as well as the desktop.

## Phase 2 — Make Advanced Backups work again

1. Check CurseForge for an AB release newer than 3.7.1 for Fabric 1.21.1 and read its changelog
   for a fix to the `checkSize` / `getDependent` NPE.
2. Reproduce on LocalServer with the production `AdvancedBackups.properties` and a world above
   5 GB; confirm the NPE, then confirm the fix (new jar and/or config) completes a backup and a
   purge cleanly. Candidate config change:
   - `purge.size` → `0` (disabled) or well above one full backup (e.g. `80.0`), relying on
     `purge.days` / `purge.count` for retention.
3. Decide retention against Bloom's 180 GB disk: one full is ~23 GB; differentials grow
   toward it. Keep at least the newest full plus its chain.
4. Ship the config via the pack (`config/AdvancedBackups.properties` under packwiz, if not
   protected by `non_overwritable_paths`) or upload directly — decide which and record it.
5. **[PROD — owner approval]** Apply the AB change, restart, then trigger `backup start`
   (`python server-config.py` → `b`) and watch the console through `finishBackup` with no
   exception. Confirm a new zip in `/backups/world/differential/` and an updated `manifest.json`.
6. Confirm the next scheduled (uptime 12 h) backup also lands without manual help.

## Phase 3 — Make the offsite copy real

1. In `theblockacademy/scripts/backup-sync.py`, list `/backups/world/differential/` (and
   `snapshots/`) instead of top-level `.zip` only.
2. Make "zero backups found" and "newest backup older than N hours" a **failure**, not a success,
   so the Actions run goes red and the existing Discord failure notice fires.
3. Check the job can move 20+ GB files: Pterodactyl download URL streaming, Actions runner disk
   and timeout. If not, upload only differentials after the first full, or move the sync off
   Actions.
4. Test with `workflow_dispatch`, confirm objects in `tba-storage/server-backups/`, check
   `BACKUP_RETENTION_DAYS` pruning.
5. PR to theblockacademy; merge after review (deploying the workflow is a prod change).

## Phase 4 — Panel backup hygiene

1. **[PROD — owner approval]** Free panel slots: keep the newest good panel backup plus one
   older anchor; delete the rest once Phase 2 and 3 are proven.
2. Add a Bloom panel schedule (e.g. weekly panel backup) if slot rotation allows it; otherwise
   document panel backups as manual, pre-upgrade only.
3. Update `docs/BACKUP-STRATEGY.md` to match reality (layers, paths, retention, how to verify),
   and add a "how to tell backups are healthy" check.

## Phase 5 — Pack refresh (1.0.8)

Gated on Phase 1 at minimum; preferably after Phase 2.

1. StreamCraft 0.8.25 → current stable (CurseForge: `./packwiz.exe cf install` / update the
   existing `streamcraft-live.pw.toml`). Confirm the `JsonNull` validation spam stops on LocalServer.
2. `./packwiz.exe update --all`; review every bump. Watch Distant Horizons (3.x was reverted
   in v1.0.3 — keep 2.4.5-b unless 3.x is proven), C2ME, Fabric loader/API.
3. Include the AB version/config from Phase 2.
4. Follow the release checklist in `CLAUDE.md`: version in `pack.toml`, `CHANGELOG.md`,
   `README.md`, `docs/CREDITS.md`, release notes `docs/release-notes-v1.0.8.md`.
5. `python scripts/build-variants.py`; test on LocalServer with the Phase 1 world copy.
6. Release notes → owner sign-off before any publish.
7. GitHub release, then Modrinth / CurseForge publish scripts (each channel needs approval).
8. **[PROD — owner approval]** `python server-config.py update-pack 1.0.8 -p` (writes the
   `slashdaemon` URL), restart, `verify-mods`, confirm AB backup runs on the new pack.
9. Announce in `#server-releases` after owner approves the text.

## Open questions for the owner

- Panel backup slots: which existing panel backups can be deleted?
- Retention target for AB on the server vs. Spaces vs. NAS.
- Should the NAS hold a periodic world pull as a third copy, and from which machine?
- Scope of 1.0.8: StreamCraft + safe updates only, or a broader mod review?
