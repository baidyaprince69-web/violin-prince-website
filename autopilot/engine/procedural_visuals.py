"""Original, deterministic cinematic artwork for Violin Prince.

Generated locally with Pillow. No image provider, stock photograph, external account,
or network call is involved.
"""
from __future__ import annotations
import hashlib
import math
import random
from pathlib import Path
from typing import Any
from PIL import Image, ImageDraw, ImageFilter, ImageOps

WIDTH, HEIGHT = 720, 1280


def _curve(a, b, c, d, count=24):
    pts=[]
    for n in range(count+1):
        t=n/count; u=1-t
        pts.append((
            round(u**3*a[0]+3*u*u*t*b[0]+3*u*t*t*c[0]+t**3*d[0]),
            round(u**3*a[1]+3*u*u*t*b[1]+3*u*t*t*c[1]+t**3*d[1]),
        ))
    return pts


def _seed(prompt, scene, index):
    raw="|".join((str(prompt),str((scene or {}).get("visual_mode") or ""),
                  str((scene or {}).get("caption") or ""),str(index)))
    return int.from_bytes(hashlib.sha256(raw.encode()).digest()[:8],"big")


def _base(seed):
    top=((5,10,23),(8,20,34),(8,12,27))[seed%3]
    bottom=((12,30,47),(20,32,48),(24,26,43))[seed%3]
    image=Image.new("RGB",(WIDTH,HEIGHT))
    draw=ImageDraw.Draw(image)
    for y in range(HEIGHT):
        t=y/(HEIGHT-1); t=t*t*(3-2*t)
        colour=tuple(round(top[k]*(1-t)+bottom[k]*t) for k in range(3))
        draw.line((0,y,WIDTH,y),fill=colour)
    return image.convert("RGBA")


def _glow(canvas, centre, radius, colour, alpha=90):
    layer=Image.new("RGBA",canvas.size,(0,0,0,0))
    x,y=centre
    ImageDraw.Draw(layer).ellipse((x-radius,y-radius,x+radius,y+radius),fill=(*colour,alpha))
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(max(10,radius//2))))


def _violin(canvas, cx, cy, scale=1.0, angle=-7):
    w,h=270*scale,500*scale
    left=[]
    for seg in (
        ((cx,cy-h*.47),(cx-w*.24,cy-h*.49),(cx-w*.53,cy-h*.42),(cx-w*.46,cy-h*.24)),
        ((cx-w*.46,cy-h*.24),(cx-w*.39,cy-h*.10),(cx-w*.26,cy-h*.13),(cx-w*.31,cy+h*.015)),
        ((cx-w*.31,cy+h*.015),(cx-w*.45,cy+h*.16),(cx-w*.54,cy+h*.34),(cx,cy+h*.49)),
    ):
        p=_curve(*seg); left.extend(p if not left else p[1:])
    right=[(round(2*cx-x),y) for x,y in reversed(left)]
    polygon=left+right[1:]
    mask=Image.new("L",canvas.size,0)
    ImageDraw.Draw(mask).polygon(polygon,fill=255)
    wood=Image.new("RGBA",canvas.size,(0,0,0,0))
    wd=ImageDraw.Draw(wood)
    y0=max(0,round(cy-h*.5)); y1=min(HEIGHT,round(cy+h*.5))
    for y in range(y0,y1+1):
        t=(y-y0)/max(1,y1-y0)
        wd.line((0,y,WIDTH,y),fill=(round(62+95*t),round(27+48*t),round(12+22*t),255))
    wood.putalpha(mask)
    layer=Image.new("RGBA",canvas.size,(0,0,0,0))
    layer.alpha_composite(wood)
    d=ImageDraw.Draw(layer)
    d.line(polygon+[polygon[0]],fill=(237,180,102,225),width=max(3,round(5*scale)),joint="curve")
    top=cy-h*1.05; base=cy-h*.39
    d.polygon([(cx-w*.075,top+20),(cx+w*.075,top+20),(cx+w*.10,base),(cx-w*.10,base)],
              fill=(48,25,18,255),outline=(215,157,88,220))
    d.polygon([(cx-w*.055,top+25),(cx+w*.055,top+25),(cx+w*.06,base),(cx-w*.06,base)],
              fill=(21,19,20,255))
    d.ellipse((cx-w*.13,top-20,cx+w*.13,top+65),fill=(99,46,18,255),outline=(225,167,93,220),width=4)
    d.ellipse((cx-w*.055,top+1,cx+w*.055,top+42),fill=(24,18,17,255))
    bridge=cy+h*.065
    d.polygon([(cx-w*.16,bridge-18),(cx+w*.16,bridge-18),(cx+w*.12,bridge+15),(cx-w*.12,bridge+15)],
              fill=(229,199,145,255),outline=(72,39,19,255))
    d.polygon([(cx-w*.085,cy+h*.32),(cx+w*.085,cy+h*.32),(cx+w*.06,cy+h*.43),(cx-w*.06,cy+h*.43)],
              fill=(40,22,18,245))
    for off in (-.045,-.015,.015,.045):
        d.line((cx+w*off,top+55,cx+w*off,cy+h*.34),fill=(245,218,172,210),width=2)
    for side in (-1,1):
        x=cx+side*w*.235
        hole=_curve((x,cy-h*.12),(x-side*w*.04,cy-h*.04),(x+side*w*.03,cy+h*.01),(x,cy+h*.08))
        hole+=_curve(hole[-1],(x-side*w*.035,cy+h*.13),(x+side*w*.035,cy+h*.19),(x,cy+h*.24))[1:]
        d.line(hole,fill=(24,14,12,255),width=max(5,round(9*scale)),joint="curve")
    layer=Image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(13)),layer)
    if angle:
        layer=layer.rotate(angle,resample=Image.Resampling.BICUBIC,center=(cx,cy))
    canvas.alpha_composite(layer)


def _waveform(canvas, rng):
    cx,cy=WIDTH//2,660
    _glow(canvas,(cx,cy),270,(11,139,159),85)
    d=ImageDraw.Draw(canvas,"RGBA")
    for radius in (150,235,325):
        d.ellipse((cx-radius,cy-radius,cx+radius,cy+radius),outline=(95,190,194,52),width=2)
    points=[]
    for x in range(-8,WIDTH+9,4):
        t=x/WIDTH; envelope=.2+.8*math.sin(math.pi*t)**.7
        y=cy+(math.sin(t*math.tau*4.1)+.32*math.sin(t*math.tau*10.8))*205*envelope
        points.append((x,round(y)))
    d.line(points,fill=(5,14,25,230),width=23,joint="curve")
    d.line(points,fill=(232,178,98,235),width=7,joint="curve")
    for _ in range(42):
        x=rng.randint(25,WIDTH-25); h=rng.randint(18,180)
        d.rounded_rectangle((x-3,cy-h,x+3,cy+h),radius=3,fill=(105,194,194,rng.randint(35,100)))


def _mechanism(canvas, rng):
    cx,cy=WIDTH//2,650
    _glow(canvas,(cx,cy),280,(173,106,47),110)
    d=ImageDraw.Draw(canvas,"RGBA")
    for r,a,w in ((250,60,3),(190,95,5),(125,135,4),(62,175,3)):
        d.ellipse((cx-r,cy-r,cx+r,cy+r),outline=(232,180,103,a),width=w)
    for i in range(16):
        angle=math.tau*i/16
        x1,y1=cx+math.cos(angle)*72,cy+math.sin(angle)*72
        x2,y2=cx+math.cos(angle)*232,cy+math.sin(angle)*232
        d.line((x1,y1,x2,y2),fill=(114,197,187,95),width=3)
        x,y=cx+math.cos(angle)*252,cy+math.sin(angle)*252
        d.ellipse((x-8,y-8,x+8,y+8),fill=(240,188,109,235))
    for _ in range(28):
        a=rng.random()*math.tau; r=rng.randint(85,270)
        x,y=cx+math.cos(a)*r,cy+math.sin(a)*r
        d.ellipse((x-3,y-3,x+3,y+3),fill=(245,212,154,190))
    d.ellipse((cx-38,cy-38,cx+38,cy+38),fill=(227,174,91,245))
    d.ellipse((cx-19,cy-19,cx+19,cy+19),fill=(11,26,39,255))


def _melody(canvas, rng):
    _glow(canvas,(WIDTH//2,650),275,(29,116,144),95)
    d=ImageDraw.Draw(canvas,"RGBA")
    for track in range(5):
        y=470+track*95
        pts=[(x,round(y+28*math.sin(x/WIDTH*math.tau*1.7+track*.65))) for x in range(20,WIDTH-15,8)]
        d.line(pts,fill=(101,183,190,70),width=2)
    notes=[]
    for i in range(16):
        x=42+i*40; y=650+round(178*math.sin(i*.56))+rng.randint(-22,22)
        notes.append((x,y))
    for i,(x,y) in enumerate(notes):
        c=(242,191,115,235) if i%3==0 else (125,212,203,220)
        d.ellipse((x-11,y-7,x+11,y+7),fill=c)
        d.line((x+9,y,x+9,y-75-rng.randint(0,25)),fill=c,width=5)
    d.line(notes,fill=(215,167,102,150),width=3,joint="curve")


def render_scene_art(prompt: str, index: int, scene: dict[str, Any] | None = None,
                     plan: dict[str, Any] | None = None, target: str | Path | None = None,
                     width: int = WIDTH, height: int = HEIGHT) -> Path:
    """Render deterministic original scene artwork; no network or provider is required."""
    if not str(prompt or "").strip():
        raise ValueError("Scene-art prompt cannot be empty.")
    scene=scene if isinstance(scene,dict) else {}
    seed=_seed(prompt,scene,index); rng=random.Random(seed)
    canvas=_base(seed)
    _glow(canvas,(int(WIDTH*.55),int(HEIGHT*.42)),330,(8,119,131),78)
    _glow(canvas,(int(WIDTH*.31),int(HEIGHT*.64)),260,(128,73,37),58)
    d=ImageDraw.Draw(canvas,"RGBA")
    for _ in range(145):
        x=rng.randint(0,WIDTH-1); y=rng.randint(0,HEIGHT-1); r=rng.choice((1,1,2,3))
        d.ellipse((x-r,y-r,x+r,y+r),fill=(210,222,209,rng.randint(18,90)))
    cx,cy=WIDTH//2,int(HEIGHT*.51)
    for radius in (300,430,565):
        d.arc((cx-radius,cy-radius,cx+radius,cy+radius),205,338,fill=(183,156,113,42),width=2)
    mode=str(scene.get("visual_mode") or "").casefold()
    if any(x in mode for x in ("wave","audio","sound")):
        _waveform(canvas,rng)
    elif any(x in mode for x in ("mechanism","cutaway","physics")):
        _mechanism(canvas,rng)
    elif any(x in mode for x in ("melody","map","timeline")):
        _melody(canvas,rng)
    else:
        _violin(canvas,int(WIDTH*(.60 if index%2==0 else .43)),int(HEIGHT*.52),1.0,-8 if index%2==0 else 7)
        if index%3==1:
            _waveform(canvas,rng)
    vignette=Image.new("L",(WIDTH,HEIGHT),0)
    ImageDraw.Draw(vignette).ellipse((-120,-100,WIDTH+120,HEIGHT+100),fill=255)
    vignette=vignette.filter(ImageFilter.GaussianBlur(100))
    shade=Image.new("RGBA",(WIDTH,HEIGHT),(2,5,15,0))
    shade.putalpha(ImageOps.invert(vignette).point(lambda v:round(v*.75)))
    canvas=Image.alpha_composite(canvas,shade).convert("RGB")
    if (width,height)!=(WIDTH,HEIGHT):
        canvas=canvas.resize((width,height),Image.Resampling.LANCZOS)
    output=Path(target) if target else Path("work/images")/f"scene-{index+1}.jpg"
    output.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(output,"JPEG",quality=94,optimize=True,progressive=True)
    return output
