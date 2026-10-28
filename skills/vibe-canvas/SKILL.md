---
name: vibe-canvas
description: Create, edit, and visually review Vibe Canvas boards through the Vibe AI MCP canvas tools, then check the result in the open board tab and fix layout defects. Use for canvas diagrams, flowcharts, mind maps, notes, tables, layouts, and follow-up edits on a Vibe board. Also use whenever the user shares a Vibe board link or asks about their board, what they are looking at, or what they have selected.
---

# Vibe Canvas

## Updates

Once per conversation, before the first canvas tool call, run `python3 scripts/update.py`. It checks at most once a day and prints one line; ignore failures. If it reports an update, finish the current task with these instructions and tell the user in one short line that a newer version is installed and applies in a new conversation.

## Tools

Boards are read and written as HTML through the Vibe AI MCP: `get_canvas_schema`, `list_canvas_pages`, `get_canvas`, `write_canvas`, `create_canvas`. If they are missing, ask the user to connect Vibe to their assistant: in the assistant's settings, add a connector with the server address `https://mcp.vibe-beta.com/mcp` and sign in to Vibe. Boards live at `app.vibe-beta.com`.

Call `get_canvas_schema` once per conversation before writing any HTML, and follow it exactly. Write rejections quote the schema rule that failed.

## Talking to the user

The user is a Vibe Canvas user, not a programmer. Describe what you can do and what you did in plain, everyday words about the board, never HTML, tag names like `c:note`, ids, tools, scripts, timestamps, or other technical terms. This applies to every message, including setup, updates, errors, and anything that went wrong: say what it means for their board and what they can do. When asked what you can do, answer from this list:

- Sticky notes in 12 colors.
- Text as a heading (H1, H2, H3) or body text.
- Shapes with a label: Rectangle, Rounded rectangle, Circle, Triangle, Right triangle, Rhombus, Parallelogram, Trapezoid, Pentagram, Cylinder.
- Sections: named, colored areas that hold other items.
- Tables with colored cells; cells cannot be merged.
- Connectors that link two items, and free lines, with or without arrows, solid, dashed, or dotted.
- Vector drawings, and math formulas or plots.
- Bold, italic, underline, strikethrough, colored, or linked text inside notes, text, shapes, and table cells.
- Move, resize, rotate, recolor, group, edit, or delete any of the above.

Images cannot be added, changed, or deleted yet, and measurements cannot be added. They still show in snapshots, so answer questions about them from one. Support will come in the future; if the user needs it sooner, suggest contacting Vibe customer support.

When the user asks about undo or redo, explain it like this: if they had the board open on that page while you made a change, they can undo or redo it there like their own edits; otherwise it cannot be undone from the board.

## Edit

- Board URL `https://HOST/BOARD_ID/PAGE_ID`. Without a page ID, call `list_canvas_pages`. Keep board, page, and URL in context across follow-ups.
- Shared board: when the user shares a board link, whatever they ask about it, such as a summary, run `python3 scripts/review.py open URL` first without asking, then continue while the tab loads.
- `get_canvas` gives the base: the page HTML and its `end_timestamp`. Its `end_timestamp` argument is required: pass the current Unix time in whole seconds (`date +%s`), never a fraction or milliseconds. Each `write_canvas` sends the base plus the current change, with the base's `end_timestamp`. Elements of the base left out are deleted; keep unchanged ones and their `uid`s exactly. New elements and groups use unique negative ids.
- Reuse the HTML from your last `get_canvas` while it is still current.
- Omit an attribute only when the schema gives it a default value; write every other attribute.
- The backend diffs only against the base, so everything that happened after it stays: your earlier writes and the user's own edits. Elements added after the base are not in it; leave them out and they stay on the board.
- Don't read again by default, including on follow-ups; assume the user has not changed the board. Read again only when the change must edit, delete, or connect to an element added after the base (it needs its real id), when the user says they changed the board or mentions something not in the base, or when a snapshot shows the board differs from what you expect.
- Show progress early. Split a large task into increments the user can watch appear, such as one section or one branch per write, and write the first one before reviewing anything. Keep each write a coherent piece, and prefer pieces that don't need to connect to elements added by an earlier piece.
- A drawing too complex for one `<c:svg>` can be split into several, each a recognizable part placed at its own board position, and drawn piece by piece. Group the pieces with a shared `gid` when they form one picture.
- Keep the user informed in a short line as each piece lands, instead of going silent until the end. Finish with one short line too; don't recap the changes, since the user sees them on the board.
- New board: when the user asks for something on a canvas without having shared a board link in this conversation, create a new board; don't ask which board or reuse one. Call `create_canvas` with an empty `<html></html>` page and open the returned URL with `python3 scripts/review.py open URL` without asking. Prepare the content while the tab loads, then add it in increments, so the user can undo and redo every change from the open board.
- Existing ink reads as an empty `<c:svg>` placeholder with only its position. To see it, pan there and take a snapshot.
- When deleting a node, remove or reconnect its connectors. When removing a section but keeping its contents, keep the children with their ids and absolute coordinates.
- Mark unknown owners or dates as TBD instead of inventing facts.
- Images and measurements are missing from the HTML, and writes never touch them. They still take space on the board; when placing a large layout into an area that may hold them, check a snapshot first.
- Place new content in the user's current view (`review.py viewport`). If the view is full, pan or zoom out to the nearest free space, as a person would. When several spots fit, choose the one that relates best to the existing content, such as next to the related element or continuing the existing flow.

Read [references/layout.md](references/layout.md) when composing or repairing a layout.

## Review

`scripts/review.py` (Python 3, no dependencies) lets you see the board in the user's open tab. Decide for yourself when a look is worth it.

```sh
python3 scripts/review.py serve &
python3 scripts/review.py health
python3 scripts/review.py open BOARD_URL
python3 scripts/review.py wait BOARD_URL [SECONDS]
python3 scripts/review.py tabs BOARD_URL
python3 scripts/review.py snapshot BOARD_URL /tmp/canvas.png [--region LEFT TOP RIGHT BOTTOM] [--max-side N | --full]
python3 scripts/review.py viewport BOARD_URL
python3 scripts/review.py pan BOARD_URL LEFT TOP RIGHT BOTTOM
python3 scripts/review.py zoom BOARD_URL [PERCENT]
```

- It needs localhost port 7193. In a sandboxed agent such as Codex, run it outside the sandbox (request escalated permissions).
- Start `serve` once and reuse it. Only the board's tab in front reliably answers.
- `tabs` counts tabs answering for a board. With 0 after you already opened it, tell the user in one short line, with the board link, that opening the board is highly recommended so you can see your changes and they can undo them; keep working and check again about once a minute. With more than 1, suggest closing the extras.
- `open` does nothing when a tab already answers for the board.
- `open` and `wait` wait up to 15 seconds while a fresh tab passes through login.
- `snapshot` shrinks the image to at most 1280 px on its long side by default, enough to judge a layout. Use `--max-side 640` for a rough look and `--full` only when you need exact pixels; the reported width and height match the saved image.
- `--region` crops the snapshot to a board area inside the current view, so a small change costs a small, sharp image without moving the user's view. The reply's `bounds` give the cropped area in board coordinates. Pan only when the area is outside the view or too small to read.
- `pan` pads the region, matches the window ratio, and never zooms past 100%.
- When you finish, leave the view where the user can best check the change, as a person showing their work would. If the change is already readable in their view, don't pan. Otherwise pan to it at a comfortable reading zoom with some surrounding context, not filling the window; for a large change, show the part that matters most rather than shrinking it all to fit.
- Only when the task needs the whole board understood, such as a summary, don't rely on the HTML alone: zoom, pan, and take snapshots until you have seen every part, then pan back to the user's view. Snapshots are slow and costly, so take as few as cover the board: start from one zoomed-out look, then look closer only at areas the HTML leaves unclear.
- When the user refers to the board as they see it ("this", "here", what they selected or are looking at), take a snapshot before answering instead of asking them.
- In a snapshot, a blue frame with handles, usually with a floating toolbar above it, marks what the user has selected. Page HTML has no selection.
- If a snapshot fails, ask the user to bring the board's tab to the front, then try again.
- A snapshot can predate your last write reaching the tab.
