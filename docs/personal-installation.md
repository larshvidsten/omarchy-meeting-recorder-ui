# Personal MAI + Tana installation

This fork is based on upstream v1.4.0. Keep generic MAI support and the personal Tana integration in separate commits. Only generic MAI support is intended for an upstream PR.

After building and testing, run `python3 integrations/install-local.py PATH_TO_BINARY`. It installs a dated release under `~/.local/share/meeting-recorder-mai/releases/`, switches `current`, adds a user launcher and configures the Tana action. Existing configuration and links are saved under `backups/`. It does not delete old recordings or the old recorder. New recordings use upstream's `~/Documents/Meetings` folder; the older recordings remain in their existing location.

Enable the new widget with `omarchy-shell shell rescanPlugins`, then `omarchy plugin enable jankeesvw.meeting-recorder right`. Once working, disable the old widget with `omarchy plugin disable lars.meeting-recorder`. The upstream widget is visible while recording/transcribing; use the application launcher to open an idle recorder.

## Updates

Do not install an upstream binary over this fork. Fetch new releases from the `upstream` Git remote, create an update branch/worktree, and rebase/cherry-pick the generic MAI commit and personal integration onto the new release. Resolve any conflicts, run tests, and build before running the local installer again. Its dated release folders allow rolling back the `current` link. The user launcher points at this local installation independently of `/usr/bin`.

If MAI support is accepted upstream, stop carrying the generic patch once the official release contains it. Keep the standalone Tana action and its config. The Python MAI adapter is embedded in the binary, so a build always contains its matching adapter.

## Rollback

Re-enable `lars.meeting-recorder` and disable `jankeesvw.meeting-recorder` to return to the old bar workflow. For a previous personal release, point `~/.local/share/meeting-recorder-mai/current` at that release and restart the app. Restore config/desktop links from the matching backup if needed. Do not remove or overwrite recordings when reverting.

Tana's local bridge tests do not publish a note. `python3 integrations/meeting-to-tana.py MEETING --prepare-only` checks conversion without contacting Tana. Selecting **Summarize to Tana** in the app runs the existing publication workflow with its configured Codex/Tana connection.
