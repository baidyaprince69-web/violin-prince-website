"""Generate replaceable, story-specific layered 2.5D cinematic environment plates."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

PALETTES = {
    "midnight_resonance": {
        "top": (4, 8, 20), "bottom": (10, 25, 46),
        "gold": (222, 164, 89), "teal": (63, 186, 190), "blue": (45, 83, 135),
    },
    "deep_space": {
        "top": (5, 4, 22), "bottom": (14, 13, 49),
        "gold": (154, 142, 255), "teal": (70, 176, 255), "blue": (57, 64, 164),
    },
    "forest_atmosphere": {
        "top": (3, 16, 18), "bottom": (10, 38, 34),
        "gold": (212, 174, 100), "teal": (83, 171, 132), "blue": (36, 101, 83),
    },
    "warm_documentary": {
        "top": (17, 10, 9), "bottom": (42, 24, 15),
        "gold": (230, 164, 91), "teal": (100, 139, 139), "blue": (89, 68, 56),
    },
}


def resolve_style(plan: dict) -> str:
    configured = (plan.get("cinematic_background") or {}).get("preset") or plan.get("background_style")
    if configured in PALETTES:
        return configured
    text = " ".join((str(plan.get("title", "")), str(plan.get("topic", "")))).casefold()
    if any(word in text for word in ("space", "planet", "galaxy", "astronomy", "universe")):
        return "deep_space"
    if any(word in text for word in ("forest", "wildlife", "nature", "jungle", "tree")):
        return "forest_atmosphere"
    if any(word in text for word in ("history", "ancient", "workshop", "industrial", "machine")):
        return "warm_documentary"
    return "midnight_resonance"


def _mix(a, b, amount):
    return tuple(round(a[i] * (1.0 - amount) + b[i] * amount) for i in range(3))


def _gradient(width, height, palette):
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = (y / max(1, height - 1)) ** 2 * 0.82
        draw.line((0, y, width, y), fill=_mix(palette["top"], palette["bottom"], t))
    return image


def generate_bundle(plan_path: Path, output_dir: Path, *, width=1080, height=1920):
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    style = resolve_style(plan)
    palette = PALETTES[style]
    output_dir.mkdir(parents=True, exist_ok=True)

    background = _gradient(width, height, palette).convert("RGBA")
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((width*.13, height*.12, width*.95, height*.76), fill=(*palette["blue"], 42))
    glow_draw.ellipse((width*.22, height*.30, width*.78, height*.88), fill=(*palette["gold"], 22))
    glow = glow.filter(ImageFilter.GaussianBlur(max(18, width // 18)))
    background = Image.alpha_composite(background, glow)

    architecture = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(architecture)
    cx = width // 2
    for offset, alpha, thickness in ((0, 32, 5), (76, 25, 3), (152, 17, 2)):
        box = (cx-width*.66-offset, height*.20-offset, cx+width*.66+offset, height*.90+offset)
        draw.arc(box, start=188, end=352, fill=(*palette["gold"], alpha), width=thickness)
    for x in (width*.08, width*.20, width*.80, width*.92):
        draw.line((x, height*.10, x, height*.84), fill=(*palette["teal"], 22), width=max(2, width//500))
    draw.line((0, height*.84, width, height*.84), fill=(*palette["gold"], 44), width=max(2, width//420))
    for fraction in (.08, .22, .40, .60, .78, .92):
        draw.line((cx, height*.84, width*fraction, height), fill=(*palette["blue"], 25), width=2)
    architecture = architecture.filter(ImageFilter.GaussianBlur(2.2))
    background = Image.alpha_composite(background, architecture)
    background_path = output_dir / "01-distant-environment.png"
    background.convert("RGB").save(background_path, quality=95)

    beams = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    beam_draw = ImageDraw.Draw(beams)
    beam_draw.polygon([(width*.22,0),(width*.34,0),(width*.70,height*.86),(width*.49,height*.86)],
                      fill=(*palette["gold"],38))
    beam_draw.polygon([(width*.71,0),(width*.78,0),(width*.53,height*.81),(width*.43,height*.81)],
                      fill=(*palette["teal"],29))
    beam_draw.ellipse((width*.23,height*.46,width*.79,height*.98),fill=(*palette["blue"],23))
    beams = beams.filter(ImageFilter.GaussianBlur(max(20,width//20)))
    lighting = Image.alpha_composite(Image.new("RGBA",(width,height),(0,0,0,0)),beams)
    crisp = ImageDraw.Draw(lighting)
    crisp.line((width*.27,0,width*.49,height*.80),fill=(*palette["gold"],60),width=max(2,width//500))
    crisp.line((width*.76,0,width*.52,height*.78),fill=(*palette["teal"],48),width=max(2,width//500))
    lighting = lighting.filter(ImageFilter.GaussianBlur(5))
    lights_path = output_dir / "02-atmospheric-light.png"
    lighting.save(lights_path)

    particles = Image.new("RGBA", (width,height), (0,0,0,0))
    particle_draw = ImageDraw.Draw(particles)
    rng = random.Random(20261115 + len(str(plan.get("topic",""))))
    for index in range(58):
        x,y = rng.randint(25,width-25),rng.randint(40,height-40)
        radius = rng.choice((2,3,4,6,8,11))
        color = palette["gold"] if index % 3 else palette["teal"]
        particle_draw.ellipse((x-radius,y-radius,x+radius,y+radius),
                              fill=(*color,rng.randint(22,90)))
    particles = particles.filter(ImageFilter.GaussianBlur(7))
    foreground = Image.alpha_composite(Image.new("RGBA",(width,height),(0,0,0,0)),particles)
    sharp = ImageDraw.Draw(foreground)
    for x,y in ((width*.10,height*.24),(width*.89,height*.37),(width*.17,height*.74),(width*.83,height*.78)):
        sharp.ellipse((x-4,y-4,x+4,y+4),fill=(*palette["gold"],120))
    foreground_path = output_dir / "03-foreground-bokeh.png"
    foreground.save(foreground_path)

    manifest = {
        "schema_version":1,"style":style,"resolution":[width,height],
        "source_story":str(plan.get("title","Untitled story")),"layer_order":"back-to-front",
        "layers":[
            {"name":"Distant Environment","role":"background","file":background_path.name,
             "distance":3.0,"cover_scale":1.40,"parallax_x":0.035,"parallax_z":0.015},
            {"name":"Atmospheric Light","role":"atmosphere","file":lights_path.name,
             "distance":2.1,"cover_scale":1.36,"parallax_x":0.080,"parallax_z":0.035},
            {"name":"Foreground Bokeh","role":"foreground","file":foreground_path.name,
             "distance":1.2,"cover_scale":1.30,"parallax_x":0.145,"parallax_z":0.060},
        ],
    }
    manifest_path=output_dir/"background-manifest.json"
    manifest_path.write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    return manifest_path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--plan",required=True)
    parser.add_argument("--output-dir",required=True)
    parser.add_argument("--width",type=int,default=1080)
    parser.add_argument("--height",type=int,default=1920)
    args=parser.parse_args()
    path=generate_bundle(Path(args.plan),Path(args.output_dir),width=args.width,height=args.height)
    print(json.dumps({"status":"background_bundle_created","manifest":str(path),"layers":3},indent=2))


if __name__=="__main__":
    main()
