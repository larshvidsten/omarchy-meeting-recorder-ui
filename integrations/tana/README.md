# Personal Tana action

The `lib/`, `config/` and skill files are copied unchanged from Lars' recorder at commit `1a8d35d`. They preserve its context → draft → direct publication → receipt workflow. The upstream UI integration only prepares equivalent input files. No old recorder service, UI or executable is needed.

This personal integration is a separate commit from optional MAI support and should not be included in the generic upstream PR. It requires the same configured Codex/Tana MCP connection as the previous recorder. Run `meeting-to-tana.py MEETING --prepare-only` to validate the bridge without invoking Codex or writing to Tana.

A user selecting the installed **Summarize to Tana** action invokes publication. The action uses the current edited transcript, local speaker labels and meeting start time. It preserves existing receipts to prevent duplicate notes; editing a transcript after publication does not silently republish it. Draft/context/receipt files are kept under `.tana/` in the meeting folder. Imported recordings should have their real original start time supplied in the manifest for calendar matching.
