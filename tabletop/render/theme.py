"""Scene themes: palette, lighting and atmosphere as data.

Geometry and appearance are kept separate on purpose. The mesh builders in
:mod:`tabletop.render.meshes` describe *shape* only — a hole, a mole, a
ground patch — and carry no colour. Everything that makes a scene look like
midday or midnight lives here, as plain data.

Why this is worth a module rather than a handful of constants
-------------------------------------------------------------
Appearance was originally scattered: artifact colours as constants in the
game app, and ``ambient`` as a module-level *default* on the shader. Raising
that default to stop whack-a-mole's wells rendering near-black silently
changed the lighting of the depth and sky demos too — a global knob
masquerading as a local fix. Themes make the dependency explicit and
per-entity instead.

:data:`LIT_120` already accepts ``light_direction``, ``ambient``,
``fog_color``, ``fog_depth`` and ``fog_amount`` as shader inputs, so a theme
can be swapped at runtime with no geometry rebuild and no shader reload.

Adding an artifact
------------------
Give it a role name, add a colour for that role to every theme, and the mesh
stays untouched. Roles are deliberately coarse (``field``, ``soil``,
``creature``...) rather than named after specific props, so a theme does not
have to be revised every time a bush or a rock is added.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ursina import Vec3, color
from ursina.color import Color

__all__ = [
    "Theme",
    "DAY",
    "DUSK",
    "NIGHT",
    "THEMES",
    "theme_by_name",
    "BezelFinish",
    "ARCADE",
    "NEON",
    "EBONY",
    "TAN",
    "FINISHES",
    "finish_by_name",
]


@dataclass(frozen=True)
class Theme:
    """A complete look: colours, light, and depth atmosphere."""

    name: str

    # --- atmosphere -----------------------------------------------------
    background: Color
    """Window clear colour: what shows beyond the playfield."""

    light_direction: Vec3
    """World-space direction from a surface *toward* the light."""

    ambient: float
    """Floor brightness. Surfaces facing away from the light fall back to
    this, so it sets how readable the inside of a deep hole is. Low ambient
    is what makes a night scene feel night-time rather than merely dim."""

    fog_color: Vec3
    """What receding geometry fades toward. Keep it near ``background`` so
    depth fades into the backdrop rather than toward an unrelated hue."""

    depth_gradient: float
    """Strength of the depth-keyed fade, 0..1."""

    # --- artifact colours -----------------------------------------------
    colors: dict[str, Color] = field(default_factory=dict)
    """Keyed by coarse *role*, not by prop name.

    ``field``    ground surface
    ``soil``     the inside of a hole
    ``creature`` a mole at rest
    ``struck``   a mole that has just been hit
    ``accent``   highlights, rims, score flashes
    ``blood``    impact droplets and the splat they leave
    ``gore``     heavier chunks thrown by an impact
    """

    tints: dict[str, Color] = field(default_factory=dict)
    """Multiplier for *textured* surfaces, keyed by the same roles.

    Painted artwork already contains its own colour and shading, so applying
    a theme's flat colour to it multiplies the two and muddies the result --
    a bright grass texture tinted with the theme's mid-green rendered as dark
    olive. Textured surfaces therefore get a near-white tint by day, and a
    dimmer, cooler one at night, which preserves theme response without
    fighting the art.
    """

    def tint_for(self, role: str) -> Color:
        return self.tints.get(role, color.white)

    def color_for(self, role: str) -> Color:
        try:
            return self.colors[role]
        except KeyError as exc:
            raise KeyError(
                f"theme {self.name!r} has no colour for role {role!r}; "
                f"known roles: {sorted(self.colors)}"
            ) from exc


@dataclass(frozen=True)
class BezelFinish:
    """The frame's material, which is separate from the time of day.

    Kept separate from :class:`Theme` on purpose. A theme is *light* -- it
    changes when the scene's sun moves, and :data:`LIT_120` already shades
    the bezel's chamfers with it. The finish is a property of the furniture,
    and a wooden table does not change colour at dusk. Folding it into the
    themes would also mean tuning every finish for every theme, which is
    three times the work for a worse answer.

    The text colours travel with the finish rather than with the theme
    because contrast is a property of what the text is printed *on*: the
    pale ink that reads on ebony vanishes on tan.
    """

    name: str
    surface: Color
    """The raised bezel moulding."""

    band: Color
    """The flat score band inside it. Darker than the surface, so the frame
    reads as two pieces and the text has something to sit on."""

    inlay: Color
    """A bright stripe along the bezel's flat top, and a line at the
    playfield edge. Two thin rings of saturated colour against a dark frame
    is what makes a border read as a cabinet rather than as furniture."""

    text: Color
    dim_text: Color
    """For secondary figures, so the score itself reads first."""

    banner: Color
    """The round-over tally, which is read over the *playfield* rather than
    over the frame. That is a green field, so the figures cannot reuse the
    band's amber: a warm colour on green has little luminance contrast and
    the text disappears into it. A cold, bright blue is the furthest thing
    from green on the colour wheel and the easiest to pick out."""


ARCADE = BezelFinish(
    name="arcade",
    # Cabinet black with a magenta inlay and amber figures: saturated
    # primaries on near-black, which is the palette a lit cabinet bezel
    # actually has, and the highest contrast available against the green
    # playfield it surrounds.
    surface=color.rgb32(22, 20, 28),
    band=color.rgb32(10, 9, 14),
    inlay=color.rgb32(255, 48, 136),
    text=color.rgb32(255, 214, 64),
    dim_text=color.rgb32(96, 224, 255),
    banner=color.rgb32(72, 200, 255),
)

NEON = BezelFinish(
    name="neon",
    surface=color.rgb32(16, 18, 34),
    band=color.rgb32(8, 9, 20),
    inlay=color.rgb32(64, 240, 255),
    text=color.rgb32(126, 255, 160),
    dim_text=color.rgb32(196, 140, 255),
    banner=color.rgb32(120, 180, 255),
)

EBONY = BezelFinish(
    name="ebony",
    # Not black: a true black bezel loses its chamfers entirely, because
    # shading can only darken from the base colour and there is nowhere
    # below black to go. A dark warm brown keeps the bevels visible.
    surface=color.rgb32(52, 40, 34),
    band=color.rgb32(28, 23, 21),
    inlay=color.rgb32(236, 176, 72),
    text=color.rgb32(242, 232, 214),
    dim_text=color.rgb32(168, 154, 138),
    banner=color.rgb32(108, 206, 255),
)

TAN = BezelFinish(
    name="tan",
    surface=color.rgb32(196, 155, 106),
    band=color.rgb32(126, 96, 62),
    inlay=color.rgb32(84, 54, 30),
    # Pale ink, not dark: the band is a mid-brown, and dark text on it has
    # less contrast than light text does.
    text=color.rgb32(248, 240, 224),
    dim_text=color.rgb32(216, 198, 170),
    banner=color.rgb32(108, 206, 255),
)

FINISHES: tuple[BezelFinish, ...] = (ARCADE, NEON, EBONY, TAN)


def finish_by_name(name: str) -> BezelFinish:
    for finish in FINISHES:
        if finish.name == name:
            return finish
    raise ValueError(
        f"unknown bezel finish {name!r}; available: {[f.name for f in FINISHES]}"
    )


DAY = Theme(
    name="day",
    background=color.rgb32(58, 74, 86),
    # Mostly overhead and off to one side, so sloped surfaces shade unevenly.
    # A purely vertical light flattens everything seen from above.
    light_direction=Vec3(0.45, 0.85, -0.35).normalized(),
    # High for a directional-only setup. Leaning and inward-facing surfaces
    # (a mole tipped back, the wall of a hole) turn away from the single
    # light and fall back to ambient entirely, so a low value renders them
    # near-black with no fill light to rescue them.
    ambient=0.72,
    fog_color=Vec3(0.18, 0.24, 0.30),
    depth_gradient=0.28,
    colors={
        "field": color.rgb32(126, 186, 104),
        "soil": color.rgb32(172, 136, 100),
        "creature": color.rgb32(246, 206, 158),
        "struck": color.rgb32(255, 150, 110),
        "accent": color.rgb32(246, 214, 120),
        # Saturated and slightly orange rather than crimson: against the
        # mid-green field a pure red reads as muddy brown, and the splat has
        # to be legible from across the table in well under a second.
        "blood": color.rgb32(214, 38, 40),
        "gore": color.rgb32(152, 54, 50),
    },
    tints={
        "field": color.rgb32(255, 255, 255),
        "creature": color.rgb32(255, 255, 255),
    },
)

DUSK = Theme(
    name="dusk",
    background=color.rgb32(30, 22, 32),
    # Low and raking, which lengthens the shading contrast across sloped
    # surfaces -- the cheapest way to make a scene read as "late".
    light_direction=Vec3(0.75, 0.42, -0.5).normalized(),
    ambient=0.38,
    fog_color=Vec3(0.20, 0.13, 0.18),
    depth_gradient=0.6,
    colors={
        "field": color.rgb32(86, 112, 76),
        "soil": color.rgb32(110, 76, 58),
        "creature": color.rgb32(198, 140, 100),
        "struck": color.rgb32(255, 158, 108),
        "accent": color.rgb32(246, 170, 96),
        "blood": color.rgb32(196, 34, 36),
        "gore": color.rgb32(138, 48, 44),
    },
    tints={
        "field": color.rgb32(216, 190, 170),
        "creature": color.rgb32(232, 204, 184),
    },
)

NIGHT = Theme(
    name="night",
    background=color.rgb32(8, 11, 18),
    light_direction=Vec3(0.3, 0.9, -0.25).normalized(),
    # Deliberately low: holes should go genuinely dark, so a mole emerging
    # into the light is the thing that draws the eye.
    ambient=0.22,
    fog_color=Vec3(0.05, 0.07, 0.12),
    depth_gradient=0.75,
    colors={
        "field": color.rgb32(44, 72, 58),
        "soil": color.rgb32(62, 48, 40),
        "creature": color.rgb32(150, 120, 96),
        "struck": color.rgb32(226, 150, 110),
        "accent": color.rgb32(132, 190, 236),
        # Brighter than the dusk value, not darker: the night field is very
        # dark, so the splat needs the contrast to carry at all. Dimming it
        # with the scene would hide the only confirmation a hit registered.
        "blood": color.rgb32(206, 44, 46),
        "gore": color.rgb32(128, 46, 44),
    },
    tints={
        "field": color.rgb32(120, 140, 170),
        "creature": color.rgb32(150, 165, 190),
    },
)

THEMES: tuple[Theme, ...] = (DAY, DUSK, NIGHT)


def theme_by_name(name: str) -> Theme:
    for theme in THEMES:
        if theme.name == name:
            return theme
    raise ValueError(
        f"unknown theme {name!r}; available: {[t.name for t in THEMES]}"
    )


def apply_theme_to(
    entity,  # ursina Entity
    theme: Theme,
    role: str,
    depth_span_world: float | None = None,
    depth_gradient: float | None = None,
    textured: bool = False,
    color_override: Color | None = None,
) -> None:
    """Point one entity at a theme.

    Pass ``textured=True`` for entities carrying artwork, so they receive
    the theme's near-white tint instead of its flat colour.

    ``color_override`` keeps an entity's own colour while still handing it
    the theme's lighting inputs. That is what the rail needs: it is lit by
    the scene but coloured by its finish (see :class:`BezelFinish`), so
    ``role`` is only consulted for the shader inputs it shares with
    everything else.

    ``depth_span_world`` is the depth over which the gradient saturates, in
    world units; pass the entity's own extent so the ramp spans exactly that
    object rather than a fixed global range. ``depth_gradient`` overrides the
    theme's strength for surfaces that should not fade at all (flat ground,
    for instance, where a gradient only dims it).
    """
    if color_override is not None:
        entity.color = color_override
    else:
        entity.color = theme.tint_for(role) if textured else theme.color_for(role)
    entity.set_shader_input("light_direction", theme.light_direction)
    entity.set_shader_input("ambient", theme.ambient)
    entity.set_shader_input("fog_color", theme.fog_color)
    entity.set_shader_input(
        "fog_amount",
        theme.depth_gradient if depth_gradient is None else depth_gradient,
    )
    if depth_span_world is not None:
        entity.set_shader_input("fog_depth", depth_span_world)
