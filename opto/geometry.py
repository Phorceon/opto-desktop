"""Triangle/quad meshes for OptoScene primitives, in the part's local y-up frame.

Each function returns a list of faces; a face is a list of 3 or 4 points [x,y,z].
`res` scales the tessellation (1.0 = normal). Shared by the Manim compiler and the evals.
"""

from __future__ import annotations

import math

Face = list[list[float]]


def _seg(n: float, lo: int = 6) -> int:
    return max(lo, int(round(n)))


def _grid(fn, nu: int, nv: int, u0=0.0, u1=1.0, v0=0.0, v1=1.0) -> list[Face]:
    faces = []
    for i in range(nu):
        for j in range(nv):
            a, b = u0 + (u1 - u0) * i / nu, u0 + (u1 - u0) * (i + 1) / nu
            c, d = v0 + (v1 - v0) * j / nv, v0 + (v1 - v0) * (j + 1) / nv
            faces.append([fn(a, c), fn(b, c), fn(b, d), fn(a, d)])
    return faces


def _disc(r: float, y: float, n: int, flip: bool = False) -> list[Face]:
    faces = []
    for i in range(n):
        a, b = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        p, q = [r * math.cos(a), y, r * math.sin(a)], [r * math.cos(b), y, r * math.sin(b)]
        faces.append([[0, y, 0], q, p] if flip else [[0, y, 0], p, q])
    return faces


def _annulus(ro: float, ri: float, y: float, n: int) -> list[Face]:
    faces = []
    for i in range(n):
        a, b = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        faces.append([[ri * math.cos(a), y, ri * math.sin(a)], [ro * math.cos(a), y, ro * math.sin(a)],
                      [ro * math.cos(b), y, ro * math.sin(b)], [ri * math.cos(b), y, ri * math.sin(b)]])
    return faces


def box(w: float, h: float, d: float, res: float = 1.0) -> list[Face]:
    n = _seg(3 * res, 2)
    hw, hh, hd = w / 2, h / 2, d / 2
    faces: list[Face] = []
    faces += _grid(lambda u, v: [hw, u, v], n, n, -hh, hh, -hd, hd)
    faces += _grid(lambda u, v: [-hw, u, v], n, n, -hh, hh, -hd, hd)
    faces += _grid(lambda u, v: [u, hh, v], n, n, -hw, hw, -hd, hd)
    faces += _grid(lambda u, v: [u, -hh, v], n, n, -hw, hw, -hd, hd)
    faces += _grid(lambda u, v: [u, v, hd], n, n, -hw, hw, -hh, hh)
    faces += _grid(lambda u, v: [u, v, -hd], n, n, -hw, hw, -hh, hh)
    return faces


def wedge(w: float, h: float, d: float, res: float = 1.0) -> list[Face]:
    n = _seg(3 * res, 2)
    a, b, c = [-w / 2, -h / 2], [w / 2, -h / 2], [-w / 2, h / 2]
    faces: list[Face] = []
    for z in (-d / 2, d / 2):
        faces.append([[*a, z], [*b, z], [*c, z]])

    def side(p, q):
        return _grid(lambda u, v: [p[0] + (q[0] - p[0]) * u, p[1] + (q[1] - p[1]) * u, v], n, n, 0, 1, -d / 2, d / 2)

    faces += side(a, b) + side(b, c) + side(c, a)
    return faces


def cylinder(rt: float, rb: float, h: float, res: float = 1.0) -> list[Face]:
    n = _seg(20 * res, 8)
    rings = _seg(2 * res, 1)

    def f(u, v):
        r = rb + (rt - rb) * v
        a = 2 * math.pi * u
        return [r * math.cos(a), -h / 2 + h * v, r * math.sin(a)]

    faces = _grid(f, n, rings)
    if rt > 1e-4:
        faces += _disc(rt, h / 2, n)
    if rb > 1e-4:
        faces += _disc(rb, -h / 2, n, flip=True)
    return faces


def cone(r: float, h: float, res: float = 1.0) -> list[Face]:
    return cylinder(0.0, r, h, res)


def ellipsoid(rx: float, ry: float, rz: float, res: float = 1.0) -> list[Face]:
    nu, nv = _seg(20 * res, 8), _seg(10 * res, 5)

    def f(u, v):
        a, b = 2 * math.pi * u, math.pi * v
        return [rx * math.sin(b) * math.cos(a), -ry * math.cos(b), rz * math.sin(b) * math.sin(a)]

    return _grid(f, nu, nv)


def sphere(r: float, res: float = 1.0) -> list[Face]:
    return ellipsoid(r, r, r, res)


def capsule(r: float, length: float, res: float = 1.0) -> list[Face]:
    nu, nv = _seg(20 * res, 8), _seg(5 * res, 3)
    faces = cylinder(r, r, length, res)
    faces = [f for f in faces if not all(abs(abs(p[1]) - length / 2) < 1e-9 for p in f)]  # drop caps

    def cap(sign):
        def f(u, v):
            a, b = 2 * math.pi * u, (math.pi / 2) * v
            return [r * math.cos(b) * math.cos(a), sign * (length / 2 + r * math.sin(b)), r * math.cos(b) * math.sin(a)]
        return _grid(f, nu, nv)

    return faces + cap(1) + cap(-1)


def torus(R: float, r: float, res: float = 1.0) -> list[Face]:
    nu, nv = _seg(28 * res, 10), _seg(10 * res, 6)

    def f(u, v):
        a, b = 2 * math.pi * u, 2 * math.pi * v
        return [(R + r * math.cos(b)) * math.cos(a), r * math.sin(b), (R + r * math.cos(b)) * math.sin(a)]

    return _grid(f, nu, nv)


def tube(ro: float, ri: float, h: float, res: float = 1.0) -> list[Face]:
    n = _seg(20 * res, 8)
    faces = [f for f in cylinder(ro, ro, h, res) if not all(abs(abs(p[1]) - h / 2) < 1e-9 for p in f)]
    faces += [f for f in cylinder(ri, ri, h, res) if not all(abs(abs(p[1]) - h / 2) < 1e-9 for p in f)]
    faces += _annulus(ro, ri, h / 2, n) + _annulus(ro, ri, -h / 2, n)
    return faces


def _ear_clip(poly: list[list[float]]) -> list[tuple[int, int, int]]:
    """Triangulate a simple polygon (either winding)."""
    n = len(poly)
    if n < 3:
        return []
    area = sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))
    idx = list(range(n)) if area > 0 else list(range(n))[::-1]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def inside(p, a, b, c):
        return cross(a, b, p) >= 0 and cross(b, c, p) >= 0 and cross(c, a, p) >= 0

    tris, guard = [], 0
    while len(idx) > 3 and guard < 4 * n * n:
        guard += 1
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = poly[i0], poly[i1], poly[i2]
            if cross(a, b, c) <= 1e-12:
                continue
            if any(inside(poly[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2))
            idx.pop(k)
            break
        else:
            break
    if len(idx) == 3:
        tris.append(tuple(idx))
    if not tris:  # degenerate/self-intersecting: fall back to a fan
        tris = [(0, i, i + 1) for i in range(1, n - 1)]
    return tris


def panel(points: list[list[float]], t: float, res: float = 1.0) -> list[Face]:
    pts = [list(p) for p in points]
    if len(pts) > 3 and abs(pts[0][0] - pts[-1][0]) < 1e-9 and abs(pts[0][1] - pts[-1][1]) < 1e-9:
        pts = pts[:-1]
    faces: list[Face] = []
    for a, b, c in _ear_clip(pts):
        for z in (-t / 2, t / 2):
            faces.append([[*pts[a], z], [*pts[b], z], [*pts[c], z]])
    n = len(pts)
    for i in range(n):
        p, q = pts[i], pts[(i + 1) % n]
        faces.append([[*p, -t / 2], [*q, -t / 2], [*q, t / 2], [*p, t / 2]])
    return faces


def lathe(points: list[list[float]], res: float = 1.0) -> list[Face]:
    n = _seg(24 * res, 10)
    faces: list[Face] = []
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        for j in range(len(points) - 1):
            (r0, y0), (r1, y1) = points[j], points[j + 1]
            p00 = [r0 * math.cos(a0), y0, r0 * math.sin(a0)]
            p01 = [r0 * math.cos(a1), y0, r0 * math.sin(a1)]
            p10 = [r1 * math.cos(a0), y1, r1 * math.sin(a0)]
            p11 = [r1 * math.cos(a1), y1, r1 * math.sin(a1)]
            if r0 < 1e-6 and r1 < 1e-6:
                continue
            if r0 < 1e-6:
                faces.append([p00, p11, p10])
            elif r1 < 1e-6:
                faces.append([p00, p01, p10])
            else:
                faces.append([p00, p01, p11, p10])
    return faces


def faces_for_part(p: dict, res: float = 1.0) -> list[Face]:
    if p["shape"] == "panel" and p.get("points"):
        return panel(p["points"], p["size"][0], res)
    if p["shape"] == "lathe" and p.get("points"):
        return lathe(p["points"], res)
    return faces_for(p["shape"], p["size"], res)


def faces_for(shape: str, size: list[float], res: float = 1.0) -> list[Face]:
    if shape == "box":
        return box(*size, res=res)
    if shape == "wedge":
        return wedge(*size, res=res)
    if shape == "cylinder":
        return cylinder(*size, res=res)
    if shape == "cone":
        return cone(*size, res=res)
    if shape == "sphere":
        return sphere(*size, res=res)
    if shape == "ellipsoid":
        return ellipsoid(*size, res=res)
    if shape == "capsule":
        return capsule(*size, res=res)
    if shape == "torus":
        return torus(*size, res=res)
    if shape == "tube":
        return tube(*size, res=res)
    return box(1, 1, 1, res=res)
