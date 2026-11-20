"""No-network, deterministic 2D editorial illustration plates for Violin Prince."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter

WIDTH, HEIGHT = 1024, 1792
RENDERER_VERSION = "violin-prince-vector-illustrator-v2"
VIOLIN_TUNING_PEG_POSITIONS = ((-1, 118), (-1, 164), (1, 118), (1, 164))
VIOLIN_STRING_OFFSETS = (-18, -6, 6, 18)
VIOLIN_BODY_COLOR = (177, 88, 43)
MODES = {
    "macro_illustration", "mechanism_illustration", "waveform",
    "melody_map", "comparison", "cover_performance",
}
NAVY = (11, 23, 38)
NAVY_MID = (23, 48, 63)
TEAL = (40, 126, 132)
TEAL_LIGHT = (100, 193, 188)
GOLD = (181, 108, 56)
GOLD_LIGHT = (238, 190, 121)
IVORY = (245, 230, 203)
WOOD = (174, 97, 54)
WOOD_DARK = (73, 44, 32)
CORAL = (218, 108, 78)
SKY = (83, 177, 213)
LEAF = (126, 184, 130)


def _background() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        color = tuple(int(NAVY[i] * (1 - t) + NAVY_MID[i] * t) for i in range(3))
        draw.line((0, y, WIDTH, y), fill=color)
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((100, 250, 930, 1300), fill=(*TEAL, 86))
    glow_draw.ellipse((310, 520, 1020, 1530), fill=(*CORAL, 42))
    glow_draw.ellipse((-80, 800, 560, 1640), fill=(*SKY, 22))
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

    # Recognisable violin outline: upper bout, pinched C-bouts, and a broader lower bout.
    body = _path((512, 560), [
        ((449, 526), (365, 531), (340, 600)),
        ((309, 674), (365, 753), (402, 790)),
        ((374, 817), (375, 875), (383, 918)),
        ((393, 1022), (438, 1140), (512, 1166)),
        ((586, 1140), (631, 1022), (641, 918)),
        ((649, 875), (650, 817), (622, 790)),
        ((659, 753), (715, 674), (684, 600)),
        ((659, 531), (575, 526), (512, 560)),
    ])
    shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon([(x+15, y+22) for x, y in mapped(body)],
                                  fill=(0, 0, 0, 110))
    layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(20)))
    d = ImageDraw.Draw(layer, "RGBA")
    d.polygon(mapped(body), fill=(*VIOLIN_BODY_COLOR, 255),
              outline=(78, 43, 31, 255), width=10)
    d.line(mapped(body + [body[0]]), fill=(242, 190, 119, 230), width=4, joint="curve")

    # A restrained varnish highlight adds painted depth without turning the
    # instrument into a generic glossy 3D prop.
    body_mask = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(body_mask).polygon(mapped(body), fill=255)
    varnish = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    varnish_draw = ImageDraw.Draw(varnish)
    varnish_draw.ellipse((tr(401, 650), tr(624, 1090)), fill=(255, 174, 91, 72))
    varnish.putalpha(ImageChops.multiply(varnish.getchannel("A"), body_mask))
    layer.alpha_composite(varnish.filter(ImageFilter.GaussianBlur(30)))
    d = ImageDraw.Draw(layer, "RGBA")

    inner = [(512,585),(448,568),(383,590),(370,650),(396,748),(420,790),
             (400,820),(405,886),(423,986),(455,1084),(512,1128),
             (569,1084),(601,986),(619,886),(624,820),(604,790),
             (628,748),(654,650),(641,590),(576,568),(512,585)]
    d.line(mapped(inner), fill=(93, 50, 31, 190), width=4, joint="curve")
    for y, width in ((650, 100), (690, 125), (1040, 110), (1073, 85)):
        grain = _curve((512-width, y), (512-width*.35, y-14),
                       (512+width*.35, y+12), (512+width, y))
        d.line(mapped(grain), fill=(242, 188, 125, 76), width=2)

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
    d.polygon(mapped(neck), fill=(70, 43, 33, 255), outline=(226, 171, 106, 255), width=5)
    d.polygon(mapped(fingerboard), fill=(29, 31, 34, 255), outline=(130, 91, 57, 255), width=4)
    d.polygon(mapped([(486, 184), (538, 184), (538, 201), (486, 201)]),
              fill=(34, 30, 29, 255), outline=(224, 190, 134, 220))
    scroll = _path((480,190), [
        ((470,150),(448,122),(461,91)), ((474,58),(498,53),(512,75)),
        ((531,52),(557,60),(565,91)), ((578,121),(554,151),(544,190))
    ])
    d.line(mapped(scroll), fill=(*GOLD_LIGHT,255), width=10, joint="curve")
    spiral = _path((512,89), [((536,83),(552,101),(537,116)),
                              ((523,129),(504,119),(511,105))])
    d.line(mapped(spiral), fill=(111,79,52,255), width=5, joint="curve")

    # A violin has four tuning pegs total: two on each side of the pegbox.
    for side, y in VIOLIN_TUNING_PEG_POSITIONS:
        x = 512 + side * 56
        p1, p2 = tr(x, y), tr(x + side * 36, y)
        d.line((p1, p2), fill=(62, 39, 30, 255), width=9)
        ex, ey = p2
        d.ellipse((ex-12, ey-12, ex+12, ey+12), fill=(155, 98, 54, 255),
                  outline=(58, 37, 29, 255), width=3)
        d.ellipse((ex-5, ey-5, ex+5, ey+5), fill=(222, 157, 91, 255))

    bridge = [(470,940),(480,900),(495,888),(512,890),(529,888),(544,900),
              (554,940),(540,953),(525,947),(512,950),(499,947),(484,953)]
    d.polygon(mapped(bridge), fill=(168,126,76,255), outline=(61,42,31,255), width=5)
    d.line(mapped([(483,918),(512,910),(541,918)]), fill=(238,210,153,255), width=4)
    tail = [(490,950),(480,1080),(500,1110),(512,1115),(524,1110),(544,1080),(534,950)]
    d.polygon(mapped(tail), fill=(55,42,37,255), outline=(*GOLD,255), width=4)

    # The number and placement of strings are fixed: exactly four.
    for offset in VIOLIN_STRING_OFFSETS:
        x = 512 + offset
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


def _scene_profile(plan: dict[str, Any] | None) -> str:
    """Choose a closed local illustration family from safe topic keywords only."""
    if not isinstance(plan, dict):
        return "violin"
    text = " ".join(
        str(plan.get(key) or "")
        for key in ("topic", "title", "core_claim", "narration_script")
    ).casefold()
    studio_terms = (
        "roomtune", "room correction", "room acoustics", "acoustic treatment",
        "studio monitor", "monitor response", "monitor playback",
        "audio interface", "onboard dsp", "monitor correction",
    )
    return "studio_acoustics" if any(term in text for term in studio_terms) else "violin"


def _draw_studio_monitor(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float = 1.0):
    """Draw a compact nearfield monitor with controlled, recognisable geometry."""
    w, h = round(190 * scale), round(320 * scale)
    draw.rounded_rectangle((x, y, x + w, y + h), radius=round(16 * scale),
                           fill=(27, 39, 47, 255), outline=(*GOLD_LIGHT, 255),
                           width=max(2, round(4 * scale)))
    draw.rounded_rectangle((x + round(12*scale), y + round(12*scale),
                            x + w - round(12*scale), y + h - round(12*scale)),
                           radius=round(10*scale), outline=(105, 140, 142, 180),
                           width=max(1, round(2*scale)))
    cx = x + w // 2
    cy = y + round(132 * scale)
    radius = round(64 * scale)
    draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius),
                 fill=(11, 20, 29, 255), outline=(*TEAL_LIGHT, 255),
                 width=max(2, round(4*scale)))
    draw.ellipse((cx-round(42*scale), cy-round(42*scale),
                  cx+round(42*scale), cy+round(42*scale)),
                 fill=(46, 68, 74, 255), outline=(*GOLD, 255),
                 width=max(2, round(3*scale)))
    draw.ellipse((cx-round(15*scale), cy-round(15*scale),
                  cx+round(15*scale), cy+round(15*scale)),
                 fill=(*GOLD_LIGHT, 255))
    tweeter_y = y + round(238 * scale)
    tweeter_r = round(27 * scale)
    draw.ellipse((cx-tweeter_r, tweeter_y-tweeter_r,
                  cx+tweeter_r, tweeter_y+tweeter_r),
                 fill=(11, 20, 29, 255), outline=(*TEAL_LIGHT, 255),
                 width=max(2, round(3*scale)))
    draw.ellipse((cx-round(8*scale), tweeter_y-round(8*scale),
                  cx+round(8*scale), tweeter_y+round(8*scale)),
                 fill=(*GOLD_LIGHT, 255))
    led = y + h - round(28*scale)
    draw.ellipse((cx-round(4*scale), led-round(4*scale),
                  cx+round(4*scale), led+round(4*scale)),
                 fill=(*TEAL_LIGHT, 255))


def _draw_measurement_mic(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float = 1.0):
    """Draw a calibration microphone and stand without labels or fabricated readings."""
    stem_top = y - round(115 * scale)
    capsule_w, capsule_h = round(23*scale), round(62*scale)
    draw.rounded_rectangle((x-capsule_w//2, stem_top, x+capsule_w//2,
                            stem_top+capsule_h), radius=round(10*scale),
                           fill=(224, 216, 194, 255), outline=(*GOLD, 255),
                           width=max(2, round(3*scale)))
    draw.line((x, stem_top+capsule_h, x, y+round(150*scale)),
              fill=(219, 209, 181, 255), width=max(2, round(5*scale)))
    draw.line((x, y+round(90*scale), x-round(60*scale), y+round(155*scale)),
              fill=(*GOLD_LIGHT, 255), width=max(2, round(4*scale)))
    draw.line((x, y+round(90*scale), x+round(60*scale), y+round(155*scale)),
              fill=(*GOLD_LIGHT, 255), width=max(2, round(4*scale)))
    draw.line((x, y+round(145*scale), x, y+round(190*scale)),
              fill=(*GOLD_LIGHT, 255), width=max(2, round(4*scale)))


def _studio_macro():
    """A listening-room overview: nearfield monitors, calibration mic and violin context."""
    image = _background()
    d = ImageDraw.Draw(image, "RGBA")
    # Acoustic wall panels and perspective floor.
    for x in (115, 335, 555, 775):
        d.rounded_rectangle((x, 250, x+125, 490), radius=10,
                            fill=(22, 46, 55, 170), outline=(106, 158, 155, 115), width=3)
        for offset in (32, 76, 120, 164, 208):
            d.line((x+18, 250+offset, x+107, 250+offset),
                   fill=(118, 158, 151, 38), width=2)
    d.line((90, 1180, 934, 1180), fill=(*GOLD_LIGHT, 125), width=3)
    d.line((170, 1180, 512, 1515), fill=(*GOLD_LIGHT, 54), width=3)
    d.line((854, 1180, 512, 1515), fill=(*GOLD_LIGHT, 54), width=3)

    _draw_studio_monitor(d, 115, 615, .88)
    _draw_studio_monitor(d, 742, 615, .88)
    _draw_measurement_mic(d, 512, 925, .90)
    for radius in (95, 145, 205):
        d.arc((512-radius, 760-radius*.45, 512+radius, 760+radius*.45),
              195, 345, fill=(*GOLD_LIGHT, 115), width=3)
    # A restrained violin silhouette links the room-correction story to the channel.
    _draw_violin(image, center=(512, 1485), scale=.58, angle=-2)
    return image


def _studio_measurement():
    """A conceptual calibration path with a mic, two monitors and an illustrative response curve."""
    image = _background()
    d = ImageDraw.Draw(image, "RGBA")

    # Response plot; no ticks or numeric values because no real-room measurement is supplied.
    d.rounded_rectangle((100, 230, 924, 590), radius=22,
                        fill=(9, 22, 35, 165), outline=(*GOLD_LIGHT, 105), width=3)
    for y in (310, 390, 470, 550):
        d.line((140, y, 884, y), fill=(126, 158, 160, 50), width=2)
    before = []
    after = []
    for step in range(100):
        x = 150 + step * 7
        phase = step / 99
        y1 = 420 + 74*math.sin(phase*math.pi*4) + 24*math.sin(phase*math.pi*11)
        y2 = 420 + 18*math.sin(phase*math.pi*4 + .25)
        before.append((round(x), round(y1)))
        after.append((round(x), round(y2)))
    d.line(before, fill=(*CORAL, 245), width=6, joint="curve")
    d.line(after, fill=(*SKY, 255), width=6, joint="curve")

    _draw_studio_monitor(d, 95, 790, .68)
    _draw_studio_monitor(d, 739, 790, .68)
    _draw_measurement_mic(d, 512, 980, .95)

    # Audio interface panel, controls and signal path.
    d.rounded_rectangle((252, 1300, 772, 1570), radius=24,
                        fill=(23, 35, 43, 255), outline=(*GOLD_LIGHT, 230), width=5)
    d.rounded_rectangle((280, 1330, 744, 1535), radius=14,
                        outline=(112, 158, 154, 150), width=3)
    for index, x in enumerate((350, 458, 566, 674)):
        d.ellipse((x-33, 1370-33, x+33, 1370+33),
                  fill=(10, 19, 27, 255), outline=(*GOLD_LIGHT, 240), width=4)
        d.arc((x-24, 1370-24, x+24, 1370+24), 205, 330,
              fill=(*TEAL_LIGHT, 255), width=4)
        d.line((x, 1370, x+round(19*math.cos(index*.55)),
                1370-round(19*math.sin(index*.55))),
               fill=(242, 229, 199, 255), width=4)
        d.rounded_rectangle((x-30, 1450, x+30, 1500), radius=8,
                            fill=(45, 66, 70, 255), outline=(129, 166, 157, 170), width=2)
    return image


def _studio_cover():
    """A violin performance payoff placed inside the same treated listening room."""
    image = _background()
    d = ImageDraw.Draw(image, "RGBA")
    _draw_studio_monitor(d, 80, 760, .58)
    _draw_studio_monitor(d, 770, 760, .58)
    for radius in (145, 220, 295):
        d.arc((512-radius, 420-radius*.36, 512+radius, 420+radius*.36),
              195, 345, fill=(*TEAL_LIGHT, 110), width=4)
    _draw_violin(image, center=(490, 1215), scale=.92, angle=-16)
    d = ImageDraw.Draw(image, "RGBA")
    bow = _curve((145, 510), (350, 560), (670, 1050), (900, 1210), 80)
    d.line(bow, fill=(33, 29, 27, 190), width=20, joint="curve")
    d.line(bow, fill=(*GOLD_LIGHT, 220), width=4, joint="curve")
    return image


def render_scene(scene: dict[str, Any], index: int, plan: dict[str, Any] | None,
                 output_path: str | Path) -> Path:
    """Render a reviewed visual mode from a closed set of deterministic local compositions."""
    del index  # Scene prompts are descriptive metadata, never executable input.
    if not isinstance(scene, dict):
        raise ValueError("Scene must be a JSON object.")
    mode = str(scene.get("visual_mode") or "").strip().casefold()
    profile = _scene_profile(plan)
    renderers = {
        "macro_illustration": _studio_macro if profile == "studio_acoustics" else _macro,
        "mechanism_illustration": _mechanism,
        "waveform": _studio_measurement if profile == "studio_acoustics" else _waveform,
        "melody_map": _melody_map,
        "comparison": _comparison,
        "cover_performance": _studio_cover if profile == "studio_acoustics" else _cover,
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
