
from pathlib import Path
import hashlib
import json
import sys
import FreeCAD as App
import Part
import Mesh
import MeshPart

HERE = Path(__file__).resolve().parent
PRINT = HERE / "print"
V = App.Vector
L, W, H = 68, 64, 13
FLOOR, WALL, FACE = 1.6, 1.6, 1.6
SEAM = H - FACE
LID_SCREWS = [(4, 4.5), (26, 4.5), (47, 36.9), (4, 60), (64, 60)]
CLIP_SCREWS = [(17, 31), (24, 31)]
REC = (56.5, 45)
MIC = (16.2, 11.1)


def box(x, y, z, length, width, height):
    return Part.makeBox(length, width, height, V(x, y, z))


def cylinder(x, y, z, radius, height):
    return Part.makeCylinder(radius, height, V(x, y, z))


def rounded(x, y, z, length, width, height, radius):
    s = box(x, y, z, length, width, height)
    vertical = [e for e in s.Edges if e.BoundBox.ZLength > height - 0.001]
    return s.makeFillet(radius, vertical)


def fuse(shapes):
    return shapes[0].multiFuse(shapes[1:]).removeSplitter()


def cut(shape, cutters):
    for tool in cutters:
        shape = shape.cut(tool)
    return shape.removeSplitter()


def read_step(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != STEP_SHA:
        raise ValueError(
            "Different vendor STEP revision. Recheck orientation and body indices."
        )
    original = Part.read(str(path))
    rot = App.Rotation(V(0, 1, 1), 180)
    solid = original.Solids
    placed = []
    for s in solid:
        t = s.copy()
        t.Placement = App.Placement(V(15.6, 24, 2.75), rot).multiply(t.Placement)
        placed.append(t)
    return placed


def bounds(s):
    b = s.optimalBoundingBox()
    return [
        round(getattr(b, k), 4)
        for k in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax")
    ]


def feature(doc, name, label, shape):
    obj = doc.addObject("Part::Feature", name)
    obj.Label, obj.Shape = label, shape
    return obj


def build():
    tray = rounded(0, 0, 0, L, W, SEAM, 3.6).cut(
        rounded(WALL, WALL, FLOOR, L - 2 * WALL, W - 2 * WALL, SEAM, 2)
    )
    adds = [tray]
    cuts = [box(-1, 10.5, 2.0, 4, 14.8, 6.1), box(-1, 10.5, 8.1, 4, 14.8, 3.5)]
    for x in (4.8, 22.2):
        for y in (9.08, 25.95):
            adds.append(box(x, y, FLOOR, 1.9, 0.76, 0.90))
    for y in (9.15, 25.92):
        adds += [
            box(24.58, y, FLOOR, 1.20, 0.78, 3.7),
            box(23.70, y, 4.25, 1.65, 0.78, 1.1),
        ]
    for y in (7.8, 27.13):
        adds.append(box(9, y, FLOOR, 7, 1, 2.3))
    for y in (9.5, 25.0):
        adds.append(box(2.17, y, FLOOR, 0.86, 0.95, 2.5))
    adds += [
        box(28.5, 2.0, FLOOR, 37.2, 1, 2),
        box(28.5, 34.7, FLOOR, 37.2, 1, 2),
        box(27.5, 2.4, FLOOR, 1.2, 9.6, 2),
        box(27.5, 25, FLOOR, 1.2, 10.0, 2),
        box(65.7, 2.4, FLOOR, 1, 32.6, 2),
    ]
    for x, y in LID_SCREWS:
        adds.append(cylinder(x, y, FLOOR, 2.65, SEAM - FLOOR))
        cuts.append(cylinder(x, y, 5.3, 0.85, 7))
    for x, y in CLIP_SCREWS:
        adds.append(cylinder(x, y, FLOOR, 2.65, 3.4))
        cuts.append(cylinder(x, y, -0.1, 0.85, 4.1))
    base = cut(fuse(adds), cuts)
    lid = rounded(0, 0, SEAM, L, W, FACE, 3.6)
    adds = [
        lid,
        box(10, 1.9, 10.2, 10, 0.9, 1.4),
        box(46, 61.2, 10.2, 9, 0.9, 1.4),
        box(65.2, 45, 10.2, 0.9, 10, 1.4),
    ]
    for y in (9.13, 25.97):
        adds.append(box(4.65, y, 4.25, 2, 0.76, SEAM - 4.25 + 0.05))
    for x in (50.5, 62.5):
        adds.append(cylinder(x, 45, 8.4, 2.4, SEAM - 8.4 + 0.1))
    cuts = [
        box(-0.1, 11.0, 11.32, 15.9, 12.2, 0.53),
        cylinder(*REC, 11.5, 2.65, 2),
        box(53.15, 41.65, 10.8, 6.7, 6.7, 1.1),
        cylinder(57.5, 53, 11.2, 1.60, 3),
    ]
    for x in (50.5, 62.5):
        cuts.append(cylinder(x, 45, 8.3, 0.85, 3.85))
    for x, y in LID_SCREWS:
        cuts += [
            cylinder(x, y, SEAM - 0.1, 1.15, FACE + 0.2),
            Part.makeCone(1.15, 2.25, 1.10, V(x, y, H - 1.10)),
        ]
    lid = cut(fuse(adds), cuts)
    profile = [
        (27.3, 0),
        (34, 0),
        (34, -2.4),
        (28.1, -2.4),
        (26.4, -3.9),
        (9, -3.9),
        (6, -3.95),
        (4.2, -4.7),
        (3.7, -3.3),
        (6.8, -1.7),
        (8.4, -0.25),
        (10.3, -0.25),
        (12, -2.05),
        (25.3, -2.05),
        (27.3, -0.7),
    ]
    points = [V(14, y, z) for y, z in profile]
    clip = Part.Face(Part.makePolygon(points + [points[0]])).extrude(V(13, 0, 0))
    clip = cut(clip, [cylinder(x, y, -3, 1.15, 4) for x, y in CLIP_SCREWS])
    return base, lid, clip


def export_stl(shape, name, rot):
    copy = shape.copy()
    if rot:
        copy.rotate(V(), *rot)
    b = copy.optimalBoundingBox()
    copy.translate(V(-b.XMin, -b.YMin, -b.ZMin))
    target = PRINT / (name + ".stl")
    MeshPart.meshFromShape(
        Shape=copy, LinearDeflection=0.03, AngularDeflection=0.18, Relative=False
    ).write(str(target))
    m = Mesh.Mesh(str(target))
    assert m.isSolid() and abs(m.BoundBox.ZMin) < 1e-4
    return {
        "triangles": m.CountFacets,
        "size_mm": [
            round(v, 3)
            for v in (m.BoundBox.XLength, m.BoundBox.YLength, m.BoundBox.ZLength)
        ],
    }


def main():
    board = read_step(Path(sys.argv[1]))
    doc = App.newDocument("ClipMicP1")
    base, lid_blank, clip = build()
    blank = feature(doc, "LidBlank", "Face before acoustic drilling", lid_blank)
    bore = doc.addObject("Part::Cylinder", "AcousticBore")
    bore.Label = "Sound aperture - adjust XY and radius after sample fit"
    bore.Radius, bore.Height = 2.5, 4
    bore.Placement = App.Placement(V(*MIC, 10), App.Rotation())
    lid_feature = doc.addObject("Part::Cut", "Lid")
    lid_feature.Base, lid_feature.Tool = blank, bore
    lid_feature.Label = "02 Face / adjustable sound port"
    doc.recompute()
    blank.Visibility = bore.Visibility = False
    lid = lid_feature.Shape
    solids = {"Tray": base, "Lid": lid, "Clip": clip}
    for name, shape in solids.items():
        assert shape.isValid() and len(shape.Solids) == 1, name
        if name != "Lid":
            feature(
                doc,
                name,
                {
                    "Tray": "01 Tray / board cradle",
                    "Lid": "02 Face / REC and microphone",
                    "Clip": "03 Removable pocket clip",
                }[name],
                shape,
            )
    micref = box(MIC[0] - 1.325, MIC[1] - 0.8, 7.93, 2.65, 3.5, 0.94)
    pack = box(29.1, 3.6, 1.85, 36, 30.5, 4.3)
    antenna = box(8, 42, 1.75, 37.4, 17.5, 0.2)
    drills = [cylinder(x, 45, 6.7, 1.15, 2) for x in (50.5, 62.5)]
    drills += [
        cylinder(x, y, 6.7, 0.5, 2) for x in (53.25, 59.75) for y in (42.75, 47.25)
    ]
    carrier = cut(box(47.5, 40, 6.8, 18, 10, 1.6), drills)
    switch = fuse([box(53.5, 42, 8.4, 6, 6, 3.4), cylinder(*REC, 11.80, 1.75, 0.90)])
    refs = {
        "BasePCB": board[37],
        "ExpansionPCB": board[71],
        "USB": board[18],
        "Card": board[72],
        "PackMax": pack,
        "FpcReserve": antenna,
        "ConnectorBay": box(11, 35, 2, 10, 5, 4),
        "MicReserve": micref,
        "RecCarrier": carrier,
        "RecSwitchEnvelope": switch,
    }
    grp = doc.addObject("App::DocumentObjectGroup", "Reference")
    for name, s in refs.items():
        if name in ("BasePCB", "ExpansionPCB", "USB", "Card"):
            a, b, c, d, e, f = bounds(s)
            s = box(a, b, c, d - a, e - b, f - c)
        grp.addObject(feature(doc, name, name + " / envelope", s))
    checks = {}
    for n, s in solids.items():
        for m, t in refs.items():
            overlap = s.common(t).Volume
            assert overlap < 0.001, (n, m, overlap)
        for m, t in solids.items():
            if n != m:
                overlap = s.common(t).Volume
                assert overlap < 0.001, (n, m, overlap)
        collisions = [
            (i, round(s.common(t).Volume, 5))
            for i, t in enumerate(board[:99])
            if s.BoundBox.intersect(t.BoundBox)
        ]
        assert all(v < 0.001 for i, v in collisions), (
            n,
            [p for p in collisions if p[1] >= 0.001],
        )
        checks[n] = {
            "valid": True,
            "solid_count": len(s.Solids),
            "vendor_solids_checked": 99,
            "bounds": bounds(s),
        }
    grp.Visibility = False
    for o in grp.Group:
        o.Visibility = False
    acoustic_ray = cylinder(*MIC, 8.88, 0.35, 4.5)
    for ref_shape in board[:99] + [lid, base]:
        assert acoustic_ray.common(ref_shape).Volume < 0.001
    doc.recompute()
    doc.saveAs(str(HERE / "ClipMic-P1.FCStd"))
    App.closeDocument(doc.Name)
    reopened = App.openDocument(str(HERE / "ClipMic-P1.FCStd"))
    for n in solids:
        assert reopened.getObject(n).Shape.isValid()
    App.closeDocument(reopened.Name)
    stl = {
        n: export_stl(s, n, r)
        for n, s, r in [
            ("Tray", base, None),
            ("Lid", lid, (V(1, 0, 0), 180)),
            ("Clip", clip, (V(0, 1, 0), 90)),
        ]
    }
    report = {
        "FreeCAD": ".".join(App.Version()[:3]),
        "source_sha256": STEP_SHA,
        "source_solids": len(board),
        "removed_camera_indices": [99, 100, 101, 102],
        "placed_reference_bounds_mm": {n: bounds(s) for n, s in refs.items()},
        "with_camera_mm": bounds(Part.makeCompound(board)),
        "without_camera_mm": bounds(Part.makeCompound(board[:99])),
        "FDM": checks,
        "reopened": True,
        "clear_acoustic_ray_test_radius_mm": 0.35,
        "STL": stl,
        "max_allowed_intersection_mm3": 0.001,
    }
    (HERE / "checks" / "geometry.json").write_text(json.dumps(report, indent=2) + "\n")
    print(stl)


STEP_SHA = "a37c6b41d5660cd3310fea05edde0238762fe00da4de623936b7ca66814cb698"
if __name__ == "__main__":
    main()
