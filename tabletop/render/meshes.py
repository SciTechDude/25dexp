"""Faceted mesh builders, shared by the demos and the game.

Everything here is **low-poly and flat-shaded on purpose**: hard-edged
facets read as moulded plastic, so the faceted look and the 3D geometry are
the same choice rather than a trade-off.

Two hard-won details are baked into :func:`flat_shaded_mesh`; both cost real
debugging time and neither is obvious:

1. **Faces must not share vertices.** OpenGL stores one normal per *vertex*,
   so a vertex shared between faces can only carry one compromise normal.
   On a cone every side face meets at the apex, so sharing it averages their
   normals and the facets blur into a smooth dome.
2. **Ursina's ``generate_normals(smooth=False)`` does not produce per-face
   normals** even with unshared vertices — every face came back pointing
   straight up and solids rendered as single flat silhouettes. Normals are
   therefore computed here by explicit cross product.
"""

from __future__ import annotations

import math

from collections.abc import Callable, Sequence

from ursina import Mesh, Vec3

from tabletop.render.mapping import table_to_world, world_to_table

__all__ = [
    "flat_shaded_mesh",
    "face_normal",
    "extruded_polygon_mesh",
    "tapered_pyramid_mesh",
    "revolved_profile_mesh",
    "well_profile",
    "mole_profile",
    "field_patch_mesh",
    "disc_mesh",
    "ring_mesh",
]

Point3 = tuple[float, float, float]


def face_normal(
    face: list[Vec3],
    reference_point: Point3 | None = None,
    outward: bool = True,
) -> Vec3:
    """Unit normal of a planar face.

    When ``reference_point`` is given the normal is flipped to point away
    from it (``outward=True``) or toward it (``outward=False``). That removes
    any dependence on getting winding order right in every face, which is
    worth a lot when generating geometry procedurally.

    ``outward=False`` is for surfaces seen from *inside* — the wall of a
    hole, for instance, where the visible side faces the axis.
    """
    ax, ay, az = face[0][0], face[0][1], face[0][2]
    bx, by, bz = face[1][0], face[1][1], face[1][2]
    cx, cy, cz = face[2][0], face[2][1], face[2][2]

    e1 = (bx - ax, by - ay, bz - az)
    e2 = (cx - ax, cy - ay, cz - az)
    nx = e1[1] * e2[2] - e1[2] * e2[1]
    ny = e1[2] * e2[0] - e1[0] * e2[2]
    nz = e1[0] * e2[1] - e1[1] * e2[0]

    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-12:
        # Degenerate face. Point it up rather than emit a zero normal, which
        # would make the lighting term meaningless.
        return Vec3(0, 1, 0)
    nx, ny, nz = nx / length, ny / length, nz / length

    if reference_point is not None:
        face_centre = (
            sum(p[0] for p in face) / len(face),
            sum(p[1] for p in face) / len(face),
            sum(p[2] for p in face) / len(face),
        )
        away = (
            face_centre[0] - reference_point[0],
            face_centre[1] - reference_point[1],
            face_centre[2] - reference_point[2],
        )
        facing_away = nx * away[0] + ny * away[1] + nz * away[2] > 0
        if facing_away != outward:
            nx, ny, nz = -nx, -ny, -nz

    return Vec3(nx, ny, nz)


def flat_shaded_mesh(
    faces: list[list[Vec3]],
    orient_outward: bool = True,
    reference_point: Point3 | None = None,
    uv_of: Callable[[Vec3], tuple[float, float]] | None = None,
) -> Mesh:
    """Build a faceted mesh from polygon faces, one flat normal per face.

    ``reference_point`` defaults to the centroid of all supplied points.
    Pass ``orient_outward=False`` for geometry viewed from the inside.

    ``uv_of`` maps a world-space vertex to texture coordinates. Procedurally
    generated meshes have no UVs at all unless this is supplied, so a
    texture applied to one samples a single undefined point and the surface
    comes out flat-coloured -- which looks like the texture failed to load.
    """
    vertices: list[Vec3] = []
    triangles: list[int] = []
    normals: list[Vec3] = []
    uvs: list[tuple[float, float]] = []

    all_points = [p for face in faces for p in face]
    if not all_points:
        raise ValueError("no faces supplied")

    centre = reference_point or (
        sum(p[0] for p in all_points) / len(all_points),
        sum(p[1] for p in all_points) / len(all_points),
        sum(p[2] for p in all_points) / len(all_points),
    )

    for face in faces:
        if len(face) < 3:
            raise ValueError(f"face needs at least 3 points, got {len(face)}")
        normal = face_normal(face, centre, outward=orient_outward)

        # Fan-triangulate, duplicating vertices so each triangle owns this
        # face's flat normal.
        for i in range(1, len(face) - 1):
            start = len(vertices)
            trio = [face[0], face[i], face[i + 1]]
            vertices.extend(trio)
            normals.extend([normal, normal, normal])
            triangles.extend([start, start + 1, start + 2])
            if uv_of is not None:
                uvs.extend(uv_of(v) for v in trio)

    return Mesh(
        vertices=vertices,
        triangles=triangles,
        normals=normals,
        uvs=uvs or None,
        mode="triangle",
    )


def extruded_polygon_mesh(
    points_mm: list[tuple[float, float]],
    top_z_mm: float,
    bottom_z_mm: float,
) -> Mesh:
    """Extrude a 2D polygon between two table heights into a closed solid."""
    if len(points_mm) < 3:
        raise ValueError("need at least 3 points to extrude a polygon")

    count = len(points_mm)
    top = [Vec3(*table_to_world(x, y, top_z_mm)) for x, y in points_mm]
    bottom = [Vec3(*table_to_world(x, y, bottom_z_mm)) for x, y in points_mm]

    faces: list[list[Vec3]] = [
        [top[0]] + [top[i] for i in range(count - 1, 0, -1)],
        list(bottom),
    ]
    for i in range(count):
        nxt = (i + 1) % count
        faces.append([top[i], top[nxt], bottom[nxt], bottom[i]])

    return flat_shaded_mesh(faces)


def tapered_pyramid_mesh(
    base_points_mm: list[tuple[float, float]],
    apex_xy_mm: tuple[float, float],
    apex_z_mm: float,
    base_z_mm: float,
) -> Mesh:
    """A pyramid whose tip-to-base axis runs along Z.

    The taper is what makes it read as receding: a constant-section prism
    has walls parallel to the view axis, so looking straight down you see
    almost none of them.
    """
    if len(base_points_mm) < 3:
        raise ValueError("need at least 3 base points to build a pyramid")

    count = len(base_points_mm)
    apex = Vec3(*table_to_world(apex_xy_mm[0], apex_xy_mm[1], apex_z_mm))
    ring = [Vec3(*table_to_world(x, y, base_z_mm)) for x, y in base_points_mm]

    faces: list[list[Vec3]] = [
        [apex, ring[(i + 1) % count], ring[i]] for i in range(count)
    ]
    # Cap only the deeper end; a cap at the glass would be a lid hiding
    # every inner wall.
    if base_z_mm < apex_z_mm:
        faces.append(list(ring))

    return flat_shaded_mesh(faces)


def revolved_profile_mesh(
    profile: list[tuple[float, float]],
    centre_xy_mm: tuple[float, float] = (0.0, 0.0),
    segments: int = 16,
    orient_outward: bool = True,
) -> Mesh:
    """Revolve a 2D profile around the Z axis into a surface of revolution.

    ``profile`` is a list of ``(radius_mm, z_mm)`` points, ordered along the
    axis. A radius of exactly 0 closes that end with a fan of triangles, so
    domes, cones and flat caps all fall out of the same representation.

    One builder covers both shapes this game needs — a tapered hole and a
    mole — which keeps the geometry code small and means the faceting looks
    consistent between them.

    ``segments`` is deliberately low (16 by default): visible facets are the
    desired look, and they also make the depth gradient easier to read than
    a smooth surface would.
    """
    if len(profile) < 2:
        raise ValueError("a profile needs at least 2 points")
    if segments < 3:
        raise ValueError("need at least 3 segments to revolve")

    cx, cy = centre_xy_mm

    def point(radius: float, z_mm: float, index: int) -> Vec3:
        angle = 2.0 * math.pi * (index % segments) / segments
        return Vec3(
            *table_to_world(
                cx + radius * math.cos(angle),
                cy + radius * math.sin(angle),
                z_mm,
            )
        )

    faces: list[list[Vec3]] = []

    for i in range(len(profile) - 1):
        r0, z0 = profile[i]
        r1, z1 = profile[i + 1]

        for s in range(segments):
            if r0 <= 1e-9 and r1 <= 1e-9:
                continue  # degenerate band on the axis
            if r0 <= 1e-9:
                # Cone/fan closing toward the previous point on the axis.
                faces.append([point(0.0, z0, s), point(r1, z1, s), point(r1, z1, s + 1)])
            elif r1 <= 1e-9:
                faces.append([point(r0, z0, s), point(r0, z0, s + 1), point(0.0, z1, s)])
            else:
                faces.append(
                    [
                        point(r0, z0, s),
                        point(r0, z0, s + 1),
                        point(r1, z1, s + 1),
                        point(r1, z1, s),
                    ]
                )

    # Orient relative to the axis mid-height so "inward" means "toward the
    # axis", which is what the inside of a hole needs.
    z_values = [z for _, z in profile]
    reference = table_to_world(cx, cy, (min(z_values) + max(z_values)) / 2.0)

    return flat_shaded_mesh(
        faces, orient_outward=orient_outward, reference_point=reference
    )


def well_profile(radius_mm: float, depth_mm: float) -> list[tuple[float, float]]:
    """Profile for a mole hole: a tapered shaft with a floor.

    Tapering inward with depth (rather than a straight cylinder) matters for
    the same reason the demo's pyramid beats a prism: straight walls are
    parallel to the view axis and nearly invisible from directly overhead,
    while sloped walls catch light and foreshorten, so the hole reads as
    having depth.
    """
    return [
        (radius_mm, 0.0),
        (radius_mm * 0.88, -depth_mm * 0.45),
        (radius_mm * 0.72, -depth_mm),
        (0.0, -depth_mm),
    ]


def mole_profile(radius_mm: float, height_mm: float) -> list[tuple[float, float]]:
    """Profile for a mole: a rounded-top body on a flat base."""
    return [
        (0.0, height_mm),
        (radius_mm * 0.42, height_mm * 0.93),
        (radius_mm * 0.76, height_mm * 0.74),
        (radius_mm, height_mm * 0.45),
        (radius_mm, 0.0),
        (0.0, 0.0),
    ]


def field_patch_mesh(
    cell_width_mm: float,
    cell_height_mm: float,
    hole_radius_mm: float,
    centre_xy_mm: tuple[float, float] = (0.0, 0.0),
    z_mm: float = 0.0,
    segments: int = 18,
    field_size_mm: tuple[float, float] | None = None,
    texture_repeat: float = 1.0,
) -> Mesh:
    """A rectangular patch of ground with a circular hole punched in it.

    ``field_size_mm`` enables texture coordinates computed in *whole-field*
    space rather than per patch, so a ground texture runs continuously
    across the tiled patches instead of restarting at every cell and
    showing a visible grid of seams. ``texture_repeat`` tiles it.

    One patch per hole, sized to its grid cell, so the patches tile into a
    continuous field. This exists because a plain field quad is opaque and
    sits *above* the wells: it occludes every hole interior, leaving only a
    sliver of rim visible. Depth-sorting cannot fix that -- the surface
    genuinely has to have holes in it.

    The ring is built by walking the circle and, for each step, connecting to
    the matching point on the cell's rectangular boundary. The boundary point
    for an angle is found by scaling out to whichever edge is hit first,
    which keeps the four corners square and the seams between patches exact.
    """
    if hole_radius_mm <= 0:
        raise ValueError("hole radius must be positive")
    half_w = cell_width_mm / 2.0
    half_h = cell_height_mm / 2.0
    if hole_radius_mm >= min(half_w, half_h):
        raise ValueError(
            f"hole radius {hole_radius_mm} does not fit in a "
            f"{cell_width_mm}x{cell_height_mm} mm cell"
        )

    cx, cy = centre_xy_mm

    def circle_point(angle: float) -> tuple[float, float]:
        return (
            cx + hole_radius_mm * math.cos(angle),
            cy + hole_radius_mm * math.sin(angle),
        )

    def boundary_point(angle: float) -> tuple[float, float]:
        dx, dy = math.cos(angle), math.sin(angle)
        # Scale to the nearer edge so the rectangle's corners stay square.
        scale = min(
            half_w / abs(dx) if abs(dx) > 1e-9 else float("inf"),
            half_h / abs(dy) if abs(dy) > 1e-9 else float("inf"),
        )
        return (cx + dx * scale, cy + dy * scale)

    # The sample angles must include the cell's four corner directions.
    # Uniform sampling alone cuts a triangle off every corner whenever a
    # corner falls between two samples, and the patches then fail to tile:
    # neighbouring cells leave a diamond-shaped hole at each shared corner.
    # How bad it looks depends on the cell's aspect ratio, so the gaps
    # appear and disappear as the grid is re-tuned.
    corner_angles = [
        math.atan2(sy * half_h, sx * half_w) % (2.0 * math.pi)
        for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1))
    ]
    uniform = [2.0 * math.pi * s / segments for s in range(segments)]
    angles = sorted(set(uniform) | set(corner_angles))
    # Close the ring by repeating the first angle a full turn on.
    angles.append(angles[0] + 2.0 * math.pi)

    faces: list[list[Vec3]] = []
    for a, b in zip(angles, angles[1:]):
        ci = circle_point(a)
        cj = circle_point(b)
        bi = boundary_point(a)
        bj = boundary_point(b)
        faces.append(
            [
                Vec3(*table_to_world(ci[0], ci[1], z_mm)),
                Vec3(*table_to_world(bi[0], bi[1], z_mm)),
                Vec3(*table_to_world(bj[0], bj[1], z_mm)),
                Vec3(*table_to_world(cj[0], cj[1], z_mm)),
            ]
        )

    def make_uv(field_w: float, field_h: float):
        def uv_of(vertex: Vec3) -> tuple[float, float]:
            # world -> table mm -> normalised whole-field position.
            x_mm, y_mm, _ = world_to_table(vertex[0], vertex[1], vertex[2])
            return (
                (x_mm / field_w + 0.5) * texture_repeat,
                (y_mm / field_h + 0.5) * texture_repeat,
            )

        return uv_of

    uv_of = make_uv(*field_size_mm) if field_size_mm is not None else None

    # Reference well below the patch so "outward" resolves to "facing up".
    return flat_shaded_mesh(
        faces,
        orient_outward=True,
        reference_point=table_to_world(cx, cy, z_mm - 500.0),
        uv_of=uv_of,
    )


def ring_mesh(
    outer_width_mm: float,
    outer_height_mm: float,
    cross_section: Sequence[tuple[float, float]],
) -> Mesh:
    """A rectangular ring around the playfield, from a cross-section.

    Builds both pieces of the table's frame: the raised bezel and the flat
    score band it encloses, which differ only in their profile (see
    :class:`tabletop.core.layout.TableLayout`).

    ``cross_section`` is that profile, as ``(inset_from_outer_edge_mm,
    z_mm)`` points ordered from the outer edge inward. Each consecutive pair
    becomes a band of four quads, one per side of the table.

    The corners mitre themselves. Insetting a centred rectangle by ``d``
    moves each corner along its own diagonal, so the corner point of one
    ring and the corner point of the next already lie on the mitre line --
    joining them with a single quad per side produces the clean 45-degree
    seam a moulded frame has, with no corner geometry to get wrong.

    Normals are resolved against a reference point far *below* the table, so
    every face comes out pointing upward-ish rather than some up and some
    down. That matters for the bezel: it is lit from above like a real
    moulding, and its two chamfers shading differently from its flat top is
    what makes it read as a solid raised edge rather than a painted border.
    """
    if len(cross_section) < 2:
        raise ValueError("a ring cross-section needs at least 2 points")

    rings: list[list[Vec3]] = []
    for inset, z_mm in cross_section:
        width = outer_width_mm - 2.0 * inset
        height = outer_height_mm - 2.0 * inset
        if width <= 0 or height <= 0:
            raise ValueError(
                f"inset {inset} mm leaves no rectangle in "
                f"{outer_width_mm}x{outer_height_mm} mm"
            )
        half_w, half_h = width / 2.0, height / 2.0
        rings.append(
            [
                Vec3(*table_to_world(x, y, z_mm))
                for x, y in (
                    (-half_w, -half_h),
                    (half_w, -half_h),
                    (half_w, half_h),
                    (-half_w, half_h),
                )
            ]
        )

    faces: list[list[Vec3]] = []
    for inner, outer in zip(rings, rings[1:]):
        for i in range(4):
            j = (i + 1) % 4
            faces.append([inner[i], inner[j], outer[j], outer[i]])

    return flat_shaded_mesh(
        faces,
        orient_outward=True,
        reference_point=table_to_world(0.0, 0.0, -2000.0),
    )


def disc_mesh(
    radius_mm: float,
    centre_xy_mm: tuple[float, float] = (0.0, 0.0),
    z_mm: float = 0.0,
    segments: int = 16,
) -> Mesh:
    """A flat horizontal disc, normal facing up. Used for cast shadows."""
    return revolved_profile_mesh(
        [(radius_mm, z_mm), (0.0, z_mm)],
        centre_xy_mm=centre_xy_mm,
        segments=segments,
        orient_outward=True,
    )
