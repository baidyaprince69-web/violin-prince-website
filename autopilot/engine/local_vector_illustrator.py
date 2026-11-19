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
    """A deliberate close crop of the violin's lower bout, bridge and four strings."""
    image = _background()
    d = ImageDraw.Draw(image, "RGBA")
    d.ellipse((100,240,924,1280), outline=(211,171,105,64), width=4)
    d.ellipse((155,300,869,1220), outline=(211,171,105,30), width=2)
    # The larger scale crops the scroll and centres the bridge/string contact area.
    _draw_violin(image, center=(512,940), scale=1.58, angle=-2)
    d = ImageDraw.Draw(image, "RGBA")
    for radius in (115,170,230,295):
        d.arc((512-radius,945-radius*.28,512+radius,945+radius*.28),
              190,350,fill=(215,170,94,118),width=3)
    d.line((115,1485,909,1485),fill=(217,183,119,105),width=2)
    return image


def _mechanism():
    """Show a violin soundboard in profile with four correctly oriented strings over one bridge."""
    image = _background()
    d = ImageDraw.Draw(image, "RGBA")

    # Upright violin top plate: the strings run along its length, bridge across its width.
    plate = _path((512,250), [
        ((330,205),(172,338),(174,570)),
        ((176,765),(295,882),(350,980)),
        ((300,1130),(345,1455),(512,1545)),
        ((679,1455),(724,1130),(674,980)),
        ((729,882),(848,765),(850,570)),
        ((852,338),(694,205),(512,250)),
    ])
    d.polygon(plate,fill=(214,194,155,255),outline=(*GOLD_LIGHT,255),width=8)
    d.line(plate+[plate[0]],fill=(104,77,48,190),width=4,joint="curve")

    # Longitudinal wood grain, kept subtle so the bridge remains the focal point.
    for x in range(295,750,28):
        pts = [(x+round(12*math.sin(y/180)),y) for y in range(390,1430,12)]
        d.line(pts,fill=(143,105,68,48),width=2)

    # Two f-hole hints anchor the illustration as a violin soundboard.
    left_hole = _path((350,720),[
        ((390,770),(330,830),(352,895)),
        ((370,950),(365,1000),(342,1050)),
    ])
    right_hole = _path((674,720),[
        ((634,770),(694,830),(672,895)),
        ((654,950),(659,1000),(682,1050)),
    ])
    d.line(left_hole,fill=(57,43,34,255),width=14,joint="curve")
    d.line(right_hole,fill=(57,43,34,255),width=14,joint="curve")

    # One arched maple bridge spans across the four longitudinal strings.
    bridge = _path((330,885),[
        ((370,850),(425,812),(512,805)),
        ((599,812),(654,850),(694,885)),
        ((684,951),(659,1010),(637,1080)),
        ((600,1110),(572,1080),(548,1050)),
        ((532,1032),(492,1032),(476,1050)),
        ((448,1080),(420,1110),(383,1080)),
        ((361,1010),(340,951),(330,885)),
    ])
    d.polygon(bridge,fill=(166,116,66,255),outline=(56,39,30,255),width=7)
    d.line(_curve((365,892),(430,820),(590,820),(659,892)),
           fill=(238,201,139,255),width=5,joint="curve")
    # Dark bridge heart and cut-out windows are geometric and symmetrical.
    d.polygon([(477,911),(493,874),(512,861),(531,874),(547,911),
               (539,967),(525,991),(512,976),(499,991),(485,967)],
              fill=(49,39,32,255),outline=(218,172,105,255),width=4)
    d.ellipse((494,900,506,912),fill=(226,190,122,230))
    d.ellipse((518,900,530,912),fill=(226,190,122,230))
    d.line([(394,1068),(386,1170)],fill=(102,68,42,255),width=17)
    d.line([(630,1068),(638,1170)],fill=(102,68,42,255),width=17)

    # Exactly four strings travel vertically across the bridge and the soundboard.
    string_x = (476, 500, 524, 548)
    for x in string_x:
        d.line([(x,335),(x,1430)],fill=(66,52,39,210),width=6)
        d.line([(x-1,335),(x-1,1430)],fill=(248,232,193,255),width=2)

    # Gentle transverse oscillation around the second string, not around the whole bridge.
    for amplitude, alpha in ((7,185),(14,120),(21,70)):
        points = []
        for y in range(520,790,4):
            x = 500 + amplitude*math.sin((y-520)/270*math.pi*5)
            points.append((round(x),y))
        d.line(points,fill=(221,170,88,alpha),width=4,joint="curve")

    # Direction cues radiate from the contact point into the wooden top plate.
    for radius in (105,165,230):
        d.arc((512-radius,570-radius*.48,512+radius,570+radius*.48),
              198,342,fill=(104,172,166,105),width=3)
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
    suffix = target.suffix.casefold()
    if suffix in {".jpg", ".jpeg"}:
        image.convert("RGB").save(target, format="JPEG", quality=93, optimize=True, progressive=True)
    elif suffix == ".png":
        image.save(target, format="PNG", optimize=True)
    else:
        raise ValueError(f"Unsupported illustration file extension: {suffix or '[missing]'}")
    return target
