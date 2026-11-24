# 2D → 2.5D — faking real depth in a top-down game

An experiment in taking a flat 2D game and giving it genuine apparent depth,
without replacing the top-down view with a conventional 3D game camera.

The game is whack-a-mole, ported from a 2D pygame version. In 2D the moles
pop by changing sprite. The question here is whether the same game can read
as a physical scene — holes sunk *below* the surface, moles rising *out* of
them — while the viewpoint stays directly overhead.

Most of the interesting content below is the perception findings: which
depth cues survive a top-down view, which ones do nothing, and why.

Everything runs on a laptop with a mouse — there is nothing to set up
beyond the environment. A touchscreen works too if you have one lying
around, and the game cannot tell the difference.

## Environment

Uses a dedicated conda env (**not** the global interpreter):

```bash
./run.sh setup          # creates the env and installs the project
```

## Running

```bash
./run.sh game           # whack-a-mole, starting at its menu
./run.sh depth          # SPACE cycles the three projections
./run.sh sky            # "eye in the sky" view, fog + world scale
./run.sh touch          # input -> event snapshots -> drawn contacts
./run.sh test           # 441 tests

./run.sh capture        # headless: writes PNGs, fails if any frame is blank
./run.sh shots          # headless PNGs of the game and its menu
./run.sh --help         # everything else
```

The game opens on a menu: `1`/`2`/`3` pick beginner, medium or advanced,
`H` shows the controls and `G` the rules. The rows are tappable too.

In play: `[click]` swing the mallet, `[D]` difficulty, `[T]` theme, `[B]` bezel finish
(arcade / neon / ebony / tan), `[P]` parallax mode, `[arrows]` move the
viewpoint, `[F]` facing, `[M]` mirror, `[R]` restart, `[TAB]` menu.
`./run.sh game --theme night --difficulty advanced --skip-menu` also works.

## Why the structure looks like this

The fiddly, long-lived parts are the coordinate maths and the input
bookkeeping; the renderer is the part most likely to be thrown away. So the
code splits four ways:

- **`core/`** — pure Python, and it never imports the renderer: the unit and
  coordinate conventions, the measuring and scaling maths, and what the game
  gets told about input.
- **`render/`** — the off-axis frustum maths (pure, scale-free, no engine
  types), the single module that converts scene millimetres to engine world
  units, the project GLSL 120 shaders, the engine configuration that must be
  applied before Ursina loads, and the Ursina adapter itself.
- **`sensors/`** — a small input-source interface, a mock that turns the
  mouse into contacts, and an optional Linux touchscreen reader.
- **`apps/`** — the runnable demos and tools.

Because `core/` has no renderer imports, swapping engines means rewriting
`render/` and nothing else. It also means the game rules and the input
bookkeeping are testable with no window open, which is most of why the test
suite runs in under a second.

## Coordinate conventions

One system, defined once in `core/geometry.py`. **Millimetres, origin at the
centre of the visible scene, on the surface plane.**

| axis | direction |
|------|-----------|
| `+X` | right, looking down at the scene |
| `+Y` | away from the near edge, toward the far side |
| `+Z` | up, out of the surface, toward the viewer |

A tap on the surface is `z = 0`, a hovering pointer `z > 0`, content
rendered *into* the scene `z < 0`. Ursina is Y-up and left-handed; that
conversion happens in exactly one module.

## The projection

Making a flat image look deep is **not** achieved by moving a camera and
re-aiming it. That makes the scene swing when the viewpoint moves, which
reads as "the world is rotating", not "I am looking through a window".

The window effect needs an **off-axis (sheared) frustum**: the view
rectangle stays pinned in world space, the eye moves freely, the frustum
shears, and **the camera never rotates**. In Panda3D terms, with the eye at
`(ex, ey, ez)` relative to a `w × h` rectangle:

```
film_size    = (w, h)
focal_length = ez
film_offset  = (-ex, -ey)
```

Offset signs were established empirically against `Lens.project`, not
derived from Panda's matrix layout.

Three modes are offered, but there is only one formula: on-axis perspective
is the degenerate case with the eye pinned above the centre.

### "Eye in the sky"

The off-axis frustum *is* the eye-in-the-sky model — the surface is a window
and the world lies behind it. Altitude is not a projection setting; it comes
from three things `sky_demo` exposes:

1. **World scale** (`MM_PER_VIRTUAL_METRE`) — the main altitude dial.
2. **Content depth** below the surface.
3. **Aerial perspective** — `fog_amount` on `LIT_120`, plus vertical
   structures whose convergence the eye reads as height.

The constraint worth understanding: an honest window only reveals a *cone*
of what lies behind it, widening as `(h + d) / h`. Put a landscape far below
and you see a tiny patch, like peering through a skylight. A convincing sky
view is therefore a **scaled miniature world fairly close to the surface**,
not geometry pushed physically far away. `sky_demo` sizes its ground and
tower field to that cone so the world's edge never enters the frustum.

Keep the optics true to the real eye position and scale the *world*. Faking
the optics to widen the view is what breaks the illusion.

### The depth-demo solid

The main solid is a **square-based pyramid with its apex pinned at the
surface and its broad base recessed**, so the tip→base axis runs along Z and
the shape tapers away from the viewer. `T` flips the taper (tip toward you
vs a funnel receding away); `W`/`S` change the depth; `G` cycles the depth
gradient.

**Flat per-face shading alone is not enough.** Each facet gets one uniform
tone, so viewed from straight overhead the apex has nothing to distinguish
it from the base and the solid collapses into a flat square with diagonals.
The fix is a per-pixel gradient keyed to depth (`fog_amount` on `LIT_120`,
which interpolates world position across each face): the apex stays bright
because it is nearest, the base corners fade as they recede. `fog_depth` is
set per solid to that solid's own depth, so the ramp always spans the shape
instead of using a sliver of a fixed global range.

Normals are computed explicitly in `_face_normal` rather than via
`Mesh.generate_normals()`. Two things had to be right: faces need
**unshared vertices** (OpenGL stores one normal per vertex, so a shared
apex forces a single averaged normal and the facets blur into a dome), and
`generate_normals(smooth=False)` still did not yield per-face normals even
then — every face came back pointing up and the solid rendered as one flat
silhouette. Normals are oriented away from the solid's centroid, which is
reliable for these convex shapes and removes any dependence on winding.

A taper beats a constant-section prism here: a prism's walls are parallel to
the view axis, so looking straight down you see almost none of them, whereas
every face of a taper is angled across the view and so catches light
differently and foreshortens as the eye moves.

Worth knowing when reading the view: **from directly overhead, a tip aimed
at the viewer projects to a point at the centre, not to a point on the
outline.** The square silhouette is the *base*; the apex sits at its centre
with four faces radiating to the corners. A tip pointing at you cannot
appear as a triangular profile from a top-down camera — that would require
an oblique view.

(Square base because the everyday meaning of "pyramid" is the 4-sided Giza
form; a triangular base would be a tetrahedron, whose 3 radiating faces read
more ambiguously from directly overhead.)

## The game, and what the 2.5D conversion actually needed

Rules live in `game/whack_a_mole.py` and import no renderer, so the whole
game is unit-tested headlessly. Logic and timing constants are ported from
the 2D pygame version and re-tuned for the larger scene; the difficulty ramp
is new (the 2D version had none).

Everything below is a cue that had to be added or discovered. None of it
exists in the 2D original, and two of the obvious ideas turned out to be
worthless.

### Why the mole has to be invisible at rest

The non-obvious finding. Viewed from ~700 mm overhead, a 150 mm rise changes
a mole's apparent size by **under 10 percent** — far too little to notice.
So the pop cannot be sold by perspective; it has to be sold by *visibility*,
exactly as a real arcade cabinet does it. An earlier version parked the mole
at the bottom of an open funnel, and a risen mole was nearly
indistinguishable from a resting one. The mole's top now sits at the well
floor at rest, concealed by the floor and the funnel wall.

### Why the mole leans back out of the hole

The other half of the same problem. A surface of revolution viewed straight
down its **own axis** projects to a circle and carries almost no shape
information — no amount of shading fixes that, which is why upright moles
read as flat discs. Tilting the body (`lean_deg`, 44 degrees, easing in over
the top half of the rise) takes its axis off the view axis, so torso and
face project as an elongated asymmetric silhouette.

Three cues work together, and none of them is scale:

- **Lean**, for silhouette and visible body. The direction matters: the
  snout sits on the mole's local -Z side (the viewer's side), so tipping the
  top *toward* the viewer rotates the face down into the hole and presents
  the back of the head. It has to lean **backward**, against the far rim,
  which swings the face up into view. Positive `rotation_x` is that
  direction — established by rendering both signs rather than reasoning
  about Ursina's left-handed rotation convention.
- **Cast shadow**, offset from the hole along the light's horizontal run and
  tightening as the mole rises. The strongest height cue available from
  overhead, precisely because apparent size barely changes.
- **Non-symmetric features** (ears, snout) and **paws resting on the rim**,
  which give a contact relationship with the hole so the mole reads as *in*
  it rather than floating above it.

Ambient is high (0.72 in `day`) for a related reason: with a single
directional light, a tipped-back body and the inward-facing wall of a hole
both turn away from it entirely and fall back to ambient, so a low value
renders them near-black with no fill light to rescue them.

### Why taps are hit-tested on the z = 0 plane

Hit testing is done in scene millimetres against the hole footprint at
`z = 0`, never by raycasting the mole's 3D body. The `z = 0` plane projects
identically in every projection mode and independently of the viewpoint, so
a tap maps to scene coordinates exactly — a mole standing proud of the
surface does not. Protruding geometry appears displaced by
`height x lateral_eye_offset / eye_height` — about 45 mm at the field edge
for a mole standing 78 mm proud — so the hit radius is forgiving (hole
radius plus 30 mm) rather than strict.

This is the one place where 2.5D is strictly worse than 2D, and the fix is
to keep the interactive geometry nearly flat and do the input maths in 2D
anyway.

### The frame, the scoreboard and the font

The display is not all playfield. `core/layout.py` splits it into a thin
raised bezel at the edge, a flat score band inside that, and the playfield
in the middle; the rules are handed only the playfield, and a tap on the
frame counts as neither a hit nor a miss. The bezel is a chamfered ring
whose two slopes shade differently from its flat top, which is what makes a
border read as raised rather than painted, and a bright inlay stripe along
it plus a line at the playfield edge give it the cabinet look.

Text is a 5x7 bitmap font defined in `render/pixel_font.py` and baked into
one texture atlas, drawn as a quad per character. Ursina's vector font reads
as a desktop UI at any size, and no pixel font ships with the project or the
OS. The atlas is monospaced, so columns line up without padding tricks.

Two findings from building it, both silent failures:

- **A font texture is a coverage map in its alpha channel, not a colour
  image.** The project's unlit shader multiplied the sampled RGB, which is
  zero there, so every glyph drew black whatever colour was set --
  including the scoreboard, pale text on a near-black band. `TEXT_120`
  exists for that reason.
- **UI-space text does not appear in the headless capture at all.** World
  -space text does. The scoreboard, the banner and the menu are therefore
  table geometry rather than a screen overlay, which also means they sit at
  known millimetre positions and behave correctly under parallax.

The band carries four things, positioned in millimetres rather than as
fractions of its length, because they have to miss each other: the clock,
the score, the detail figures, and an EXIT button at the right-hand end.
The mallet's resting place is the left-hand end. The exit button's rectangle
lives in `core/layout.py` so that what is drawn and what a tap is tested
against cannot drift apart, and a test asserts it clears every readout by
more than its own width.

The mallet is the pointer only while the hand is over the playfield; off it
the system cursor comes back, so the exit button is aimed at with an
ordinary cursor. What counts as "over the playfield" is the mallet's **head**
-- the handle hangs over the panel whenever the player reaches for the near
row, and treating that as leaving the field would make the bottom row
unplayable, flipping between mallet and cursor as the player reached for it.

The mallet is also *drawn* where it will appear over the hand rather than at
the hand's own table position. It rides 150 mm above the glass, so drawing
it at the contact point put its head outward of the hole being clicked by up
to ~45 mm at the edge of the field. Same correction as the menu's, in the
other direction.

That correction has to use the eye the **lens** projects from, which is not
the viewer's. Only the head-tracked mode projects from the tracked head; the
fixed modes project from above the table centre however far the viewer
marker has walked around the perimeter. Correcting toward the head while the
lens projected from the centre was worse than no correction at all: the
mallet was drawn short of the hand, and near the home edge it appeared over
the panel, which is what made the exit button impossible to aim at.
`lens_eye` is now the single answer to "which eye", used by the rig to place
the camera and by the view for every apparent-position calculation.

As a backstop, the mallet also gives way when its head circle comes within
its own radius of the exit button, so the button is never covered even if
the pointer is still technically over the field.

EXIT itself asks rather than acts. A button inside the playfield's reach
that closed the window on one touch is a swing away from ending someone's
round, so EXIT (and `ESC`) opens the dialog in `render/confirm.py`, and what
it offers depends on where the player is: mid-round it pauses and offers
resume / end the round / leave; after a round it offers play again / menu /
leave; from the start menu it asks once before closing the window. The
round's clock stops while the question is on screen -- a prompt about
quitting must not cost seconds -- and the dialog is modal, so the keys that
cycle themes underneath it do nothing while it is up. `exit_prompt` and its
rows are plain data, tested without a window; `./run.sh capture` can render
the `confirm` scene, which is how "is it in front of the menu it covers"
gets answered.

The clock counts **down**. Counting up makes the player work out how long
they have left, and it turns red under ten seconds.

### The mallet

The pointer is a round mallet, not a cursor: the system cursor is hidden the
moment a round starts, and `render/mallet.py` draws a striking face about
the size of a hole with a handle running back toward the player. It is
driven by a position in **table millimetres** rather than by the mouse, so
a finger on a touchscreen goes down the same path -- whichever it is, the
mallet goes there and a tap swings it.

The swing is mostly a dip in Z. From directly overhead, rotation alone is
weak -- the mallet sweeps sideways and nothing says it came down -- while a
drop toward the glass and back is the one motion that reads as a strike. The
motion is a pure function of normalised swing time, so it is unit-tested.

Two sizing lessons, both visible in the captures:

- **The head is half a hole across, not a hole across.** Sized to the hole
  it covered the entire impact: the splat and most of the droplets landed
  underneath it and a hit looked like nothing had happened. A pointer only
  has to say *where*.
- **It stops at 86 mm, not at the glass.** Lower, and the struck mole's own
  sprite draws over it, so the strike looks like the mallet went underneath.

The tally is drawn on the table too, at a height **below** the menu plane.
Ordering the two planes is what keeps the menu on top: the first version put
the tally higher, so opening the menu after a round left the tally floating
over the level list and the help panels. The menu path hides it as well, but
the ordering is what makes the mistake impossible rather than something
every future path into the menu has to remember.

Pointer ownership is a function of state -- the mallet has it while a round
is running, the system cursor has it in the menu and once a round is over --
re-asserted every frame rather than toggled at each transition. Toggling was
the first version and it left the cursor captured after a round, so the menu
could not be clicked; a toggle has to be repeated on every path into a state
and Ursina resets cursor visibility during window startup anyway.

A second half of that bug was not about the cursor at all. The menu is drawn
150 mm above the glass, but a touch is reported *on* the glass, so testing a
tap against the rows' own coordinates is wrong by `eye / (eye - height)` --
and the error grows with distance from the eye's axis, so the two info rows
at the edge of the panel were unhittable while the level rows near the
centre still worked. `glass_mm_to_plane_mm` carries the tap up to the plane
it was aimed at.

During a round the mallet simply stays where the hand left it. Retracting
it to a rest spot after every hit was tried and played badly: it had to
travel back before the next swing, so every hit cost a beat of lag exactly
as the game sped up. It only lies down when the round ends, sideways on the
score panel -- off the playfield, where it is neither over a hole hiding the
next mole nor over the splat.

### Difficulty

`beginner` / `medium` / `advanced` are multipliers over a `GameConfig`
(`pace`, `motion`, `crowd`), not three copies of the tuning, so `medium` is
exactly the identity and a level scales whatever base config it is given.
Each level still ramps from its own start values to its own end values over
the round.

### Hit effects

`game/effects.py` is pure Python in millimetres, like the rules, so the
particle faults that do not show up in a screenshot -- droplets that never
settle, lists that grow without bound -- are unit-tested. An impact leaves a
splat that expands fast and lingers, droplets that arc under gravity and
fade where they land, and a squash on the sprite itself, which is the view's
business since it is a property of the card rather than of the world.

### Themes

`render/theme.py` holds palette, light direction, ambient and depth
atmosphere as data, with `day` / `dusk` / `night` presets. Meshes carry shape
only and no colour, and themes key off coarse *roles* (`field`, `soil`,
`creature`, `struck`, `accent`) rather than prop names, so adding a bush or a
rock does not mean revising every theme. `LIT_120` takes all of these as
shader inputs, so a theme swaps at runtime with no geometry rebuild.

This module exists because appearance had leaked into two places at once:
artifact colours as constants in the game app, and `ambient` as a global
*default* on the shader — raising that default to stop the wells rendering
near-black silently changed the lighting of the depth and sky demos too.

### Mesh notes

`render/meshes.py` is shared by the demos and the game.
`revolved_profile_mesh` builds both wells and moles from a `(radius, z)`
profile. Two traps are baked in:

- **A `Mesh` is a scene-graph node, not a shared asset.** Assigning one
  instance to several Entities re-parents that single node, so only one
  entity renders — all 24 holes but one vanished until each got its own mesh.
- **A solid ground quad occludes the wells.** It sits at the `z = 0` plane
  and is opaque, so only a sliver of rim showed. The ground is therefore
  built as one hole-punched patch per grid cell (`field_patch_mesh`), and the
  cells tile the field exactly.
- **A patch's outer ring has to include its cell's corners.** Sampling the
  boundary at uniform angles cuts a triangle off any corner that falls
  between two samples, and neighbouring patches then leave a diamond-shaped
  hole at every shared corner. Whether it shows depends on the cell's aspect
  ratio, so it appeared the moment the grid was re-tuned and the background
  came through the field in a regular pattern.
- **A flat card parked at a well's floor z-fights with the floor.** Mole
  sprites lie flat, so fragments of artwork showed through holes that were
  meant to be empty, and which ones leaked depended on draw order. A resting
  mole is now parked below the floor and not drawn at all.

Ursina's built-in `Pipe` / `Cylinder` cover much of what
`revolved_profile_mesh` does and *do* shade flat via
`generate_normals(smooth=False)`. Ours is kept because it also controls
normal orientation (inward, for the inside of a hole) in one argument. There
is no built-in equivalent of `field_patch_mesh`. Ursina's bundled samples
contain no whack-a-mole or comparable top-down game.

## macOS and OpenGL

**Apple's OpenGL has no GLSL 130 or 140.** Apple never shipped GL 3.0/3.1,
so the only versions available are 120 (legacy 2.1 compatibility context)
and 150 (3.2+ core context). Ursina 8.3's shaders are mostly 130/140 —
including `unlit_with_fog_shader`, the default for every `Entity`, and the
`text_shader` that `Text` hardcodes. Those **can never compile on macOS**.
Ursina's maintainer confirms this in
[issue #594](https://github.com/pokepetter/ursina/issues/594): Apple
supports only its own shading language, and the advice is "don't use these
shaders."

Two consequences, both already handled:

- In a *compatibility* context the failure is survivable — Panda falls back
  to fixed-function and geometry still draws. Requesting a **core** profile
  to unlock GLSL 150 removes that safety net, so anything whose shader fails
  draws nothing. **Do not request a core profile**; the setup module
  documents this.
- `render/shaders.py` ships project shaders at **GLSL 120** — the common
  denominator across macOS 2.1 and Linux compatibility contexts — and
  installs them as the default. Both platforms run identical shader code.
  The trade is no shadow mapping; diffuse shading on extruded side walls
  carries the depth cue instead.

Two residual GLSL 130 errors still appear in the log on macOS, from an
Ursina entity built at import time. They are **cosmetic** — every project
entity renders, as `capture --check` verifies. Chasing them risks
re-blanking the scene, and muting the error category would hide real faults.

## Two traps that cost real time

Recorded because both fail **silently**, with a wrong picture and no error:

1. **`color.rgb` is an alias for `color.rgba` and expects 0.0–1.0 floats.**
   The 0–255 variants are `color.rgb32` / `rgba32`. Passing 0–255 to the
   float version clamps to **opaque white**, so the ground surface became a
   large white quad covering the scene. This looked exactly like "the
   renderer is broken" and sent debugging toward OpenGL profiles and
   Ursina's macOS support before the real cause surfaced.
   `tests/test_color_usage.py` is a static guard against it.
2. **`mode="line"` maps to `GeomLinestrips`**, joining every vertex into one
   path. Disjoint segments need explicit index pairs, or the grid is
   criss-crossed by diagonals.

Also: `base.win.saveScreenshot()` returns a blank image on macOS. Use the
`RTMCopyRam` render-texture approach in `apps/capture.py` — early debugging
wasted effort on captures that were uniformly white no matter what the scene
contained.

## What is verified, and what is not

Verified numerically and through the real renderer (441 passing tests):

- The projection invariant — the view rectangle's corners pin to the
  viewport for every eye position — checked against a reference matrix *and*
  against live Panda3D projection, so a maths bug and a wiring bug are
  distinguishable.
- Raised and recessed geometry parallax in *opposite* directions.
- The film-offset sign is not inverted by Ursina's left-handed system.
- Scale and unit mappings, round-trips, plausibility checks.
- Input phase lifecycle: BEGAN once, ENDED once, ids never recycled.
- Input snapshots survive a round trip through JSON unchanged.
- Layout splits: the playfield stays centred, the bezel profile starts and
  ends flush, and a margin too wide for the display is rejected.
- Ground patches tile: every boundary vertex lies on its cell rectangle and
  all four corners are present, at four different cell aspect ratios.
- Difficulty: `medium` is the identity, each level is faster than the last,
  and the simultaneous-mole cap never rounds down to zero.
- Hit effects: droplets rise, fall, settle and expire; the pools are capped;
  a given seed reproduces a burst exactly.
- Font metrics and mesh layout: every glyph is 5x7, alignment straddles its
  anchor, and UVs stay inside the atlas.

Verified visually, via the capture renders:

- Orthographic shows no side walls; perspective and off-axis do.
- Off-axis left vs right flips which wall is visible and swaps the token's
  shaded face — parallax reverses correctly.
- The sky view reads as looking straight down from altitude: towers splay
  radially from a central vanishing point, which moves with the eye.
- The game scene and the menu, via `./run.sh shots`: the frame and its
  inlay, the scoreboard, a struck mole mid-impact with its splat, and the
  menu in each of its three states.

**Not verified:** whether the depth illusion is actually *convincing* is a
judgement call, not a test. The geometry is provably correct and the renders
look right, but the fog and scale values were tuned by eye and need a human
in front of the screen to say whether they work.
