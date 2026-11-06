# Action-adventure and exploration

- Movement is a held key: `hold_key` with 150 to 400 ms, then observe where the player ended up.
  Calibrate once: hold for 200 ms, measure how far the player moved from the `node_moved` event, and
  plan the rest from that.
- Dialogs, cutscenes and prompts take priority. If `surfaces` lists a dialog, advance it (`enter`,
  `space`, or the shown key) before moving.
- The HUD and the minimap are information, not targets. Quest text is the objective; quote it.
- Enemies and projectiles move between observations. Act on their current position, and `wait` for
  stability before precise clicks.
- If you are stuck in a corner or loop for three turns, change strategy: look for a door, read the
  map, or ask the user.
