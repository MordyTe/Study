# Menus, inventories, launchers and settings

- Menus are dense: use `observe` with `skeleton` when the scene is long, then act on the region.
- Prefer labeled controls (`button`, `menu_item`, `tab`). Verify a selection changed state
  (`selected`, `checked`) in the next observation.
- Inventories are grids of twins: identify an item by its name or icon text, and by position when
  names repeat.
- Settings that change resolution or input can break the session; ask the user before changing them.
- Launchers and native dialogs expose an accessibility tree: nodes with `src=a11y` are exact and clicks
  on them are delegated to the semantic path.
