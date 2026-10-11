# Touch controls

Half the engineering in this project is input. Getting a 1997 strategy game to boot on
an iPhone is an afternoon; making it *playable* with thumbs is the actual work.

Layouts are data, not code. They live in `layouts/`, they're versioned here, and
contributing one needs taste rather than a compiler.

## Why this is hard

- A fingertip covers roughly 40×40 points. A 1998 UI was drawn for a 1-point cursor.
- Your hands sit **on top of** the screen, so the bottom third is partly occluded.
- There's no tactile edge. You can't find a button without looking at it, which means
  you can't look at the game.
- Many of these games assume a keyboard with 40 bound keys.
- No physical feedback on press — hence haptics on every virtual button.

The layouts here encode specific answers to those problems. Reading a few is the
fastest way to understand the schema.

## The eleven built-in layouts

| Layout | For | Core idea |
|---|---|---|
| `fps-twin-stick` | Doom, Quake, Duke, Blood, Dark Forces | left stick moves, right half aims as a trackpad |
| `fps-single-stick` | Wolfenstein 3D | no vertical aim exists, so don't fake a second stick |
| `pointer-trackpad` | RCT2, Transport Tycoon, Theme Hospital, Caesar III | relative cursor, so your finger never covers the target |
| `pointer-direct` | ScummVM, Heroes of M&M, X-COM | tap where you mean; targets are already finger-sized |
| `isometric-touch` | Diablo | the original scheme was a pointer poking at a world — stay out of the way |
| `rpg-virtual-cursor` | Morrowind | modal: twin-stick in the world, cursor mode in menus |
| `tank-controls` | Tomb Raider | rotate-then-move, as designed |
| `platformer-2d` | Cave Story, Sonic Mania | oversized d-pad, two big face buttons |
| `gamepad` | Tier 2 emulated consoles | conventional pad, face buttons arranged per platform |
| `sixdof` | Descent | sticks + gyro for roll. Experimental. Not solved. |
| `keyboard-overlay` | generic DOS | honest compromise; a hand-made layout always beats it |

## Schema

```toml
schema = 1
id = "fps-twin-stick"
name = "Twin-stick FPS"
description = """What this is for and why it's shaped this way."""
safe_area = true                  # respect the home indicator and notch
autohide_on_controller = true     # vanish when an MFi pad connects
modal = false                     # true if the layout has modes (see below)

[[control]]
kind = "stick"
id = "move"
anchor = "bottom-left"            # corner or edge to measure from
offset = [24, 28]                 # points from that anchor
size = 150
opacity = 0.30
deadzone = 0.14
recenter = true                   # stick re-centres under the finger on touch
bind = { up = "forward", down = "back", left = "strafe_left", right = "strafe_right" }
```

### Control kinds

| Kind | Notes |
|---|---|
| `stick` | analog or 8-way. `recenter` matters more than people expect. |
| `dpad` | discrete. `diagonals = false` for tank controls. |
| `button` | `style = "toggle"` for modifiers you'd otherwise hold through a ledge-walk. |
| `button-cluster` | face buttons; `arrangement = "platform"` resolves from the recipe. |
| `pointer` | `mode = "absolute"` (direct) or `"relative"` (trackpad). |
| `slider` | weapon cycling, throttle. `style = "segmented"` for discrete steps. |
| `keystrip` | scrollable key rows, for the DOS fallback. |
| `gesture` | `tap`, `hold`, `long-press`, `two-finger-tap`, `two-finger-drag`, `pinch`, `edge-swipe-left/right` |
| `gyro` | device rotation as an axis. Currently only used for roll in `sixdof`. |

### Anchors

`top-left` · `top-center` · `top-right` · `left-center` · `right-center` ·
`bottom-left` · `bottom-center` · `bottom-right`

Always anchor to a corner or edge, never to absolute coordinates — the layout has to
survive every iPhone size from SE to Pro Max, and both orientations.

### Modal layouts

Some games are really two games. Morrowind is a first-person RPG and a mouse-driven
inventory screen, and a single layout serves both badly.

Set `modal = true`, then tag controls with `active_in = "world"` or `"cursor"`, and
bind something to `mode:toggle` or `mode:cursor`. Controls without `active_in` are
always visible.

## Designing a good one

**Thumbs reach corners, not centres.** Everything frequent goes in the bottom corners.
The middle of the screen is for looking at.

**Big and translucent beats small and opaque.** 60–90 points for anything used
constantly. Opacity around 0.3 — present enough to find, faint enough to see past.

**Don't replicate the original controller.** Replicate the *intent*. Wolfenstein's
layout drops vertical aim because the game has none; copying a modern shooter's pad
would add a control that does nothing.

**Guard against overlap.** Adjacent buttons that can both register from one fat press
ruin platformers. `button_overlap_guard = true` in `[tuning]`.

**Haptics on everything pressable.** It's the only feedback available, and its absence
is why so many touch controls feel dead.

**Test one-handed.** People play phones on trains.

## The in-app editor

The shell will ship a layout editor: drag, resize, set opacity and deadzones, try it
against the running game, then export TOML. The intended loop is that you tune a layout
while actually playing, then open a PR with the result so nobody else has to.

That editor is not written yet. Hand-authored TOML works fine in the meantime —
every layout in this repo was written that way.

## Controllers

Full `GameController` support: Xbox, DualSense, Backbone, 8BitDo, and anything else
iOS recognizes. Touch controls auto-hide on connect and reappear on disconnect.

A controller doesn't make layouts irrelevant — it makes them a *fallback*, and the
`bind` names are shared, so one mapping serves both.
