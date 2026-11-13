#!/usr/bin/env node
/**
 * Isolated V3 renderer experiment.
 * HTML Canvas is rendered deterministically by Playwright, then encoded by FFmpeg.
 * The production Python/FFmpeg renderer remains untouched.
 */
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { chromium } from "playwright";

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) {
  throw new Error("Usage: node render.mjs <input.json> <silent-output.mp4>");
}

const data = JSON.parse(await fs.readFile(inputPath, "utf8"));
const width = Number(data.width || 720);
const height = Number(data.height || 1280);
const fps = Number(data.fps || 25);
const duration = Number(data.duration_seconds || 24);
const frames = Math.round(fps * duration);
if (!Array.isArray(data.scenes) || data.scenes.length !== 3) {
  throw new Error("V3 prototype requires exactly three prepared scene images.");
}
if (!Array.isArray(data.word_cues) || data.word_cues.length < 10) {
  throw new Error("V3 prototype requires native word-level narration timestamps.");
}
for (const scene of data.scenes) {
  if (!scene.image_b64) throw new Error("A scene image is missing from the HTML renderer input.");
}

const safeJson = JSON.stringify(data).replaceAll("<", "\\u003c");
const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
html,body{margin:0;padding:0;width:${width}px;height:${height}px;overflow:hidden;background:#070d18}
#stage{display:block;width:${width}px;height:${height}px}
</style>
</head>
<body>
<canvas id="stage" width="${width}" height="${height}"></canvas>
<script>
window.__DATA__ = ${safeJson};
(() => {
  const D = window.__DATA__;
  const canvas = document.getElementById("stage");
  const ctx = canvas.getContext("2d", { alpha: false });
  const W = D.width, H = D.height;
  const GOLD = "#ebca8b", IVORY = "#fffaf1", MUTED = "#bec8d7";
  const images = D.scenes.map(scene => {
    const image = new Image();
    image.src = "data:image/jpeg;base64," + scene.image_b64;
    return image;
  });
  const ready = Promise.all(images.map(image => image.decode()));
  const clamp = (value, low=0, high=1) => Math.max(low, Math.min(high, value));
  const easeOut = value => 1 - Math.pow(1 - clamp(value), 3);
  const easeInOut = value => {
    const x = clamp(value);
    return x < 0.5 ? 4*x*x*x : 1 - Math.pow(-2*x+2,3)/2;
  };
  const roundRect = (x,y,w,h,r) => {
    ctx.beginPath();
    ctx.roundRect(x,y,w,h,r);
  };
  const wrap = (text, maxWidth, font) => {
    ctx.font = font;
    const words = String(text || "").split(/\s+/).filter(Boolean);
    const lines = [];
    let line = "";
    for (const word of words) {
      const candidate = line ? line + " " + word : word;
      if (line && ctx.measureText(candidate).width > maxWidth) {
        lines.push(line);
        line = word;
      } else line = candidate;
    }
    if (line) lines.push(line);
    return lines.slice(0, 2);
  };

  function drawBase(sceneIndex, progress, alpha=1) {
    const image = images[sceneIndex];
    const scale = Math.max(W / image.width, H / image.height) * (1 + 0.055 * easeInOut(progress));
    const drawW = image.width * scale, drawH = image.height * scale;
    const drift = (sceneIndex % 2 === 0 ? -1 : 1) * 18 * easeInOut(progress);
    const dx = (W-drawW)/2 + drift;
    const dy = (H-drawH)/2 + (sceneIndex === 1 ? -10 : 7) * easeInOut(progress);
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.drawImage(image, dx, dy, drawW, drawH);
    const shade = ctx.createLinearGradient(0,0,0,H);
    shade.addColorStop(0,"rgba(4,9,17,.40)");
    shade.addColorStop(.54,"rgba(4,9,17,.02)");
    shade.addColorStop(1,"rgba(4,9,17,.76)");
    ctx.fillStyle = shade;
    ctx.fillRect(0,0,W,H);
    ctx.restore();
  }

  function drawBrand(sceneIndex) {
    ctx.save();
    ctx.fillStyle = GOLD;
    ctx.font = "700 20px Arial, sans-serif";
    ctx.fillText("VIOLIN PRINCE", 34, 49);
    ctx.strokeStyle = "rgba(235,202,139,.62)";
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(34,72); ctx.lineTo(W-34,72); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(34,1190); ctx.lineTo(W-34,1190); ctx.stroke();
    ctx.fillStyle = "rgba(255,250,241,.88)";
    ctx.font = "500 13px Arial, sans-serif";
    ctx.fillText("ORIGINAL STORY  •  ORIGINAL SOUNDTRACK",34,1212);
    ctx.textAlign = "right";
    ctx.fillText(String(sceneIndex+1).padStart(2,"0") + " / 03",W-34,1212);
    ctx.restore();
  }

  function drawGraphic(scene, index, time, start, sceneDuration, alpha=1) {
    const local = time - start;
    const enter = easeOut(local / .42);
    const leave = 1 - easeInOut((local - (sceneDuration-.44)) / .44);
    const opacity = clamp(Math.min(enter, leave)) * alpha;
    if (opacity <= 0) return;
    const yShift = 24 * (1-enter);
    const x = 42, y = 150 + yShift, w = W-84;
    ctx.save();
    ctx.globalAlpha = opacity;
    ctx.shadowColor = "rgba(0,0,0,.30)";
    ctx.shadowBlur = 22;
    ctx.fillStyle = "rgba(7,13,24,.86)";
    ctx.strokeStyle = "rgba(235,202,139,.78)";
    ctx.lineWidth = 1.6;
    roundRect(x,y,w,scene.comparison ? 236 : 220,24);
    ctx.fill(); ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.fillStyle = GOLD;
    roundRect(x+20,y+22,7,172,4); ctx.fill();
    const label = String(scene.graphic_label || ("STORY BEAT " + (index+1))).toUpperCase();
    ctx.font = "700 16px Arial, sans-serif";
    ctx.fillStyle = GOLD;
    ctx.fillText(String(index+1).padStart(2,"0") + " / 03     " + label.slice(0,34), x+48,y+47);

    if (scene.comparison && scene.comparison.left_label && scene.comparison.right_label) {
      const top = y+70, gap=14, colW=(w-78-gap)/2;
      const leftX=x+48, rightX=leftX+colW+gap;
      for (const [cx, item] of [[leftX,scene.comparison.left],[rightX,scene.comparison.right]]) {
        ctx.fillStyle = "rgba(255,255,255,.055)";
        roundRect(cx,top,colW,130,12); ctx.fill();
        ctx.fillStyle = IVORY; ctx.font = "700 21px Arial, sans-serif";
        ctx.fillText(String(item?.label || "DETAIL").slice(0,24),cx+14,top+34);
        ctx.fillStyle = MUTED; ctx.font = "16px Arial, sans-serif";
        const lines=wrap(item?.detail || "",colW-28,"16px Arial, sans-serif");
        lines.forEach((line,j)=>ctx.fillText(line,cx+14,top+66+j*22));
      }
    } else {
      ctx.fillStyle = IVORY;
      ctx.font = "700 30px Arial, sans-serif";
      const headline = wrap(scene.caption || D.title || "",w-98,"700 30px Arial, sans-serif");
      headline.forEach((line,j)=>ctx.fillText(line,x+48,y+92+j*38));
      ctx.fillStyle = MUTED;
      ctx.font = "17px Arial, sans-serif";
      const detail = wrap(scene.graphic_detail || "",w-98,"17px Arial, sans-serif");
      const detailY = y + (headline.length>1 ? 164 : 146);
      detail.forEach((line,j)=>ctx.fillText(line,x+48,detailY+j*23));
      // Three abstract progress nodes; no unsupported numeric data is implied.
      const lineY=y+198;
      ctx.strokeStyle="rgba(235,202,139,.42)";
      ctx.lineWidth=2; ctx.beginPath(); ctx.moveTo(W-152,lineY); ctx.lineTo(W-67,lineY); ctx.stroke();
      for(let dot=0;dot<3;dot++){
        ctx.fillStyle=dot<=index?GOLD:"rgba(150,164,183,.8)";
        ctx.beginPath(); ctx.arc(W-152+dot*42.5,lineY,5,0,Math.PI*2); ctx.fill();
      }
    }
    ctx.restore();
  }

  const STOP = new Set(["a","an","and","are","as","at","be","by","for","from","in","into","is","it","of","on","or","that","the","this","to","was","were","with"]);
  function presetFor(word,index) {
    const clean = String(word).replace(/[^\p{L}\p{N}]/gu,"");
    if (/[!?]$/.test(word)) return "snap";
    if (clean.length >= 7 && !STOP.has(clean.toLowerCase())) return "impact";
    return ["slide","rise","snap","pop"][index%4];
  }

  function drawCaptions(time) {
    const words = D.word_cues;
    let lo=0, hi=words.length-1, found=-1;
    while(lo<=hi){
      const mid=(lo+hi)>>1;
      if(Number(words[mid].start)<=time){found=mid;lo=mid+1;}else hi=mid-1;
    }
    if(found<0) return;
    const active=words[found];
    if(time > Number(active.end)+.16) return;
    const recent=words.slice(Math.max(0,found-2),found+1);
    const activeProgress=easeOut((time-Number(active.start))/.16);
    const baseline=1000;
    ctx.save();
    ctx.textBaseline="middle";
    ctx.textAlign="left";
    const segments=recent.map((cue,i)=>({
      text:String(cue.text || ""),
      active:i===recent.length-1,
      index:found-(recent.length-1-i),
      cue
    }));
    const widths=segments.map(segment=>{
      const size=segment.active ? (segment.text.length>12?48:62) : 27;
      ctx.font=(segment.active?"800 ":"600 ")+size+"px Arial, sans-serif";
      return ctx.measureText(segment.text).width + (segment.active?20:13);
    });
    const total=widths.reduce((a,b)=>a+b,0);
    const scale=Math.min(1,(W-68)/Math.max(total,1));
    let cursor=(W-total*scale)/2;
    for(let i=0;i<segments.length;i++){
      const segment=segments[i], isActive=segment.active;
      const size=isActive?(segment.text.length>12?48:62):27;
      const preset=presetFor(segment.text,segment.index);
      let sx=1, sy=1, dy=0, dx=0, rotation=0;
      if(isActive){
        if(preset==="slide"){dx=-34*(1-activeProgress);dy=8*(1-activeProgress);sx=.94+.06*activeProgress;}
        else if(preset==="rise"){dy=30*(1-activeProgress);sx=.98+.02*activeProgress;}
        else if(preset==="snap"){sx=.70+.34*activeProgress;sy=.70+.34*activeProgress;rotation=-.025*(1-activeProgress);}
        else if(preset==="impact"){sx=.78+.22*activeProgress;sy=.78+.22*activeProgress;}
        else {sx=.82+.18*activeProgress;sy=.82+.18*activeProgress;}
      }
      ctx.save();
      ctx.translate(cursor+widths[i]*scale/2,baseline+dy);
      ctx.scale(sx*scale,sy);
      ctx.rotate(rotation);
      ctx.font=(isActive?"800 ":"600 ")+size+"px Arial, sans-serif";
      ctx.textAlign="center";
      ctx.fillStyle=isActive && !STOP.has(segment.text.toLowerCase())?GOLD:(isActive?IVORY:"rgba(255,250,241,.76)");
      ctx.shadowColor=isActive?"rgba(0,0,0,.60)":"transparent";
      ctx.shadowBlur=isActive?16:0;
      ctx.lineWidth=isActive?2:0;
      if(isActive && preset==="impact"){
        ctx.strokeStyle="rgba(7,13,24,.88)";
        ctx.strokeText(segment.text,0,0);
      }
      ctx.fillText(segment.text,0,0);
      ctx.restore();
      cursor+=widths[i]*scale;
    }
    // A fine gold baseline reacts to the active word without boxing in the caption.
    ctx.globalAlpha=.78;
    ctx.strokeStyle=GOLD; ctx.lineWidth=2;
    ctx.beginPath();ctx.moveTo(Math.max(76,(W-total*scale)/2),1054);
    ctx.lineTo(Math.min(W-76,(W+total*scale)/2),1054);ctx.stroke();
    ctx.restore();
  }

  window.__READY__ = ready;
  window.renderAt = async function(time) {
    await ready;
    const scenes=D.scenes;
    let index=0;
    for(let i=0;i<scenes.length-1;i++){
      if(time>=Number(scenes[i].start)+Number(scenes[i].duration)) index=i+1;
      else break;
    }
    index=Math.min(index,scenes.length-1);
    const scene=scenes[index];
    const local=clamp((time-Number(scene.start))/Number(scene.duration));
    ctx.clearRect(0,0,W,H);
    const transition=.36;
    const transitionAt=Number(scene.start)+Number(scene.duration)-transition;
    if(index<scenes.length-1 && time>=transitionAt){
      const p=easeInOut((time-transitionAt)/transition);
      drawBase(index,local,1-p);
      drawBase(index+1,0,p);
      drawGraphic(scene,index,time,Number(scene.start),Number(scene.duration),1-p);
    } else {
      drawBase(index,local,1);
      drawGraphic(scene,index,time,Number(scene.start),Number(scene.duration),1);
    }
    drawBrand(index);
    drawCaptions(time);
    if(time>D.duration_seconds-.40){
      const fade=clamp((time-(D.duration_seconds-.40))/.40);
      ctx.fillStyle="rgba(4,8,15,"+fade+")";ctx.fillRect(0,0,W,H);
    }
  };
})();
</script>
</body>
</html>`;

const browser = await chromium.launch({ headless: true, args: ["--no-sandbox", "--disable-dev-shm-usage"] });
try {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  await page.setContent(html, { waitUntil: "load" });
  await page.evaluate(async () => await window.__READY__);
  await fs.mkdir(path.dirname(outputPath), { recursive: true });

  const ffmpeg = spawn("ffmpeg", [
    "-y", "-hide_banner", "-loglevel", "error",
    "-f", "image2pipe", "-vcodec", "png", "-framerate", String(fps), "-i", "pipe:0",
    "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
    "-pix_fmt", "yuv420p", "-movflags", "+faststart", outputPath
  ], { stdio: ["pipe", "inherit", "inherit"] });

  const sampleTimes = [2.5, 7.5, 13.5, 19.5];
  const sampleSet = new Set(sampleTimes.map(value => Math.min(frames-1, Math.round(value*fps))));
  const sampleDir = path.join(path.dirname(outputPath), "qa-frames");
  await fs.mkdir(sampleDir, { recursive: true });

  try {
    for (let frame=0; frame<frames; frame++) {
      const time=frame/fps;
      await page.evaluate(async value => await window.renderAt(value), time);
      const png=await page.locator("#stage").screenshot({ type:"png", animations:"disabled" });
      if (sampleSet.has(frame)) {
        const stamp=String(time.toFixed(1)).replace(".","p");
        await fs.writeFile(path.join(sampleDir,`frame-${stamp}s.png`),png);
      }
      if (!ffmpeg.stdin.write(png)) await once(ffmpeg.stdin,"drain");
    }
    ffmpeg.stdin.end();
    const [code] = await once(ffmpeg,"close");
    if (code !== 0) throw new Error(`FFmpeg exited with code ${code}`);
  } catch (error) {
    ffmpeg.kill("SIGTERM");
    throw error;
  }
  const stat=await fs.stat(outputPath);
  if (stat.size < 100000) throw new Error("HTML renderer output is unexpectedly small.");
  console.log(JSON.stringify({frames,fps,duration_seconds:duration,output:outputPath,bytes:stat.size,renderer:"HTML Canvas + Playwright + FFmpeg"}));
} finally {
  await browser.close();
}
