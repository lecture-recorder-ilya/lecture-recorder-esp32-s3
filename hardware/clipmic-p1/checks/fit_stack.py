"""Промеры сборки FreeCAD по сечениям. Печатает номиналы и условный нижний запас, мм."""
from pathlib import Path
import FreeCAD as App
import Part

d = App.openDocument(str(Path(__file__).resolve().parents[1] / "ClipMic-P1.FCStd"))
board, usb, card, pack = [d.getObject(k).Shape.optimalBoundingBox()
                          for k in ("BasePCB", "USB", "Card", "PackMax")]


def cuts(name, axis, point):
    start, end = list(point), list(point)
    start[axis], end[axis] = -1, 75
    line = Part.makeLine(App.Vector(*start), App.Vector(*end))
    return sorted(sorted(v.Point[axis] for v in edge.Vertexes)
                  for edge in d.getObject(name).Shape.common(line).Edges)


x = cuts("Tray", 0, (0, 9.7, 3))
y = cuts("Tray", 1, (12, 0, 3))
front, rear = x[1][1], x[2][0]
left, right = y[1][1], y[2][0]
sx, tx = board.XMin - front, rear - board.XMax
sy, ty = board.YMin - left, right - board.YMax
support = cuts("Tray", 2, (5.5, 9.5, 0))[0][1]
ceiling = cuts("Lid", 2, (5.5, 9.5, 0))[0][0]
lift = ceiling - support - board.ZLength
opening = cuts("Tray", 1, (.8, 0, 6))
bottom = cuts("Tray", 2, (.8, 18, 0))[0][1]
relief = cuts("Lid", 2, (12, 18, 0))[0][0]
relief_end = cuts("Lid", 0, (0, 18, 11.6))[0][0]
relief_y = cuts("Lid", 1, (12, 0, 11.6))
pack_x = cuts("Tray", 0, (0, 7, 2.5))
pack_y = cuts("Tray", 1, (40, 0, 2.5))
floor = cuts("Tray", 2, (40, 18, 0))[0][1]
roof = cuts("Lid", 2, (40, 18, 0))[0][0]

# Три поля строки: номинальный запас, неблагоприятная сумма, ожидаемый номинал из сверки.
rows = {
    "PCB X общий люфт": (sx + tx, .2 + .2 + .1, .595),
    "PCB Y общий люфт": (sy + ty, .2 + .2 + .1, .55),
    "PCB Z общий люфт": (lift, .2 + .2 + .15 + .1, .50),
    "USB Y малая сторона у упора": (min(usb.YMin - opening[0][1] - sy,
                                         opening[1][0] - usb.YMax - ty), .2 + .2 + .1, 2.5973),
    "USB Z снизу": (usb.ZMin - bottom, .2 + .2 + .1, .76),
    "USB Z сверху у верхнего упора": (d.Tray.Shape.optimalBoundingBox().ZMax - usb.ZMax - lift,
                                      .2 + .2 + .15 + .1, 3.94),
    "SD Z у верхнего упора": (relief - card.ZMax - lift, .2 + .2 + .1, .35),
    "SD X конец выборки у упора": (relief_end - card.XMax - tx, .2 + .2 + .15 + .1, .2233),
    "SD Y край выборки у упора": (min(card.YMin - relief_y[0][1] - sy,
                                      relief_y[1][0] - card.YMax - ty), .2 + .2 + .15 + .1, .1853),
    "Батарея X свободная ширина": (pack_x[-1][0] - pack_x[-2][1] - pack.XLength, .2 + .2, 1.0),
    "Батарея Y свободная ширина": (pack_y[2][0] - pack_y[1][1] - pack.YLength, .2 + .2, 1.2),
    "Батарея Z при ленте 0,25": (roof - floor - .25 - pack.ZLength, .2 + .2 + .15 + .1, 5.25),
}
for label, (nominal, budget, expected) in rows.items():
    assert abs(nominal - expected) < .002, (label, nominal, expected)
    print(f"{label:38} {nominal:7.3f} - {budget:.2f} = {nominal-budget:7.3f}")
print(f"Утопление USB при смещении платы: {usb.XMin-sx:.3f} .. {usb.XMin+tx:.3f}")
