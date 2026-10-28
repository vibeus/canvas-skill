# Canvas layout

Use the schema returned by `get_canvas_schema` for actual element attributes. The initial creation vocabulary is text, shape, note, section, table, connector, and groups; preserve any other elements returned by a read exactly when they are unrelated to the request.

Text width is difficult to estimate. Treat `c:text` as single-line unless paragraphs explicitly split it. Check the snapshot and adjust. Shapes need padding around their labels. A square note has limited space: shorten long text, split it into paragraphs, or use a larger text card when appropriate.

A section is a colored, titled frame that holds a named region. Each one is another box the reader has to take in, so many sections make a board heavy and repetitive; whitespace and a heading also mark a region, more lightly. Keep section backgrounds tightly fitted to their children. Long section names can extend beyond the section's width. Children keep absolute coordinates. Do not nest sections.

## Mind maps

Keep main branch labels short and put the substance in nearby subtopics, examples, and explanations; keep the depth the user asked for. Let branches grow unevenly with their content. When one tree gets too large to read at a glance, use an overview map with each main topic expanded in its own map nearby. Place related ideas close, separate groups with whitespace, and use color and connectors to show the relationships.

## Other layouts and review

Align the anchor centers of neighboring flowchart nodes before routing. A taller decision diamond often needs a different top coordinate to keep its center on the main path. Use one waypoint per necessary bend for branches, return loops, or obstacle avoidance. Merge collinear waypoints and remove short jogs by adjusting the connected nodes where practical. Derive connector sides again after moving nodes. Delete or reconnect edges when deleting a node. Reserve room for connector labels. For a lower branch beside an occupied row, leave the source from its bottom and route through the gap between rows. Verify the full rendered route, including its first segment.

Use `c:table` for tabular data instead of a grid of shapes. Every row needs the same number of cells; widen columns rather than letting cell text wrap into clipped rows.

Use a shared `gid` for movable groups and a section for a named visual region. Grouping does not convert child coordinates into relative coordinates. Preserve group membership and external connector IDs when moving related elements.

For a visible region `(left, top, right, bottom)` and snapshot dimensions `(width, height)`, world units per image pixel are `(right-left)/width` horizontally and `(bottom-top)/height` vertically. Browser zoom scale and device-pixel ratio are different quantities. Side panels may cover part of the canvas; use the snapshot to choose visible free space instead of assuming the full viewport is clear.

Review only the changed region at a readable zoom, checking clipping, contrast, edge attachment, overlap, and section titles. Capture a fresh snapshot after the engine settles. Fold observed defects into the next write, then verify once more. Do not repeatedly request unchanged screenshots or export the board merely to inspect its appearance.

A committed write can precede delivery to the open tab. Compare the snapshot's labels and positions with the edited HTML before accepting it. A frame showing the preceding case is stale evidence.

Use explicit text colors for every paragraph on a dark card, including newly appended owner or status lines. Keep short note titles and split descriptions into brief paragraphs. When moving a section, translate every child by the same delta and preserve the children's IDs. When splitting a section, retain its children's IDs and move them into the new containers before removing the old container.
