# Vibe Canvas skill

Lets an AI assistant create and edit your Vibe Canvas boards, then look at the result and fix the layout.

## Install or update

Send this file's link to your assistant (Claude Code, Codex, or ChatGPT) and say "install this skill", or "update this skill" to get the latest version. In Claude Code and Codex the skill also updates itself, checking at most once a day. The rest of this file is written for the assistant.

Maintainers: bump `VERSION` with every change; installed copies update when it differs from `main`.

## For the assistant

Install the whole `vibe-canvas` folder (this README's folder: `SKILL.md`, `references/`, `scripts/`), not only `SKILL.md`. Do the work yourself; the user may not be a programmer, and you may be running on a remote machine.

### 1. Get the folder

```sh
tmp=$(mktemp -d)
git clone --depth 1 --filter=blob:none --sparse https://github.com/vibeus/canvas-skill.git "$tmp/canvas-skill"
git -C "$tmp/canvas-skill" sparse-checkout set skills/vibe-canvas
```

The folder is now at `$tmp/canvas-skill/skills/vibe-canvas`.

### 2. Put it where your app looks for skills

| App | Destination |
| --- | --- |
| Claude Code | `~/.claude/skills/vibe-canvas` |
| Codex | `~/.agents/skills/vibe-canvas` |
| ChatGPT | Zip the folder and give it to the user to upload under Skills, since ChatGPT installs skills from its own UI. |

```sh
mkdir -p DESTINATION_PARENT
rm -rf DESTINATION_PARENT/vibe-canvas
cp -R "$tmp/canvas-skill/skills/vibe-canvas" DESTINATION_PARENT/
```

This replaces any older copy, so the same steps install and update. In ChatGPT, delete the old skill before uploading the new zip.

### 3. Connect the Vibe AI MCP server

Skip this if it is already connected. Otherwise add the server `https://mcp.vibe-beta.com/mcp`. The user signs in to Vibe the first time it is used.

### 4. Finish

Tell the user to start a new conversation so the skill loads. Visual review (`scripts/review.py`) needs Python 3 and must run on the same computer as the browser showing the board. On a remote machine or in ChatGPT, the skill can still create and edit boards but cannot look at them.
