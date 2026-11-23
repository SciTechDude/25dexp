# Draft sprites — not used by the game

Kept because the notes are worth more than the pixels. Nothing here is
loaded at runtime.

## Status

- `mole_front.png`, `mole_back.png` — **drafts, rejected for now.** Derived
  from `../mole_full.png` by replacing its head with an hourglass body
  (small head circle over a larger torso), plus a face on the front and a
  tail on the back. They read as a mole but lose the source drawing's
  character, and two artefacts remain: a brown step on the left of the mound
  where the original head's bounding box was blanked, and flat patches on
  the back where the paws were painted out.

- `make_direction_sprites.py` — the generator. Samples the body, snout and
  mound colours from the source rather than hardcoding them, and centres the
  body on the **midpoint between the forepaws** (which marks the hole) rather
  than on the mound's pixel centroid, because the mound spreads right and
  includes grass tufts that drag the centroid off the opening.

## Why left/right are not here

They do not need to exist as files. The source art faces right, and a flat
card is mirrored at runtime with a negative X scale — free, and the art is
asymmetric only in its gaze. See `MIRROR_MODES` in
`tabletop/apps/whack_a_mole.py`.

## What went wrong with front/back

Both artefacts share one cause: the original head is removed by blanking its
*bounding rectangle*, and the head overlaps the mound. A colour-based mask
would clear both up. Drawing them by hand would be better still.
