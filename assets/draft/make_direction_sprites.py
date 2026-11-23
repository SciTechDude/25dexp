"""4-direction mole sprite set derived from one source drawing."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

src = Path(sys.argv[1]); out = Path(sys.argv[2])
im = Image.open(src).convert("RGBA")
w, h = im.size
px = im.load()

body = px[int(w * 0.40), int(h * 0.42)][:3] + (255,)
tan = px[int(w * 0.52), int(h * 0.26)][:3] + (255,)
ink = (26, 26, 32, 255)
MOUND_TOP = int(h * 0.52)
HEAD_BOX = (int(w * 0.24), 0, int(w * 0.92), MOUND_TOP)

cols = [x for x in range(w) for y in range(MOUND_TOP, h) if px[x, y][3] > 80]
mound_brown = px[(min(cols) + max(cols)) // 2, int(h * 0.75)][:3] + (255,)

def _paw_centre() -> int:
    """Midpoint of the two forepaws, which marks the hole's opening.

    Better than the mound's pixel centroid: the mound spreads wide and
    includes grass tufts off to one side, so its centroid sits right of
    where the mole actually emerges, and a body centred there looks offset.
    """
    pts = [(x, y) for x in range(w) for y in range(MOUND_TOP, h)
           if px[x, y][3] > 80
           and all(abs(px[x, y][i] - tan[i]) < 32 for i in range(3))]
    if not pts:
        return w // 2
    xs = [p[0] for p in pts]
    return (min(xs) + max(xs)) // 2


# Tight tolerance. At 60 this also matched the mound's own brown -- mound
# (149,105,70) is only ~70 from the paw tan (222,170,135) per channel -- and
# the "paw" cover ellipses swallowed the entire mound.
TOL = 32
mound_cx = None  # set after is_tan is available


def is_tan(c):
    return c[3] > 80 and all(abs(c[i] - tan[i]) < TOL for i in range(3))


mound_cx = _paw_centre()


def mound_layer(with_paws: bool) -> Image.Image:
    base = im.copy()
    ImageDraw.Draw(base).rectangle(HEAD_BOX, fill=(0, 0, 0, 0))
    if with_paws:
        return base
    bp = base.load()
    pts = [(x, y) for x in range(w) for y in range(MOUND_TOP, h)
           if is_tan(bp[x, y])]
    if pts:
        mid = (min(p[0] for p in pts) + max(p[0] for p in pts)) // 2
        d = ImageDraw.Draw(base)
        for group in ([p for p in pts if p[0] <= mid],
                      [p for p in pts if p[0] > mid]):
            if not group:
                continue
            gx = [p[0] for p in group]; gy = [p[1] for p in group]
            pad = int(w * 0.018)
            # Clamp the cover so a stray match cannot erase the mound.
            x0 = max(min(gx) - pad, 0)
            x1 = min(max(gx) + pad, x0 + int(w * 0.17))
            y0 = max(min(gy) - pad, MOUND_TOP)
            y1 = min(max(gy) + pad, y0 + int(h * 0.26))
            d.ellipse((x0, y0, x1, y1), fill=mound_brown)
    return base


def hourglass(canvas: Image.Image):
    d = ImageDraw.Draw(canvas)
    torso_r = int(w * 0.128)
    head_r = int(w * 0.092)
    torso_cy = MOUND_TOP - int(torso_r * 0.30)
    head_cy = torso_cy - torso_r - int(head_r * 0.08)
    d.ellipse((mound_cx - torso_r, torso_cy - torso_r,
               mound_cx + torso_r, torso_cy + torso_r),
              fill=body, outline=ink, width=5)
    ear = int(w * 0.034)
    for side in (-1, 1):
        ex = mound_cx + side * int(head_r * 0.80)
        ey = head_cy - int(head_r * 0.60)
        d.ellipse((ex - ear, ey - ear, ex + ear, ey + ear),
                  fill=body, outline=ink, width=4)
    box = (mound_cx - head_r, head_cy - head_r,
           mound_cx + head_r, head_cy + head_r)
    d.ellipse(box, fill=body, outline=ink, width=5)
    return box, torso_r, torso_cy


def tail(canvas: Image.Image, torso_r: int, torso_cy: int) -> None:
    """A short tapered tail poking out of the mound beside the body.

    Replaces the paws on the back view: from behind you would see the tail,
    not the forepaws gripping the far rim.
    """
    d = ImageDraw.Draw(canvas)
    x = mound_cx + int(torso_r * 1.05)
    y = torso_cy + int(torso_r * 0.35)
    seg = [(x, y), (x + int(w * 0.055), y - int(h * 0.045)),
           (x + int(w * 0.105), y - int(h * 0.125))]
    for i, width in ((0, 15), (1, 10)):
        d.line((seg[i], seg[i + 1]), fill=ink, width=width + 5)
    for i, width in ((0, 15), (1, 10)):
        d.line((seg[i], seg[i + 1]), fill=body, width=width)
    tip = int(w * 0.016)
    d.ellipse((seg[-1][0] - tip, seg[-1][1] - tip,
               seg[-1][0] + tip, seg[-1][1] + tip),
              fill=body, outline=ink, width=3)


def finish(canvas: Image.Image, with_paws: bool) -> Image.Image:
    canvas.alpha_composite(
        mound_layer(with_paws).crop((0, MOUND_TOP, w, h)), (0, MOUND_TOP)
    )
    return canvas


# ---- back: body from behind, tail instead of paws ----
back = mound_layer(with_paws=False)
_, t_r, t_cy = hourglass(back)
tail(back, t_r, t_cy)
back = finish(back, with_paws=False)
back.save(out / "mole_back.png")

# ---- front: body with a face, paws kept ----
front = mound_layer(with_paws=True)
(bx0, by0, bx1, by1), _, _ = hourglass(front)
d = ImageDraw.Draw(front)
cx = (bx0 + bx1) // 2
hw = bx1 - bx0
eye_y = by0 + int(hw * 0.33)
er = int(w * 0.022)
for side in (-1, 1):
    ex = cx + side * int(hw * 0.24)
    d.ellipse((ex - er, eye_y - er, ex + er, eye_y + er),
              fill=(255, 255, 255, 255), outline=ink, width=3)
    pr = int(er * 0.5)
    d.ellipse((ex - pr, eye_y - pr, ex + pr, eye_y + pr), fill=ink)
mw, mh = int(hw * 0.50), int(hw * 0.32)
my = by0 + int(hw * 0.54)
d.ellipse((cx - mw // 2, my, cx + mw // 2, my + mh),
          fill=tan, outline=ink, width=4)
nr = int(w * 0.017)
d.ellipse((cx - nr, my + mh // 2 - nr, cx + nr, my + mh // 2 + nr), fill=ink)
for side in (-1, 1):
    for k, dy in enumerate((-4, 2, 8)):
        x0 = cx + side * (mw // 2 - 3)
        d.line((x0, my + mh // 2 + dy,
                x0 + side * int(w * 0.075), my + mh // 2 + dy - 4 + k * 3),
               fill=ink, width=3)
front = finish(front, with_paws=True)
front.save(out / "mole_front.png")

im.transpose(Image.FLIP_LEFT_RIGHT).save(out / "mole_left.png")
im.save(out / "mole_right.png")
print(f"mound cx={mound_cx}/{w} body={body[:3]} mound={mound_brown[:3]}")
