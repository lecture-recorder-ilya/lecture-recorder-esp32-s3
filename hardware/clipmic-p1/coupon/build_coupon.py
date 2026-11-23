"""Сгенерировать и проверить STL купона в Python FreeCAD. Единицы — мм."""
from pathlib import Path

import FreeCAD as App
import Mesh
import MeshPart
import Part

ROOT = Path(__file__).resolve().parent
V = App.Vector
# ID, диаметр окна, зазор под носиком одной штатной клипсы
VARIANTS = [(1, 4.8, 0.25), (2, 5.0, 0.45), (3, 5.2, 0.65)]
SEGMENTS = {
    "a": (0, 3.4, 2.5, .8), "b": (1.7, 1.7, .8, 2.1),
    "c": (1.7, 0, .8, 2.1), "d": (0, 0, 2.5, .8),
    "e": (0, 0, .8, 2.1), "f": (0, 1.7, .8, 2.1), "g": (0, 1.7, 2.5, .8),
}
DIGITS = {"0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg",
          "4": "bcfg", "7": "abc", "5": "acdfg", "6": "acdefg", "8": "abcdefg"}


def legend(text, x, y):
    blocks = []
    for char in text:
        if char == ".":
            blocks.append(Part.makeBox(.9, .9, .6, V(x, y, 1.6)))
            x += 1.9
        else:
            for seg in DIGITS[char]:
                dx, dy, w, h = SEGMENTS[seg]
                blocks.append(Part.makeBox(w, h, .6, V(x + dx, y + dy, 1.6)))
            x += 3.6
    return blocks


def build():
    base = Part.makeBox(63, 69, 1.6)
    base = base.fuse(Part.makeBox(63, 35, 2.4, V(0, 0, 1.6)))
    doc = App.openDocument(str(ROOT.parent / "ClipMic-P1.FCStd"))
    for number, diameter, gap in VARIANTS:
        x = (number - .5) * 21
        lift = gap - .25
        if lift > 0:
            base = base.fuse(Part.makeBox(13, 6.7, lift, V(x - 6.5, 27.3, 4)))
        for dx in (-3.5, 3.5):
            base = base.cut(Part.makeCylinder(.85, 3.2, V(x + dx, 31, 4 + lift - 3.1)))
        base = base.cut(Part.makeCylinder(diameter / 2, 2, V(x + 3, 51, 0)))
        for text, y in [(str(number), 49), (f"{diameter:.1f}", 43), (f"{gap:.2f}", 36.5)]:
            base = base.multiFuse(legend(text, x - 8, y))
        # Пробное окно защёлки крышки, отдельно от штатной клипсы одежды.
        clearance = (.15, .25, .35)[number - 1]
        width, depth = 8 + 2 * clearance, 3 + 2 * clearance
        base = base.cut(Part.makeBox(width, depth, 2, V(x - width / 2, 65 - depth / 2, 0)))
        base = base.multiFuse(legend(f"{clearance:.2f}", x - 8, 56))
        assert 0 < .85 - clearance < 1
        locked = snap_key()
        locked.rotate(V(), V(1, 0, 0), -90)
        locked.translate(V(x, 65 - 1.5, 10.6))
        assert locked.common(base).Volume < 1e-6
        clip = doc.Clip.Shape.copy()
        clip.rotate(V(), V(0, 1, 0), 180)
        clip.translate(V(x + 20.5, 0, 4 + lift))
        assert clip.common(base).Volume < 1e-6
        contact = Part.Vertex(V(x, 9, 4))
        assert abs(contact.distToShape(clip)[0] - gap) < 1e-5
    App.closeDocument(doc.Name)
    return base.removeSplitter()


def snap_key():
    # Две гибкие лапки лежат в плоскости стола. Y — направление вставки.
    handle = Part.makeBox(16, 4, 3, V(-8, -4, 0))
    for sign in (-1, 1):
        outline = [(2.8, 0), (4, 0), (4, 11), (4.85, 11), (4.85, 11.4),
                   (3.7, 13.5), (2.8, 13.5)]
        pts = [V(sign * x, y, 0) for x, y in outline]
        arm = Part.Face(Part.makePolygon(pts + [pts[0]])).extrude(V(0, 0, 3))
        handle = handle.fuse(arm)
        handle = handle.fuse(Part.makeBox(1.2, 9, 3, V(6.6 if sign == 1 else -7.8, 0, 0)))
    return handle.removeSplitter()


def export(solid, name):
    assert solid.isValid() and len(solid.Solids) == 1
    path = ROOT / name
    MeshPart.meshFromShape(Shape=solid, LinearDeflection=.025, AngularDeflection=.12,
                           Relative=False).write(str(path))
    mesh = Mesh.Mesh(str(path))
    assert mesh.isSolid() and abs(mesh.BoundBox.ZMin) < 1e-5
    print(name, mesh.BoundBox, mesh.CountFacets, "facets")


if __name__ == "__main__":
    export(build(), "P1-coupon.stl")
    export(snap_key(), "Snap-key.stl")
