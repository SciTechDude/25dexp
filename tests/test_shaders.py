"""Guard that no GLSL 130/140 shader ever reaches the driver.

Apple's OpenGL has no GLSL 130 or 140 (see
:mod:`tabletop.render.platform_setup`), and Ursina's own shaders are written
in both. A failed compile is survivable -- Panda falls back to
fixed-function drawing -- which is exactly what makes this worth a test: the
scene still looks roughly right, so the only signal is two error lines in a
log nobody reads, and whatever the fallback draws is not what our shaders
would have drawn.

``development_mode=True`` on purpose: that is when Ursina builds its editor
UI (exit button, cog menu, counters), which is the widest set of entities it
creates on its own.

Runs in a subprocess because Ursina keeps its window, camera and scene as
module-level singletons, so a second instance in one process is unsafe --
and :mod:`tests.test_rig_ursina` already owns the one in this process.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.ursina

pytest.importorskip("ursina", reason="ursina not installed")

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Reports strays as a single line so the assertion can show the offenders.
PROBE = textwrap.dedent(
    """
    from tabletop.render import platform_setup  # noqa: F401  (before ursina)
    from ursina import Ursina, camera, scene
    from tabletop.render.shaders import PROJECT_SHADERS, install_project_shaders

    install_project_shaders()
    app = Ursina(
        size=(320, 200),
        development_mode=True,
        show_ursina_splash=False,
        vsync=False,
        window_type="offscreen",
    )
    for _ in range(3):
        app.step()

    strays = []

    def walk(node, path):
        for child in getattr(node, "children", ()):
            name = getattr(child, "name", None) or type(child).__name__
            shader = getattr(child, "shader", None)
            if shader is not None and shader not in PROJECT_SHADERS:
                strays.append(f"{path}/{name}={getattr(shader, 'name', shader)}")
            walk(child, f"{path}/{name}")

    walk(scene, "scene")
    walk(camera, "camera")
    print("STRAYS:", " ".join(strays) or "none")
    """
)


@pytest.fixture(scope="module")
def probe_output() -> str:
    """Stdout+stderr of one Ursina startup under the project's shaders."""
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"probe failed:\n{output}"
    return output


def test_no_unsupported_glsl_version(probe_output: str) -> None:
    """Panda never reports a shader it cannot compile."""
    offending = [
        line
        for line in probe_output.splitlines()
        if "is not supported" in line or "error occurred while compiling" in line
    ]
    assert not offending, "shader compile errors on startup:\n" + "\n".join(offending)


def test_every_entity_is_on_a_project_shader(probe_output: str) -> None:
    """No entity is left holding one of Ursina's own shaders.

    The compile errors are the symptom; this is the cause, and it fails
    even on a platform where 130 happens to compile.
    """
    strays = next(
        line.removeprefix("STRAYS:").strip()
        for line in probe_output.splitlines()
        if line.startswith("STRAYS:")
    )
    assert strays == "none", f"entities left on a non-project shader: {strays}"
