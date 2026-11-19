"""No-network, deterministic 2D editorial illustration plates for Violin Prince."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

WIDTH, HEIGHT = 1024, 1792
RENDERER_VERSION = "violin-prince-vector-illustrator-v1"
MODES = {
    "macro_illustration", "mechanism_illustration", "waveform",
    "melody_map", "comparison", "cover_performance",
}
NAVY = (7, 17, 31)
NAVY_MID = (11, 31, 47)
TEAL = (54, 119, 124)
TEAL_LIGHT = (114, 176, 169)
GOLD = (184, 139, 70)
GOLD_LIGHT = (226, 190, 122)
IVORY = (226, 211, 178)
WOOD = (156, 105, 61)
WOOD_DARK = (78, 52, 37)


def _background() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        color = tuple(int(NAVY[i] * (1 - t) + NAVY_MID[i] * t) for i in range(3))
        draw.line((0, y, WIDTH, y), fill=color)
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((100, 250, 930, 1300), fill=(*TEAL, 86))
    image = Image.alpha_composite(image.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(150)))
    frame = ImageDraw.Draw(image, "RGBA")
    frame.rounded_rectangle((28, 28, WIDTH - 28, HEIGHT - 28), radius=30,
                            outline=(*GOLD_LIGHT, 105), width=2)
    frame.rounded_rectangle((45, 45, WIDTH - 45, HEIGHT - 45), radius=22,
                            outline=(*GOLD_LIGHT, 36), width=1)
    for y in range(90, HEIGHT - 80, 84):
        frame.line((60, y, WIDTH - 60, y), fill=(*GOLD_LIGHT, 12), width=1)
    return image


def _curve(p0, p1, p2, p3, steps=28):
    points = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = u**3*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t**3*p3[0]
        y = u**3*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t**3*p3[1]
        points.append((round(x), round(y)))
    return points


def _path(start, segments):
    result, current = [start], start
    for c1, c2, end in segments:
        part = _curve(current, c1, c2, end)
        result.extend(part[1:])
        current = end
    return result


def _draw_violin(image: Image.Image, center=(512, 1050), scale=1.0, angle=0.0):
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ox, oy = center
    a = math.radians(angle)

    def tr(x, y):
        dx, dy = (x - 512) * scale, (y - 900) * scale
        return (round(ox + dx * math.cos(a) - dy * math.sin(a)),
                round(oy + dx * math.sin(a) + dy * math.cos(a)))

    def mapped(points):
        return [tr(x, y) for x, y in points]

    def box(p1, p2):
        return (min(p1[0], p2[0]), min(p1[1], p2[1]),
                max(p1[0], p2[0]), max(p1[1], p2[1]))

    body = _path((512, 560), [
        ((450, 530), (360, 535), (337, 600)),
        ((305, 680), (356, 753), (399, 774)),
        ((350, 812), (342, 895), (358, 975)),
        ((382, 1085), (444, 1150), (512, 1166)),
        ((580, 1150), (642, 1085), (666, 975)),
        ((682, 895), (674, 812), (625, 774)),
        ((668, 753), (719, 680), (687, 600)),
        ((664, 535), (574, 530), (512, 560)),
    ])
    shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon([(x+15, y+22) for x, y in mapped(body)],
                                  fill=(0, 0, 0, 110))
    layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(20)))
    d = ImageDraw.Draw(layer, "RGBA")
    d.polygon(mapped(body), fill=(*IVORY, 255), outline=(*GOLD_LIGHT, 255), width=9)
    d.line(mapped(body + [body[0]]), fill=(*WOOD_DARK, 220), width=4, joint="curve")

    inner = [(512,585),(430,565),(370,625),(395,740),(380,845),(395,980),
             (450,1095),(512,1120),(574,1095),(629,980),(644,845),(629,740),
             (654,625),(594,565),(512,585)]
    d.line(mapped(inner), fill=(121, 91, 59, 165), width=4, joint="curve")
    for y, width in ((650, 100), (690, 125), (1040, 110), (1073, 85)):
        grain = _curve((512-width, y), (512-width*.35, y-14),
                       (512+width*.35, y+12), (512+width, y))
        d.line(mapped(grain), fill=(163, 124, 77, 65), width=2)

    f_holes = [
        _path((424,760), [((440,790),(400,815),(414,842)),
                          ((426,865),(434,878),(416,900)),
                          ((399,922),(405,940),(411,954))]),
        _path((600,760), [((584,790),(624,815),(610,842)),
                          ((598,865),(590,878),(608,900)),
                          ((625,922),(619,940),(613,954))]),
    ]
    for hole in f_holes:
        d.line(mapped(hole), fill=(43, 34, 29, 255), width=10, joint="curve")
    for x, y in ((424,760),(411,954),(600,760),(613,954)):
        cx, cy = tr(x, y)
        d.ellipse((cx-7, cy-7, cx+7, cy+7), fill=(43, 34, 29, 255))

    neck = [(473,560),(468,335),(479,190),(545,190),(556,335),(551,560)]
    fingerboard = [(487,560),(484,315),(492,180),(532,180),(540,315),(537,560)]
    d.polygon(mapped(neck), fill=(65,48,42,255), outline=(*GOLD_LIGHT,255), width=5)
    d.polygon(mapped(fingerboard), fill=(35,32,31,255), outline=(110,86,62,255), width=4)
    scroll = _path((480,190), [
        ((470,150),(448,122),(461,91)), ((474,58),(498,53),(512,75)),
        ((531,52),(557,60),(565,91)), ((578,121),(554,151),(544,190))
    ])
    d.line(mapped(scroll), fill=(*GOLD_LIGHT,255), width=10, joint="curve")
    spiral = _path((512,89), [((536,83),(552,101),(537,116)),
                              ((523,129),(504,119),(511,105))])
    d.line(mapped(spiral), fill=(111,79,52,255), width=5, joint="curve")

    for side in (-1, 1):
        for y in (115, 155, 195, 235):
            x = 512 + side * 56
            p1, p2 = tr(x, y), tr(x + side * 38, y)
            d.line((p1, p2), fill=(65,45,35,255), width=8)
            ex, ey = p2
            d.ellipse((ex-11,ey-11,ex+11,ey+11), fill=(*GOLD_LIGHT,255),
                      outline=(68,48,36,255), width=3)

    bridge = [(470,940),(480,900),(495,888),(512,890),(529,888),(544,900),
              (554,940),(540,953),(525,947),(512,950),(499,947),(484,953)]
    d.polygon(mapped(bridge), fill=(168,126,76,255), outline=(61,42,31,255), width=5)
    d.line(mapped([(483,918),(512,910),(541,918)]), fill=(238,210,153,255), width=4)
    tail = [(490,950),(480,1080),(500,1110),(512,1115),(524,1110),(544,1080),(534,950)]
    d.polygon(mapped(tail), fill=(55,42,37,255), outline=(*GOLD,255), width=4)

    # The number and placement of strings are fixed: exactly four.
    for x in (494, 506, 518, 530):
        line = mapped([(x,150),(x-2,340),(x-2,560),(x,760),(x+1,940),(x,1090)])
        d.line(line, fill=(231,218,188,225), width=3)
        d.line(line, fill=(247,236,209,125), width=1)
    image.alpha_composite(layer)


def _macro():
    image = _background()
    d = ImageDraw.Draw(image, "RGBA")
    d.ellipse((150,240,874,1080), outline=(211,171,105,74), width=4)
    d.ellipse((205,300,819,1020), outline=(211,171,105,34), width=2)
    _draw_violin(image, center=(512,1050), scale=1.11, angle=-2)
    d = ImageDraw.Draw(image, "RGBA")
    for r in (90,140,198,260):
        d.arc((512-r,930-r*.32,512+r,930+r*.32), 190, 350,
              fill=(215,170,94,120), width=3)
    d.line((115,1465,909,1465), fill=(217,183,119,115), width=2)
    return image


def _mechanism():
    image = _background()
    d = ImageDraw.Draw(image, "RGBA")
    plate = _path((96,1070), [
        ((250,900),(770,900),(928,1070)),
        ((935,1240),(855,1480),(720,1510)),
        ((560,1590),(360,1590),(205,1510)),
        ((80,1435),(30,1240),(96,1070)),
    ])
    d.polygon(plate, fill=(210,188,146,255), outline=(*GOLD_LIGHT,255), width=7)
    d.line(plate + [plate[0]], fill=(104,77,48,190), width=4, joint="curve")
    for y in range(1150,1430,34):
        pts = [(x,round(y+28*math.sin((x-150)/730*math.pi)))
               for x in range(150,880,12)]
        d.line(pts, fill=(143,105,68,43), width=2)
    bridge = _path((445,1115), [
        ((455,1030),(460,890),(512,815)),
        ((564,890),(569,1030),(579,1115)),
        ((560,1140),(541,1110),(530,1095)),
        ((520,1087),(504,1087),(494,1095)),
        ((480,1110),(464,1140),(445,1115)),
    ])
    d.polygon(bridge, fill=(159,108,62,255), outline=(55,38,29,255), width=7)
    d.line([(456,1030),(512,855),(568,1030)], fill=(237,200,136,245), width=4)
    d.polygon([(486,1010),(495,953),(512,935),(529,953),(538,1010),
               (528,1055),(512,1035),(496,1055)],
              fill=(48,39,34,255), outline=(207,161,99,255), width=3)
    d.line([(478,1118),(470,1282)], fill=(113,75,44,255), width=18)
    d.line([(546,1118),(554,1282)], fill=(113,75,44,255), width=18)
    # Four strings, each a separate, fine line.
    for i, y in enumerate((818,837,856,875)):
        pts = [(120,y),(380,y-4),(640,y+2),(900,y-5)]
        d.line(pts, fill=(47,39,32,245), width=5, joint="curve")
        d.line([(x,yy-1) for x,yy in pts], fill=(238,218,178,255), width=2, joint="curve")
    for offset in range(3):
        pts = [(x,round(846+8*math.sin((x-235)/570*math.pi*4+offset*.14)))
               for x in range(235,805,7)]
        d.line(pts, fill=(223,176,94,85-offset*16), width=2, joint="curve")
    for r in (145,205,265):
        d.arc((512-r,530-r*.5,512+r,530+r*.5),195,345,
              fill=(104,172,166,105), width=3)
    return image


def _waveform():
    image = _background()
    _draw_violin(image, center=(495,1150), scale=.70, angle=18)
    d = ImageDraw.Draw(image, "RGBA")
    for row in range(6):
        pts = []
        for step in range(130):
            x = 440 + step * 4
            y = 450 + row * 70 + 26 * math.sin(step*.105+row*.32) * math.exp(-step/190)
            pts.append((round(x),round(y)))
        d.line(pts, fill=(221,179,103,165-row*16), width=4, joint="curve")
    for r in (65,110,165,220):
        d.arc((512-r,430-r,512+r,430+r),205,335,fill=(104,172,166,120),width=3)
    return image


def _melody_map():
    image = _background()
    d = ImageDraw.Draw(image, "RGBA")
    for y in (570,640,710,780,850):
        d.line((90,y,930,y), fill=(*GOLD_LIGHT,80), width=3)
    notes = [(180,780),(300,710),(420,640),(540,680),(660,780),(780,850),(900,710)]
    for x,y in notes:
        d.ellipse((x-18,y-12,x+18,y+12), fill=(*IVORY,255),
                  outline=(*GOLD_LIGHT,255), width=3)
    curve = _curve((155,930),(350,470),(670,1030),(895,580),100)
    d.line(curve, fill=(*TEAL_LIGHT,230), width=8, joint="curve")
    _draw_violin(image, center=(512,1330), scale=.48, angle=-3)
    return image


def _comparison():
    image = _background()
    d = ImageDraw.Draw(image, "RGBA")
    d.line((512,280,512,1470), fill=(*GOLD_LIGHT,90), width=3)
    d.ellipse((100,330,480,710), outline=(*TEAL_LIGHT,125), width=5)
    d.ellipse((544,330,924,710), outline=(*GOLD_LIGHT,125), width=5)
    for side, color in ((-1,TEAL_LIGHT),(1,GOLD_LIGHT)):
        origin = 512 + side * 215
        for row in range(5):
            pts = []
            for step in range(80):
                x = origin - 135 + step * 3.4
                y = 840 + row*52 + 27*math.sin(step*(.07+row*.004))*(1 if side < 0 else .6)
                pts.append((round(x),round(y)))
            d.line(pts, fill=(*color,180-row*20), width=4)
    _draw_violin(image, center=(512,1360), scale=.43)
    return image


def _cover():
    image = _background()
    _draw_violin(image, center=(480,1180), scale=.89, angle=-18)
    d = ImageDraw.Draw(image, "RGBA")
    bow = _curve((145,480),(340,520),(680,1020),(890,1190),80)
    d.line(bow, fill=(33,29,27,180), width=20, joint="curve")
    d.line(bow, fill=(*GOLD_LIGHT,215), width=4, joint="curve")
    for r in (150,235,320):
        d.arc((512-r,390-r*.45,512+r,390+r*.45),195,345,
              fill=(*TEAL_LIGHT,130), width=4)
    return image


def render_scene(scene: dict[str, Any], index: int, plan: dict[str, Any] | None,
                 output_path: str | Path) -> Path:
    """Render a reviewed visual mode with fixed, verifiable instrument geometry."""
    del index, plan  # Scene prompts and story text are never executable input.
    if not isinstance(scene, dict):
        raise ValueError("Scene must be a JSON object.")
    mode = str(scene.get("visual_mode") or "").strip().casefold()
    renderers = {
        "macro_illustration": _macro,
        "mechanism_illustration": _mechanism,
        "waveform": _waveform,
        "melody_map": _melody_map,
        "comparison": _comparison,
        "cover_performance": _cover,
    }
    renderer = renderers.get(mode)
    if renderer is None:
        raise ValueError(f"Unsupported local vector illustration mode: {mode or '[missing]'}")
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image = renderer()
    if image.size != (WIDTH, HEIGHT):
        raise ValueError(f"Unexpected illustration size: {image.size}")
    image.save(target, format="PNG", optimize=True)
    return target
