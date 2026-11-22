"""Time Manim mesh building and single-frame rendering for a scene (perf check)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from manim import tempconfig  # noqa: E402

from opto import geometry, schema, video  # noqa: E402

sc = schema.load(sys.argv[1])
n = sum(len(geometry.faces_for(p["shape"], p["size"], 1.0)) * p.get("repeat", {}).get("n", 1) for p in sc.parts)
print("faces@res1", n)
cls = video.build_scene_class(sc)
with tempconfig({"quality": "low_quality", "dry_run": True, "verbosity": "ERROR", "progress_bar": "none"}):
    s = cls()
    s.parts = {}
    t = time.time(); s._build_meshes(); print("build s", round(time.time() - t, 2))
    s._orient_camera()
    for v in s.parts.values():
        s.add(v["all"])
    for k in range(2):
        t = time.time(); s.renderer.camera.capture_mobjects(s.mobjects); print("frame s", round(time.time() - t, 3))
