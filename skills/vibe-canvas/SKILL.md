---
name: vibe-canvas
description: Create, edit, and visually review Vibe Canvas boards through the Vibe AI MCP canvas tools, then check the result in the open board tab and fix layout defects. Use for canvas diagrams, flowcharts, mind maps, notes, tables, layouts, and follow-up edits on a Vibe board. Also use whenever the user shares a Vibe board link or asks about their board, what they are looking at, or what they have selected.
---

# Vibe Canvas

This skill covers how the tools work and the pitfalls that break boards. How the board should look is up to you and the user.

## Updates

Once per conversation, before the first canvas tool call, run `python3 scripts/update.py`. It checks at most once a day and prints one line; ignore failures. If it reports an update, finish the current task with these instructions and tell the user in one short line that a newer version is installed and applies in a new conversation.

## Tools

Boards are read and written as HTML through the Vibe AI MCP: `get_canvas_schema`, `list_canvas_pages`, `get_canvas`, `write_canvas`, `create_canvas`. If they are missing, ask the user to connect Vibe to their assistant: in the assistant's settings, add a connector with the server address `https://mcp.vibe-beta.com/mcp` and sign in to Vibe. Boards live at `app.vibe-beta.com`.

Call `get_canvas_schema` once per conversation before writing any HTML, and follow it exactly. Write rejections quote the schema rule that failed.

## Talking to the user

The user is a Vibe Canvas user, not a programmer. Speak in plain words about their board, never HTML, tag names, ids, tools, scripts, or timestamps, including in errors and setup. When asked what you can do: sticky notes, text, labeled shapes, sections, tables, connectors and lines, vector drawings, math formulas and plots, rich text, and moving, resizing, rotating, recoloring, grouping, editing, or deleting any of these.

Images and measurements cannot be added, changed, or deleted yet; they still show in snapshots, so answer questions about them from one. If the user needs that sooner, suggest contacting Vibe customer support.

Undo: changes you make while the user has that page open can be undone there like their own edits; otherwise they cannot be undone from the board.

## Reading and writing

- Board URL is `https://HOST/BOARD_ID/PAGE_ID`. Without a page ID, call `list_canvas_pages`. Keep board, page, and URL in context across follow-ups.
- `get_canvas` returns the page HTML and its `end_timestamp`. Its `end_timestamp` argument is required: the current Unix time in whole seconds (`date +%s`).
- Each `write_canvas` sends that base HTML plus your change, with the base's `end_timestamp`. The backend diffs against the base: base elements you leave out are **deleted**; keep unchanged ones and their `uid`s exactly. New elements and groups use unique negative ids. Elements added after the base (yours or the user's) are not in it and are left alone.
- Reuse your last read; read again only when you must touch an element added after it (you need its real id), or the user says the board changed.
- Omit an attribute only when the schema gives it a default.
- Ink reads as an empty `<c:svg>` placeholder; images and measurements are missing from the HTML entirely. All of them still take space on the board.
- New board: when the user wants something on a canvas without having shared a board, call `create_canvas` with `<html></html>` and run `python3 scripts/review.py open URL`, so they watch it appear and can undo. When the user shares a board link, run `open` too; it does nothing if the tab is already open.
- Write large work in pieces the user can watch land, with a short line per piece. Don't recap at the end; they see the board.
- Mark unknown owners or dates as TBD instead of inventing them.

## Seeing the board

`scripts/review.py` (Python 3, no dependencies) talks over a local websocket (port 7193) to the board tab open in the user's browser. It must run on the same machine as that browser; in a sandbox such as Codex, run it outside the sandbox.

```sh
python3 scripts/review.py serve &                  # start once, reuse
python3 scripts/review.py open BOARD_URL           # open the tab (no-op if open)
python3 scripts/review.py tabs BOARD_URL           # how many tabs answer
python3 scripts/review.py viewport BOARD_URL       # what the user sees, in board coordinates
python3 scripts/review.py snapshot BOARD_URL OUT.png [--region L T R B] [--max-side N | --full]
python3 scripts/review.py pan BOARD_URL L T R B    # move the user's view to a region
python3 scripts/review.py zoom BOARD_URL [PERCENT]
```

- `viewport` is cheap: use it freely to see where the user is looking and place new work there.
- Snapshots are images and cost far more than reading HTML, even shrunk (`--max-side 640`) or cropped (`--region`, which needs no pan). Take one when the HTML can't answer: the user says "this" or "what I selected" (a blue frame with handles marks the selection), ink, images, or understanding a whole board for a summary.
- `pan` and `zoom` move the user's own view. Each move is slow and every jump disturbs them; move only when what you need is off screen, and at the end leave them looking at your change.
- Only the board's tab in front reliably answers. If `tabs` is 0, tell the user once that opening the board is recommended so you can see it and they can undo; keep working. If more than 1, suggest closing extras. If a snapshot fails, ask them to bring the tab to the front.
- A snapshot can predate your last write reaching the tab; compare against what you wrote.

### Reviewing your work

Most changes need no visual check: editing text, recoloring, or adding a few items where there is clear space can be trusted from the HTML, so don't snapshot or ask.

Hard layouts are different: a complex flowchart, a large diagram, or connectors routed around other items usually come out with overlaps, clipped labels, or tangled lines when written blind, and do need a check. Still don't check on your own: ask the user whether you should look over the result and fix the layout, and recommend it. Remember their answer as a lasting preference (in your memory, if you have one) and follow it next time without asking again.

## Layout

There is no house style. Fit the layout to the user: follow what your memory says they like, match the style already on their board, and remember corrections they make. Without any of that, choose what suits the content.

A **section** is a named, colored frame that holds other items. Each one is another box the reader has to take in, so many sections make a board heavy and repetitive; whitespace and a heading mark a region more lightly. Use few.

Pitfalls:

- Sections cannot nest. Their children keep absolute coordinates. When moving a section, move every child by the same delta; when removing or splitting one, keep the children's ids and positions. Long section titles can overflow the section's width.
- A shared `gid` groups items but does not make their coordinates relative.
- Text width is hard to estimate; treat a text element as one line unless split into paragraphs. Shapes need padding around labels; square notes hold little text.
- Deleting a node: remove or reconnect its connectors. Moving nodes: recompute connector sides.
- Tables: every row needs the same number of cells; cells cannot merge.
- On dark fills, give every paragraph an explicit light text color, including lines you append later.
- Snapshot scale: for bounds `(left, top, right, bottom)` and image size `(width, height)`, board units per pixel are `(right-left)/width` and `(bottom-top)/height`. Side panels can cover part of the view.
