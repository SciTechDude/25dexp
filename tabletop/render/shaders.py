"""Project shaders, written in GLSL 120 so they compile everywhere.

Why this module exists
----------------------
Apple's OpenGL implementation never shipped GL 3.0 or 3.1, so **GLSL 130 and
140 cannot compile on macOS at all**. The versions available are:

* GLSL 120, in the legacy 2.1 *compatibility* context (the default), and
* GLSL 150, only in a 3.2+ *core* context.

Ursina's own shaders are mostly 130/140, including ``unlit_with_fog_shader``
(the default for every ``Entity``) and the ``text_shader`` that ``Text``
hardcodes. On macOS those always fail to compile.

In a compatibility context that failure is survivable: Panda3D falls back to
the fixed-function pipeline and the geometry still draws. Requesting a core
profile to unlock GLSL 150 removes that safety net -- there is no
fixed-function pipeline in core, so anything whose shader fails to compile
draws *nothing*. That is strictly worse, and was the original cause of the
blank/partial rendering here.

So: stay in the compatibility context and supply our own GLSL 120 shaders.
120 is the common denominator -- valid on macOS 2.1 and on Linux
compatibility contexts alike -- so there is one code path and identical
output on both.

The trade is no shadow mapping (not expressible this simply in 120), so
depth comes from the off-axis geometry and from diffuse shading on the
extruded side walls. :data:`LIT_120` provides the shading.
"""

from __future__ import annotations

from ursina import Vec2, Vec3
from ursina.shader import Shader

__all__ = [
    "UNLIT_120",
    "LIT_120",
    "TEXT_120",
    "install_project_shaders",
    "LIGHT_DIRECTION",
    "FOG_COLOR",
    "FOG_DEPTH_WORLD",
]

LIGHT_DIRECTION = Vec3(0.45, 0.85, -0.35).normalized()
"""World-space direction from a surface *toward* the light.

Mostly from above (world +Y is up out of the glass) and offset to one side,
so the extruded walls of recessed geometry catch light unevenly. That uneven
shading is the depth cue, so a purely top-down light would defeat the point.
"""

FOG_COLOR = Vec3(0.13, 0.18, 0.27)
"""Haze colour for aerial perspective.

Near the window background so deep geometry fades into the backdrop rather
than toward an unrelated hue -- but deliberately a little lighter than it,
so a strong gradient dims recessed surfaces without erasing them."""

FOG_DEPTH_WORLD = 14.0
"""Depth below the glass, in world units (1400 mm), over which fog saturates."""

AMBIENT = 0.5
"""Floor brightness, so faces turned away from the light stay legible
rather than going black.

Raised to 0.5 after the whack-a-mole wells came out near-black: their inner
walls face the axis, so they catch very little directional light, and a
depth gradient on top of that left nothing visible inside the hole."""


# Vertex shader shared in spirit by both programs. Declared separately
# because the lit variant additionally needs normals and the model matrix.
_UNLIT_VERTEX = """#version 120

uniform mat4 p3d_ModelViewProjectionMatrix;
uniform vec2 texture_scale;
uniform vec2 texture_offset;

attribute vec4 p3d_Vertex;
attribute vec2 p3d_MultiTexCoord0;
attribute vec4 p3d_Color;

varying vec2 uvs;
varying vec4 vertex_color;

void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    uvs = (p3d_MultiTexCoord0 * texture_scale) + texture_offset;
    vertex_color = p3d_Color;
}
"""

_UNLIT_FRAGMENT = """#version 120

uniform sampler2D p3d_Texture0;
uniform vec4 p3d_ColorScale;

varying vec2 uvs;
varying vec4 vertex_color;

void main() {
    // Panda binds a white 1x1 texture when the node has none, so this is
    // also correct for untextured geometry such as the grid lines.
    gl_FragColor = texture2D(p3d_Texture0, uvs) * p3d_ColorScale * vertex_color;
}
"""

UNLIT_120 = Shader(
    name="unlit_120",
    language=Shader.GLSL,
    vertex=_UNLIT_VERTEX,
    fragment=_UNLIT_FRAGMENT,
    default_input={
        "texture_scale": Vec2(1, 1),
        "texture_offset": Vec2(0, 0),
    },
)


_LIT_VERTEX = """#version 120

uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;
uniform vec2 texture_scale;
uniform vec2 texture_offset;

attribute vec4 p3d_Vertex;
attribute vec3 p3d_Normal;
attribute vec2 p3d_MultiTexCoord0;
attribute vec4 p3d_Color;

varying vec2 uvs;
varying vec4 vertex_color;
varying vec3 world_normal;
varying vec3 world_pos;

void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    uvs = (p3d_MultiTexCoord0 * texture_scale) + texture_offset;
    vertex_color = p3d_Color;
    world_pos = (p3d_ModelMatrix * p3d_Vertex).xyz;

    // Build the 3x3 rotation part explicitly rather than relying on a
    // mat3(mat4) truncation constructor, which is not portable across all
    // GLSL 120 implementations.
    mat3 model_rotation = mat3(
        p3d_ModelMatrix[0].xyz,
        p3d_ModelMatrix[1].xyz,
        p3d_ModelMatrix[2].xyz
    );
    world_normal = normalize(model_rotation * p3d_Normal);
}
"""

_LIT_FRAGMENT = """#version 120

uniform sampler2D p3d_Texture0;
uniform vec4 p3d_ColorScale;
uniform vec3 light_direction;
uniform float ambient;

// Aerial perspective. Depth below the glass (world +Y is up, so content
// inside the display has negative Y) is mixed toward fog_color. This is the
// strongest altitude cue available after perspective convergence: it is why
// a distant valley floor reads as distant rather than merely small.
// fog_amount defaults to 0 so existing scenes are unchanged.
uniform vec3 fog_color;
uniform float fog_depth;
uniform float fog_amount;

varying vec2 uvs;
varying vec4 vertex_color;
varying vec3 world_normal;
varying vec3 world_pos;

void main() {
    vec4 base = texture2D(p3d_Texture0, uvs) * p3d_ColorScale * vertex_color;

    // Lighting is computed in world space. The camera translates with the
    // viewer but never rotates, so world space keeps the shading fixed to
    // the table rather than sliding around as the head moves.
    float n_dot_l = max(dot(normalize(world_normal), normalize(light_direction)), 0.0);
    float lighting = ambient + (1.0 - ambient) * n_dot_l;

    vec3 lit = base.rgb * lighting;

    float depth_below = max(-world_pos.y, 0.0);
    float fog = clamp(depth_below / max(fog_depth, 0.0001), 0.0, 1.0) * fog_amount;

    gl_FragColor = vec4(mix(lit, fog_color, fog), base.a);
}
"""

LIT_120 = Shader(
    name="lit_120",
    language=Shader.GLSL,
    vertex=_LIT_VERTEX,
    fragment=_LIT_FRAGMENT,
    default_input={
        "texture_scale": Vec2(1, 1),
        "texture_offset": Vec2(0, 0),
        "light_direction": LIGHT_DIRECTION,
        "ambient": AMBIENT,
        "fog_color": FOG_COLOR,
        "fog_depth": FOG_DEPTH_WORLD,
        "fog_amount": 0.0,
    },
)


_TEXT_FRAGMENT = """#version 120

uniform sampler2D p3d_Texture0;
uniform vec4 p3d_ColorScale;

varying vec2 uvs;
varying vec4 vertex_color;

void main() {
    // A font texture carries glyph coverage in its **alpha** channel only;
    // its RGB is not a colour. Sampling it as one -- which the general
    // unlit shader does, since for ordinary geometry that is correct --
    // multiplies every glyph by RGB 0 and draws all text black, whatever
    // colour was asked for. The glyph's colour comes from the vertex
    // colour, which Panda bakes in from TextNode.setTextColor.
    float coverage = texture2D(p3d_Texture0, uvs).a;
    // Threshold with a one-pixel soft edge, so text stays smooth at any
    // size. fwidth is available in GLSL 120.
    float edge = max(fwidth(coverage), 0.0001);
    float alpha = smoothstep(0.5 - edge, 0.5 + edge, coverage);

    vec4 base = vertex_color * p3d_ColorScale;
    gl_FragColor = vec4(base.rgb, base.a * alpha);
}
"""

TEXT_120 = Shader(
    name="text_120",
    language=Shader.GLSL,
    vertex=_UNLIT_VERTEX,
    fragment=_TEXT_FRAGMENT,
    default_input={
        "texture_scale": Vec2(1, 1),
        "texture_offset": Vec2(0, 0),
    },
)


def install_project_shaders() -> None:
    """Make :data:`UNLIT_120` the default for entities, :data:`TEXT_120` for text.

    Call once, immediately after constructing ``Ursina()`` and before any
    entity is created.

    ``Text`` needs separate treatment: it assigns Ursina's GLSL 130
    ``text_shader`` inside its own ``__init__``, so overriding
    ``Entity.default_shader`` alone does not reach it. Patching the class
    attribute it reads is what keeps the HUD from falling back.

    Text also needs its *own* shader rather than the unlit one, because a
    font texture is a coverage map in the alpha channel, not a colour image
    (see :data:`TEXT_120`).
    """
    from ursina import Entity, Text

    Entity.default_shader = UNLIT_120

    # Text.__init__ does `self.shader = text_shader`; redirect that module
    # reference so new Text instances pick up a compilable shader.
    import ursina.text as ursina_text

    ursina_text.text_shader = TEXT_120
    Text.default_shader = TEXT_120

    # Note: two GLSL-130 compile errors still appear in the log on macOS.
    # They come from an Ursina entity built at *import* time (its `camera`
    # is a module-level singleton created before this function can run), so
    # it already holds the old default. Reassigning camera.ui/camera.overlay
    # was tried and did not silence them, so the source is elsewhere in
    # Ursina's startup. They are cosmetic: every project entity renders, as
    # `python -m tabletop.apps.capture --check` verifies. Left alone
    # deliberately -- chasing them risks re-blanking the scene, and
    # suppressing the glgsg error category would hide real shader faults.
