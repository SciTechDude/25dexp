"""Bake the mole's turn as a strip of frames with a fixed dirt mound.

Why this exists
---------------
``assets/mole_full.png`` paints the mole and its dirt mound on one sheet.
The renderer mirrors that whole card to face the mole the other way, so the
mound mirrors with it: the earth visibly shifts, and during the turn the
spin squeezes the dirt along with the animal. Both are wrong -- a mound of
earth does not move because the mole looked left.

Fixing it in the renderer would need the mound as a separate quad drawn in
*front* of the mole, and that cannot be done honestly here: the mound lies
on the ground while the mole rises above it, so in a top-down view the mole
is always the nearer surface. Forcing the draw order with render bins would
put the mound in front of the start menu too.

So it is fixed in the art instead. This script separates mole from mound,
rebuilds the part of the mound the mole was covering, and bakes one frame
per stage of the turn -- the mole scaled about its own axis over a mound
that is pixel-identical in every frame. The renderer then picks a frame
instead of mirroring a card, and the mound cannot move because it is the
same pixels throughout.

Usage
-----
    python tools/bake_mole_turn_strip.py            # writes the asset
    python tools/bake_mole_turn_strip.py --preview  # plus a contact sheet

Needs Pillow and numpy, which the dev extra already brings in for tests.
The output is committed, so this runs only when the source art changes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
# Run as a plain script, so the repo is not on the path yet; the frame
# widths are the contract with the renderer and must come from the one
# place that defines them.
sys.path.insert(0, str(REPO))

from tabletop.render.assets import MOLE_TURN_FRAME_WIDTHS  # noqa: E402
SOURCE = REPO / "assets" / "mole_full.png"
STRIP = REPO / "assets" / "mole_turn_strip.png"

FRAME_WIDTHS = MOLE_TURN_FRAME_WIDTHS

MOLE, MUD, BG, NONE = 1, 2, 3, 0
INK = 0.30
"""Below this value a pixel is line art, whatever its hue.

The strokes are anti-aliased, so their edges carry a brown or blue tint
that the fill rules would otherwise swallow. Left unassigned, each goes to
the nearest class -- the shape it outlines.
"""


def classify(rgb: np.ndarray) -> np.ndarray:
    """Label every pixel mole / mud / background, by palette.

    The art is flat-coloured, so hue and value separate the classes
    exactly: blue-grey body, peach muzzle and paws, brown mud, green
    grass, white page.
    """
    h, w, _ = rgb.shape
    mx, mn = rgb.max(2), rgb.min(2)
    v = mx
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    d = np.maximum(mx - mn, 1e-6)
    hue = (
        np.select(
            [mx == r, mx == g],
            [((g - b) / d) % 6.0, (b - r) / d + 2.0],
            default=(r - g) / d + 4.0,
        )
        * 60.0
    )

    label = np.zeros((h, w), np.uint8)
    near_white = (v > 0.82) & (s < 0.14)
    # No standalone grey class: the page leaves a grey halo around every
    # outline, and claiming it for the mole body laid a one-pixel mole
    # fringe along the whole length of the mound's edge -- which then made
    # every column of the mound look occluded.
    label[((s < 0.45) & (hue > 180) & (hue < 285) & (v > INK))] = MOLE
    label[(hue < 40) & (v > 0.70) & (s > 0.14)] = MOLE
    label[(hue < 55) & (v > INK) & (v <= 0.72) & (s > 0.28)] = MUD
    label[(hue >= 55) & (hue < 185) & (s > 0.25) & (v > INK)] = MUD

    # Background is the white reachable from the border, so the eye stays
    # with the mole.
    reach = np.zeros((h, w), bool)
    frontier = np.zeros((h, w), bool)
    frontier[0, :] = frontier[-1, :] = True
    frontier[:, 0] = frontier[:, -1] = True
    frontier &= near_white
    while frontier.any():
        reach |= frontier
        grow = np.zeros_like(frontier)
        grow[1:, :] |= frontier[:-1, :]
        grow[:-1, :] |= frontier[1:, :]
        grow[:, 1:] |= frontier[:, :-1]
        grow[:, :-1] |= frontier[:, 1:]
        frontier = grow & near_white & ~reach
    label[reach] = BG
    label[near_white & ~reach] = MOLE

    # Not just ink: the claws are drawn "dark brown to black", and only
    # their black strokes fall under INK. Their brown fill passes the mud
    # rule, so it stayed in the dirt while the strokes travelled with the
    # mole -- half a claw each way.
    claw_dark = v <= CLAW_DARK
    peach = (hue < 40) & (v > 0.70) & (s > 0.14)
    # Order matters: pruning first, claiming second. The other way round,
    # `keep_one_mole` sees each freshly claimed claw as an island of mole
    # unconnected to the body and hands it straight back to the mud --
    # which is exactly the clipping this rule exists to stop.
    # Prune, claim, prune again. The first prune drops dirt detail that
    # the colour rules mistook for mole. The claim then pulls in the mole's
    # own dark line work near its paws -- but by reach, so it also picks up
    # loose clods and arcs of the mound's outline that happen to lie close
    # by, and those then travel with the mole as a handful of specks
    # sliding over the dirt. The second prune keeps only what is actually
    # joined to the animal: a claw is attached to its paw, a clod is not.
    return keep_one_mole(
        claim_claws(keep_one_mole(fill_ink(label)), claw_dark, peach)
    )


def fill_ink(label: np.ndarray) -> np.ndarray:
    """Hand every unassigned (ink) pixel to the nearest class.

    The mole wins ties and advances twice as fast, because the claws are
    drawn *over* the mud: a straight nearest-class split leaves them
    behind when the mole moves. Background never votes -- an outline
    belongs to the thing it draws, not to the empty space beside it, and
    letting it vote put the mole's own silhouette in the mud layer.
    """
    h, w = label.shape
    work = label.copy()
    for step in range(400):
        todo = work == NONE
        if not todo.any():
            break
        votes = np.zeros((h, w, 4), np.int16)
        for shift in range(4):
            n = np.zeros_like(work)
            if shift == 0:
                n[1:, :] = work[:-1, :]
            elif shift == 1:
                n[:-1, :] = work[1:, :]
            elif shift == 2:
                n[:, 1:] = work[:, :-1]
            else:
                n[:, :-1] = work[:, 1:]
            for cls in (MOLE, MUD):
                if cls == MUD and step % 2:
                    continue
                votes[..., cls] += (n == cls).astype(np.int16)
        best = votes.argmax(2).astype(np.uint8)
        work = np.where(todo & (votes.max(2) > 0), best, work)
    return despeckle(work)


FLAT_DIRT = 110
"""Minimum channel value for a pixel to count as plain earth, 0-255.

Used to pick what the mound rebuild is allowed to copy: flat dirt, never
the mound's own black outlines.
"""

CLAW_DARK = 0.52
"""How dark a pixel near a paw has to be to count as the mole's own.

Covers the claws' brown fill as well as their black strokes -- the two
together are what a claw is, and splitting them between the layers left a
dark wedge of claw sitting in the dirt after the mole turned away from it.
Above this value the mound's ordinary mid-brown begins, which must stay
with the mound.
"""

CLAW_REACH_PX = 30
"""How far from a paw or muzzle the mole's own line work extends.

The claws -- five on each paw -- are drawn *over* the mud, below the
peach of the paw, and every outline in the picture fuses into one 18,000
pixel blob of ink, so which shape a stroke belongs to cannot be settled by
connectivity. Nearest-class cannot settle it either: a claw tip has mud
1 px to its side and paw 20 px above it, so the mud wins and the claws get
left behind in the dirt when the mole turns.

What does settle it is reach: nothing in the mud is drawn in black within
26 px of a paw, and the claws and whisker strokes are, so ink that close
to peach belongs to the mole. The cost is a little of the mound's own
outline going with it where a paw rests on the dirt, which the mound
rebuild then fills with plain earth.
"""


def claim_claws(
    label: np.ndarray, dark: np.ndarray, peach: np.ndarray
) -> np.ndarray:
    """Give the mole every dark mark near its paws and muzzle."""
    reach = peach.copy()
    for _ in range(CLAW_REACH_PX):
        grow = reach.copy()
        grow[1:, :] |= reach[:-1, :]
        grow[:-1, :] |= reach[1:, :]
        grow[:, 1:] |= reach[:, :-1]
        grow[:, :-1] |= reach[:, 1:]
        reach = grow
    label[dark & reach & (label == MUD)] = MOLE
    return label


def keep_one_mole(label: np.ndarray) -> np.ndarray:
    """Keep the largest mole blob and give the rest back to the mud.

    In this artwork the animal is a single connected shape -- body, muzzle,
    whiskers and both paws, 97% of everything classed as mole. What is
    left is dirt detail that happened to fall inside the mole's colour
    rules: little clods and grass bases, several of them low down in the
    mound.

    They cannot stay. The mole layer is scaled and mirrored per frame while
    the mound is not, so a speck of "mole" sitting in the dirt moves when
    the frame does -- which is precisely the mound moving, the thing this
    whole strip exists to stop.
    """
    h, w = label.shape
    mole = label == MOLE
    seen = np.zeros((h, w), bool)
    best: list[tuple[int, int]] = []
    for y in range(h):
        for x in range(w):
            if not mole[y, x] or seen[y, x]:
                continue
            stack = [(y, x)]
            seen[y, x] = True
            blob: list[tuple[int, int]] = []
            while stack:
                cy, cx = stack.pop()
                blob.append((cy, cx))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and mole[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if len(blob) > len(best):
                best = blob
    keep = np.zeros((h, w), bool)
    for y, x in best:
        keep[y, x] = True
    label[mole & ~keep] = MUD
    return label


def despeckle(label: np.ndarray, min_px: int = 400) -> np.ndarray:
    """Flip islands smaller than ``min_px`` to the class around them.

    The source is a JPEG-grade scan, so every edge sheds a scatter of
    stray pixels, and a layer peppered with the other layer's confetti is
    not a usable sprite. Specks are never dissolved into the background:
    that would eat real detail at the thin ends of the whiskers.

    The threshold is generous because of what the medium-sized islands
    are: dirt-coloured marks *inside* the mole (claw shading) and
    mole-coloured marks inside the mound. Left alone, a mud island inside
    the head becomes the mound's topmost pixel for its column, which makes
    the occlusion test think the mound's own edge is up there and leaves a
    notch in the rebuilt contour. Absorbing each island into whatever
    surrounds it is both the right look and what keeps the contour sane.
    """
    h, w = label.shape
    seen = np.zeros((h, w), bool)
    for y in range(h):
        for x in range(w):
            if seen[y, x] or label[y, x] == BG:
                continue
            cls = label[y, x]
            stack = [(y, x)]
            seen[y, x] = True
            blob: list[tuple[int, int]] = []
            border: dict[int, int] = {}
            while stack:
                cy, cx = stack.pop()
                blob.append((cy, cx))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if not (0 <= ny < h and 0 <= nx < w):
                        continue
                    if label[ny, nx] == cls:
                        if not seen[ny, nx]:
                            seen[ny, nx] = True
                            stack.append((ny, nx))
                    else:
                        border[int(label[ny, nx])] = (
                            border.get(int(label[ny, nx]), 0) + 1
                        )
            border.pop(BG, None)
            if len(blob) >= min_px or not border:
                continue
            winner = max(border, key=border.get)
            for cy, cx in blob:
                label[cy, cx] = winner
    return label


def smooth_patch(out: np.ndarray, painted: np.ndarray, passes: int = 3) -> np.ndarray:
    """Average the rebuilt pixels with their neighbours.

    Copying column by column leaves faint vertical grain -- each column
    takes its colour from a slightly different donor row. Invisible at
    playing size and obvious in the strip, and a few averaging passes over
    the painted pixels only turn it into plain earth, which is all that
    patch is meant to be.
    """
    if not painted.any():
        return out
    work = out.astype(np.float32)
    solid = (out[..., 3] > 128).astype(np.float32)
    for _ in range(passes):
        total = work[..., :3] * solid[..., None]
        weight = solid.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            total += np.roll(work[..., :3] * solid[..., None], (dy, dx), (0, 1))
            weight += np.roll(solid, (dy, dx), (0, 1))
        averaged = total / np.maximum(weight, 1e-6)[..., None]
        work[..., :3] = np.where(painted[..., None], averaged, work[..., :3])
    out[..., :3] = work[..., :3].round().astype(out.dtype)
    return out


def rebuild_mound(rgba: np.ndarray, label: np.ndarray) -> np.ndarray:
    """Fill in the mound where the mole was covering it.

    Separation leaves a mole-shaped bite in the mud. Mirror the mole over
    that and the bite shows on the wrong side as a ghost of the mole
    facing the old way, so the mound has to be whole first.

    The mound's real top edge across a bite is interpolated between the
    nearest columns that still show their own silhouette, and the fill is
    sampled from the nearest such column at the same relative depth, so
    the lobes and shading come across instead of a vertical smear. Crude,
    and it does not need to be better: the mole stands in front of most of
    it in every frame.
    """
    h, w, _ = rgba.shape
    mud = label == MUD
    mole = label == MOLE
    out = rgba.copy()
    out[..., 3] = np.where(mud, 255, 0)
    painted = np.zeros(out.shape[:2], bool)

    cols = np.nonzero(mud.any(0))[0]
    top = np.full(w, -1)
    bottom = np.full(w, -1)
    for x in cols:
        ys = np.nonzero(mud[:, x])[0]
        top[x], bottom[x] = ys[0], ys[-1]

    # Where the mole covers the mound's top edge, the mole's pixels sit
    # *above* that edge rather than inside the mound's band -- so the test
    # is what the edge touches. Touching the mole means it is an occlusion
    # boundary and the mound continues behind it. A stray pixel is not a
    # bite: whiskers and grass reach across most of the image.
    # A whisker is not a body. Requiring several mole pixels in the rows
    # above the mound's edge, rather than any at all, is what stops a
    # whisker tip marking its column as occluded -- which interpolated the
    # contour up from far-off columns and painted blocks of dirt into the
    # sky above the mound's real right-hand lobe.
    contact, min_contact, min_intrusion = 10, 6, 12
    bitten = np.zeros(w, bool)
    for x in cols:
        above = mole[max(0, top[x] - contact) : top[x], x]
        band = mole[top[x] : bottom[x] + 1, x]
        bitten[x] = (
            int(above.sum()) >= min_contact or int(band.sum()) > min_intrusion
        )

    clean = cols[~bitten[cols]]
    if not clean.size:
        return out

    # Spans of bitten columns, rebuilt by copying an intact stretch of the
    # mound of the same width. Interpolating the top edge instead gave a
    # straight line, and a straight line capped with an outline reads as a
    # crate rather than as earth: the mound is all lobes, so the fill has
    # to bring lobes with it.
    runs: list[tuple[int, int]] = []
    start = None
    for x in range(w):
        if x in cols and bitten[x]:
            start = x if start is None else start
        elif start is not None:
            runs.append((start, x - 1))
            start = None
    if start is not None:
        runs.append((start, w - 1))

    # The quarry every patch is cut from: the longest run of intact
    # columns that is mound and nothing else. Grass has to be excluded by
    # hand -- the longest clean run happens to be the right-hand end of
    # the mound, where the tufts are, and copying those into the middle
    # planted grass in the gap the mole had been standing in.
    g, r, b = rgba[..., 1], rgba[..., 0], rgba[..., 2]
    grassy = ((g > r + 10) & (g > b + 10) & (rgba[..., 3] > 128)).any(0)
    gaps = np.nonzero(np.diff(clean) > 1)[0]
    stretches = [st[~grassy[st]] for st in np.split(clean, gaps + 1)]
    stretches = [st for st in stretches if st.size]
    quarry = max(stretches, key=len) if stretches else clean

    # Plain dirt, for any column the patch copy cannot serve.
    earthy = mud & (rgba[..., 0] - rgba[..., 2] >= 20) & (
        rgba[..., :3].max(2) >= FLAT_DIRT
    )
    median_dirt = (
        np.median(rgba[earthy][:, :3], axis=0).astype(np.int16)
        if earthy.any()
        else np.array([144, 96, 48], np.int16)
    )

    for a, b in runs:
        span = b - a + 1
        for i, x in enumerate(range(a, b + 1)):
            # Walk the quarry and turn back at its ends, so the copy never
            # runs out however wide the bite is.
            step = i % max(1, 2 * (len(quarry) - 1))
            k = step if step < len(quarry) else 2 * (len(quarry) - 1) - step
            donor = int(quarry[k])
            # Match the mound's height at the edges of the bite so the
            # patch meets the real contour without a step.
            left_ref = clean[clean < a]
            right_ref = clean[clean > b]
            lo_edge = top[left_ref[-1]] if left_ref.size else top[donor]
            hi_edge = top[right_ref[0]] if right_ref.size else top[donor]
            f = i / max(1, span - 1)
            want_top = (1 - f) * lo_edge + f * hi_edge
            shift = int(round(want_top - top[donor]))
            lo = max(0, top[donor] + shift)
            hi = bottom[x] if bottom[x] > lo else min(h - 1, bottom[donor] + shift)
            # Only solid, *flat* pixels are worth copying. Two reasons:
            # a donor pixel the pale scrub emptied still carries its old
            # white in RGB, and copying that wrote opaque white into the
            # dirt; and a donor's black lobe outlines, mapped by relative
            # depth into a tall narrow hole, come out stretched into dark
            # wedges -- which read as a clipped claw left behind in the
            # mound once the mole turns off it. Plain earth is what belongs
            # under a mole.
            # "Mud colour" means brown, not merely light: a neutral grey
            # passes a brightness test and reads as a smear of ash in the
            # dirt.
            col = rgba[:, donor]
            donor_rows = np.nonzero(
                (col[:, 3] > 128)
                & (col[:, :3].max(1) >= FLAT_DIRT)
                & (col[:, 0] - col[:, 2] >= 20)
            )[0]
            for y in range(lo, hi + 1):
                if mud[y, x]:
                    continue
                if donor_rows.size:
                    f2 = (y - lo) / max(1, hi - lo)
                    sy = int(round(top[donor] + f2 * (bottom[donor] - top[donor])))
                    sy = int(donor_rows[np.argmin(np.abs(donor_rows - sy))])
                    out[y, x, :3] = rgba[sy, donor, :3]
                else:
                    # A donor with no earth in it at all would otherwise
                    # leave the column unfilled -- a one pixel white seam
                    # straight down the mound.
                    out[y, x, :3] = median_dirt
                out[y, x, 3] = 255
                painted[y, x] = True

    # Safety pass: a donor column can be shorter than the hole it is
    # filling, which left a transparent slot through the mound. Anything
    # still see-through between the rebuilt edge and the mound's own bottom
    # takes the nearest solid colour below it in its own column.
    for a, b_ in runs:
        for x in range(a, b_ + 1):
            if bottom[x] < 0:
                continue
            solid = np.nonzero(out[:, x, 3] > 128)[0]
            if not solid.size:
                continue
            for y in range(solid[0], bottom[x] + 1):
                if out[y, x, 3] > 128:
                    continue
                below = solid[solid > y]
                src_y = below[0] if below.size else solid[-1]
                out[y, x, :3] = out[src_y, x, :3]
                out[y, x, 3] = 255
                painted[y, x] = True
    return smooth_patch(out, painted)


def scrub_pale(rgba: np.ndarray, threshold: int = 170) -> np.ndarray:
    """Replace near-white pixels in a layer with the nearest real colour.

    The page shows through in two ways that both end up inside the mud
    layer: flecks of white where the separation took a highlight, and the
    grey halo the scan leaves around every black outline. Harmless on their
    own -- but the mound rebuild copies colour from its neighbours, so a
    pale pixel becomes a pale *streak* smeared down the dirt, which is
    exactly as visible as the hole it was filling.
    """
    out = rgba.copy()
    opaque = out[..., 3] > 128
    chroma = out[..., :3].max(2) - out[..., :3].min(2)
    value = out[..., :3].max(2)
    # Pale, and also mid-grey: the scan's halo around each outline is a
    # neutral grey that is too dark for the pale test but has no business
    # in a mound of earth. Black is left alone -- that is the outline
    # itself.
    pale = opaque & (
        (out[..., :3].min(2) > threshold)
        | ((chroma < 20) & (value > 60) & (value <= threshold))
    )
    if not pale.any():
        return out
    out[..., 3] = np.where(pale, 0, out[..., 3])
    for _ in range(200):
        todo = pale & (out[..., 3] <= 128)
        if not todo.any():
            break
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            src = np.roll(out, (dy, dx), axis=(0, 1))
            take = (
                todo
                & (src[..., 3] > 128)
                & (src[..., :3].min(2) <= threshold)
                & (src[..., :3].max(2) - src[..., :3].min(2) >= 20)
            )
            out[take] = src[take]
            todo &= ~take
    # Anything still pale had no better neighbour: drop it rather than
    # leave a white speck in the dirt.
    still = pale & (out[..., 3] <= 128)
    out[still] = 0
    return out


def recentre(layer: np.ndarray) -> np.ndarray:
    """Shift a layer so its centre of mass sits at the card's centre.

    The card is positioned on the hole, so this is what puts the mole over
    the hole -- and it is what stops the two poses drifting. Mirroring
    happens about the same centre, so a mole that turns keeps its mass
    exactly where it was instead of sliding sideways by the offset between
    its own centre and the card's.

    Centre of *mass*, not of the bounding box: the snout is long and thin
    and the claws reach left, so the box centre sits 16 px right of where
    the animal's weight actually is.
    """
    h, w, _ = layer.shape
    ys, xs = np.nonzero(layer[..., 3] > 128)
    if not xs.size:
        return layer
    # (w - 1) / 2, not w / 2: a horizontal flip maps x to w - 1 - x, so
    # that is the axis the mirror actually uses. Centring on w / 2 instead
    # left the two poses a pixel and a half apart -- small, but it is
    # exactly the drift this is here to prevent.
    shift = int(round((w - 1) / 2 - xs.mean()))
    if shift == 0:
        return layer
    out = np.zeros_like(layer)
    if shift > 0:
        out[:, shift:] = layer[:, : w - shift]
    else:
        out[:, : w + shift] = layer[:, -shift:]
    return out


def fill_interior_holes(rgba: np.ndarray) -> np.ndarray:
    """Close any transparent pocket the mound encloses.

    Separating by colour leaves small holes where a mole-coloured detail
    sat inside the mound -- the tips of the two claws, in this artwork.
    They are a few dozen pixels each and they show: the mole covers them in
    the pose it was drawn in, so they only appear once it turns, as a pair
    of pale specks in the dirt where a claw used to be.

    A pocket is transparency that cannot be reached from the border, which
    distinguishes it from the sky above the mound. Each one takes the
    colour of the nearest solid pixel.
    """
    out = rgba.copy()
    solid = out[..., 3] > 128
    holes = ~solid

    reach = np.zeros_like(holes)
    front = np.zeros_like(holes)
    front[0, :] = front[-1, :] = True
    front[:, 0] = front[:, -1] = True
    front &= holes
    while front.any():
        reach |= front
        grow = np.zeros_like(front)
        grow[1:, :] |= front[:-1, :]
        grow[:-1, :] |= front[1:, :]
        grow[:, 1:] |= front[:, :-1]
        grow[:, :-1] |= front[:, 1:]
        front = grow & holes & ~reach

    pockets = holes & ~reach
    if not pockets.any():
        return out

    # Grow the solid colour inwards until the pockets are gone, taking
    # mid-tone colour before outline colour. Outlines are the nearest
    # neighbour of plenty of pockets -- the white gaps between grass
    # blades, for one -- and filling from them turns a pocket into a black
    # blob, which is worse than the pocket.
    for prefer_midtone in (True, False):
        for _ in range(200):
            todo = pockets & (out[..., 3] <= 128)
            if not todo.any():
                break
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                src = np.roll(out, (dy, dx), axis=(0, 1))
                take = todo & (src[..., 3] > 128)
                if prefer_midtone:
                    take &= src[..., :3].max(2) >= FLAT_DIRT
                out[take] = src[take]
                todo &= ~take
    return out


def spun(layer: Image.Image, factor: float) -> Image.Image:
    """``layer`` squeezed about the card's centre, mirrored if negative.

    This is the spin: a card with no thickness presents ``cos(angle)`` of
    its width, and the sign flips as it passes edge-on.

    Everything happens about the centre of the card, which is where
    :func:`recentre` has already put the mole's centre of mass -- so the
    squeeze is symmetric and the mirror is a straight flip. The two rest
    poses then have the same centre, which is what stops the mole
    appearing to drift sideways when it changes direction.
    """
    w, h = layer.size
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if abs(factor) < 1e-3:
        return out
    src = layer.transpose(Image.FLIP_LEFT_RIGHT) if factor < 0 else layer
    new_w = max(1, int(round(w * abs(factor))))
    squeezed = src.resize((new_w, h), Image.LANCZOS)
    out.paste(squeezed, ((w - new_w) // 2, 0), squeezed)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out", type=Path, default=STRIP)
    parser.add_argument(
        "--preview", action="store_true", help="also write a contact sheet"
    )
    args = parser.parse_args()

    src = Image.open(args.source).convert("RGBA")
    rgba = np.asarray(src).astype(np.int16)
    rgb = (np.asarray(src.convert("RGB")).astype(np.float32)) / 255.0

    label = classify(rgb)
    # Scrub before rebuilding, not after: the rebuild copies colour from
    # its neighbours, so a pale pixel left in place is smeared rather than
    # replaced.
    mud_layer = np.asarray(src).copy()
    mud_layer[..., 3] = np.where(label == MUD, 255, 0)
    scrubbed = scrub_pale(mud_layer)
    mound = fill_interior_holes(rebuild_mound(scrubbed.astype(np.int16), label))
    mound_img = Image.fromarray(mound.astype(np.uint8), "RGBA")

    mole_layer = np.asarray(src).copy()
    mole_layer[..., 3] = np.where(label == MOLE, 255, 0)
    mole_img = Image.fromarray(recentre(scrub_pale(mole_layer)), "RGBA")

    w, h = src.size

    frames = []
    for factor in FRAME_WIDTHS:
        frame = mound_img.copy()
        frame.alpha_composite(spun(mole_img, factor))
        # Again after compositing: resampling the mole leaves a few
        # part-transparent pixels along its edge, and a pinhole between
        # mole and mound reads as the same pale speck in the dirt as a
        # claw-shaped hole does.
        frame = Image.fromarray(
            fill_interior_holes(np.asarray(frame)).astype(np.uint8), "RGBA"
        )
        frames.append(frame)

    strip = Image.new("RGBA", (w * len(frames), h), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        strip.paste(frame, (i * w, 0))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    strip.save(args.out)
    print(f"wrote {args.out} ({strip.size[0]}x{strip.size[1]}, {len(frames)} frames)")
    print(f"  mirrored about the card centre x={w // 2}, widths {FRAME_WIDTHS}")

    if args.preview:
        sheet = Image.new(
            "RGB", (w * len(frames), h), (232, 232, 232)
        )
        for i, frame in enumerate(frames):
            cell = Image.new("RGBA", (w, h), (232, 232, 232, 255))
            cell.alpha_composite(frame)
            sheet.paste(cell.convert("RGB"), (i * w, 0))
        preview = args.out.with_name("mole_turn_preview.png")
        sheet.save(preview)
        print(f"wrote {preview}")


if __name__ == "__main__":
    main()
