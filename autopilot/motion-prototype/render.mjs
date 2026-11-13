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
html,body{margin:0;padding:0;width:${width}px;height:${height}px;overflow:hidden;background:#100c0a}
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
  const GOLD = "#edc18a", IVORY = "#fff3e2", MUTED = "#cbb9a6", COPPER = "#c9795d", INK = "#100c0a";
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
    const eased = easeInOut(progress);
    const scale = Math.max(W / image.width, H / image.height) * (1 + 0.095 * eased);
    const drift = (sceneIndex % 2 === 0 ? -1 : 1) * (14 * eased + 5 * Math.sin(progress * Math.PI));
    const drawW = image.width * scale, drawH = image.height * scale;
    const dx = (W-drawW) / 2 + drift;
    const dy = (H-drawH)/2 + (sceneIndex === 1 ? -18 : 12) * eased;
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.filter = "saturate(0.88) sepia(0.18) contrast(1.07)";
    ctx.drawImage(image, dx, dy, drawW, drawH);
    ctx.filter = "none";
    const shade = ctx.createLinearGradient(0,0,0,H);
    shade.addColorStop(0,"rgba(13,8,7,.52)");
    shade.addColorStop(.35,"rgba(13,8,7,.03)");
    shade.addColorStop(.72,"rgba(13,8,7,.05)");
    shade.addColorStop(1,"rgba(9,6,5,.78)");
    ctx.fillStyle = shade;
    ctx.fillRect(0,0,W,H);
    ctx.fillStyle = "rgba(92,35,18,.10)";
    ctx.fillRect(0,0,W,H);
    ctx.restore();
  }

  function musicEnergyAt(time) {
    const values = Array.isArray(D.music_energy) ? D.music_energy : [];
    if (!values.length) return 0.34 + 0.18 * Math.sin(time * 2.1);
    const position = clamp(time / Math.max(0.001, Number(D.duration_seconds || 24)), 0, 0.999) * values.length;
    const lower = Math.floor(position);
    const upper = Math.min(values.length - 1, lower + 1);
    const mix = position - lower;
    return clamp(Number(values[lower] || 0) * (1 - mix) + Number(values[upper] || 0) * mix);
  }

  function drawAtmosphere(time, sceneIndex) {
    ctx.save();
    ctx.globalCompositeOperation = "screen";
    const glowX = W * (0.36 + 0.25 * Math.sin(time * 0.23 + sceneIndex));
    const glowY = H * (0.39 + 0.05 * Math.cos(time * 0.31));
    const glow = ctx.createRadialGradient(glowX,glowY,12,glowX,glowY,W*0.60);
    glow.addColorStop(0,"rgba(207,111,61,.13)");
    glow.addColorStop(.52,"rgba(166,78,42,.055)");
    glow.addColorStop(1,"rgba(166,78,42,0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0,0,W,H);

    for (let ring=0; ring<3; ring++) {
      const phase = time * (0.16 + ring * 0.025) + ring * 1.8;
      ctx.beginPath();
      ctx.ellipse(W*(0.72-0.08*ring),H*(0.44+0.035*ring),
        118+ring*54+12*Math.sin(time*.8+ring),220+ring*70,
        phase,0,Math.PI*2);
      ctx.strokeStyle = ring===0 ? "rgba(239,190,132,.18)" : "rgba(218,137,91,.10)";
      ctx.lineWidth = ring===0 ? 1.8 : 1;
      ctx.stroke();
    }

    for (let mote=0; mote<30; mote++) {
      const seed = mote * 17.17 + sceneIndex * 9.3;
      const x = (mote * 83.7 + 42 * Math.sin(time * (0.18 + mote%4*.035) + seed) + W) % W;
      const y = (mote * 47.3 - time * (8 + mote%5*3) + H * 2) % H;
      const radius = 1 + (mote%3) * .55;
      ctx.globalAlpha = .12 + .16 * (0.5 + 0.5 * Math.sin(time*1.6+seed));
      ctx.fillStyle = mote%4===0 ? "#f0c58a" : "#cf8761";
      ctx.beginPath();
      ctx.arc(x,y,radius,0,Math.PI*2);
      ctx.fill();
    }

    const sweep = (time * 78) % (W + 360) - 180;
    const beam = ctx.createLinearGradient(sweep-90,0,sweep+90,H);
    beam.addColorStop(0,"rgba(230,166,110,0)");
    beam.addColorStop(.48,"rgba(230,166,110,.045)");
    beam.addColorStop(1,"rgba(230,166,110,0)");
    ctx.globalAlpha = .7;
    ctx.fillStyle = beam;
    ctx.fillRect(0,0,W,H);
    ctx.restore();
  }

  function drawBowMotion(time, scene) {
    const subject = String(D.visual_motif || (D.title+" "+D.topic+" "+scene.caption+" "+scene.graphic_label)).toLowerCase();
    if (!/(violin|bow|string|music|performance|musician)/.test(subject)) return;
    const energy = musicEnergyAt(time);
    const strokeSpeed = 12.5 + energy * 8.5;
    const phase = time * strokeSpeed;
    const sweep = Math.sin(phase);
    const centerY = H * .585 + sweep * (17 + 24 * energy);
    const vibrato = 2.2 + energy * 4.2;

    ctx.save();
    ctx.globalCompositeOperation = "screen";
    ctx.lineCap = "round";
    ctx.globalAlpha = .14 + energy * .26;
    for (let string=0; string<4; string++) {
      const x = 230 + string * 67;
      ctx.beginPath();
      ctx.moveTo(x, H*.465);
      for (let step=0; step<=18; step++) {
        const y = H*.465 + step * (H*.205/18);
        const offset = Math.sin(time*34 + step*.75 + string*.9) * vibrato;
        if (step===0) ctx.moveTo(x+offset,y);
        else ctx.lineTo(x+offset,y);
      }
      ctx.strokeStyle = string===1 ? "rgba(255,226,177,.70)" : "rgba(226,190,143,.38)";
      ctx.lineWidth = string===1 ? 2.3 : 1.25;
      ctx.stroke();
    }

    ctx.globalAlpha = .18 + energy * .62;
    ctx.shadowColor = "rgba(255,207,145,.86)";
    ctx.shadowBlur = 12 + energy * 22;
    ctx.strokeStyle = "rgba(255,231,194,.92)";
    ctx.lineWidth = 2.2 + energy * 2.0;
    ctx.beginPath();
    ctx.moveTo(72,centerY-15);
    ctx.lineTo(W-72,centerY+18);
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.strokeStyle = "rgba(194,106,70,.78)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(82,centerY-22);
    ctx.lineTo(W-82,centerY+11);
    ctx.stroke();

    const sparkX = 80 + ((time * (190 + energy*220)) % (W-160));
    for (let spark=0; spark<5; spark++) {
      const px = sparkX - spark*13;
      const py = centerY + Math.sin(time*18+spark)*8;
      ctx.globalAlpha = (.18 + energy*.42) * (1-spark*.14);
      ctx.fillStyle = "#ffe4b7";
      ctx.beginPath();
      ctx.arc(px,py,1.4+energy*1.3,0,Math.PI*2);
      ctx.fill();
    }
    ctx.restore();
  }

  function drawBrand(sceneIndex, time) {
    ctx.save();
    ctx.fillStyle = GOLD;
    ctx.font = "800 18px Arial, sans-serif";
    ctx.fillText("VIOLIN PRINCE", 34, 48);
    ctx.textAlign = "right";
    ctx.fillStyle = "rgba(255,243,226,.78)";
    ctx.font = "600 12px Arial, sans-serif";
    ctx.fillText("MOTION STORY  /  " + String(sceneIndex+1).padStart(2,"0") + " OF 03", W-34, 47);
    ctx.textAlign = "left";
    ctx.strokeStyle = "rgba(237,193,138,.48)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(34,69);
    ctx.lineTo(W-34,69);
    ctx.stroke();
    ctx.globalAlpha = .45 + .18*Math.sin(time*1.4);
    ctx.beginPath();
    ctx.arc(34,69,2.5,0,Math.PI*2);
    ctx.fillStyle = GOLD;
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.fillStyle = "rgba(255,243,226,.74)";
    ctx.font = "500 12px Arial, sans-serif";
    ctx.fillText("ORIGINAL STORY  •  ORIGINAL SOUNDTRACK",34,1212);
    ctx.textAlign = "right";
    ctx.fillText("VIOLIN PRINCE",W-34,1212);
    ctx.restore();
  }

  function drawGraphic(scene, index, time, start, sceneDuration, alpha=1) {
    const local = time - start;
    const enter = easeOut(local / .58);
    const leave = 1 - easeInOut((local - (sceneDuration-.62)) / .62);
    const opacity = clamp(Math.min(enter, leave)) * alpha;
    if (opacity <= 0) return;

    const yShift = 30 * (1-enter);
    const top = 118 + yShift;
    const label = String(scene.graphic_label || ("STORY BEAT " + (index+1))).toUpperCase();
    const headline = String(scene.caption || D.title || "");
    const detail = String(scene.graphic_detail || "");
    const accent = index===1 ? COPPER : GOLD;

    ctx.save();
    ctx.globalAlpha = opacity;
    const fade = ctx.createLinearGradient(0,top-32,0,top+290);
    fade.addColorStop(0,"rgba(12,8,7,.78)");
    fade.addColorStop(.72,"rgba(12,8,7,.32)");
    fade.addColorStop(1,"rgba(12,8,7,0)");
    ctx.fillStyle = fade;
    ctx.fillRect(0,top-34,W,330);

    ctx.fillStyle = accent;
    ctx.font = "800 14px Arial, sans-serif";
    ctx.fillText(String(index+1).padStart(2,"0") + "   /   " + label.slice(0,38),42,top+22);

    ctx.fillStyle = IVORY;
    ctx.font = "700 39px Georgia, serif";
    const headlineLines = wrap(headline,W-92,"700 39px Georgia, serif");
    headlineLines.forEach((line,row)=>ctx.fillText(line,42,top+82+row*48));

    ctx.fillStyle = MUTED;
    ctx.font = "500 17px Arial, sans-serif";
    const detailLines = wrap(detail,W-92,"500 17px Arial, sans-serif");
    const detailY = top + 104 + headlineLines.length*43;
    detailLines.forEach((line,row)=>ctx.fillText(line,44,detailY+row*24));

    const graphY = Math.min(top+240+Math.max(0,headlineLines.length-1)*13, top+282);
    const graphLeft = 44;
    const graphRight = W-44;
    const progress = clamp(local / Math.max(1,sceneDuration));
    ctx.strokeStyle = "rgba(237,193,138,.44)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(graphLeft,graphY);
    ctx.lineTo(graphRight,graphY);
    ctx.stroke();

    if (scene.comparison && scene.comparison.left_label && scene.comparison.right_label) {
      const gap=22, colW=(W-110-gap)/2, topY=graphY-26;
      const leftX=45, rightX=leftX+colW+gap;
      for (const [x,item] of [
        [leftX,{label:scene.comparison.left_label,detail:scene.comparison.left_detail}],
        [rightX,{label:scene.comparison.right_label,detail:scene.comparison.right_detail}]
      ]) {
        ctx.fillStyle="rgba(255,243,226,.08)";
        roundRect(x,topY,colW,90,12);ctx.fill();
        ctx.fillStyle=IVORY;ctx.font="700 19px Arial, sans-serif";
        ctx.fillText(String(item.label||"").slice(0,22),x+14,topY+31);
        ctx.fillStyle=MUTED;ctx.font="14px Arial, sans-serif";
        wrap(item.detail||"",colW-28,"14px Arial, sans-serif").forEach((line,row)=>ctx.fillText(line,x+14,topY+56+row*18));
      }
    } else if (index===0) {
      // Animated editorial spectrum: visual rhythm, not invented numerical data.
      for (let bar=0;bar<24;bar++) {
        const phase = time*3.6 + bar*.42;
        const barH = 7 + (12+18*Math.abs(Math.sin(phase)))*(.45+.55*progress);
        const x = 48 + bar*26;
        ctx.fillStyle = bar%4===0 ? accent : "rgba(237,193,138,.48)";
        roundRect(x,graphY-barH,13,barH,5);
        ctx.fill();
      }
      const pulseX = graphLeft + progress*(graphRight-graphLeft);
      ctx.fillStyle = IVORY;
      ctx.shadowColor = accent;ctx.shadowBlur = 14;
      ctx.beginPath();ctx.arc(pulseX,graphY,4.5,0,Math.PI*2);ctx.fill();
      ctx.shadowBlur = 0;
    } else if (index===1) {
      // Three-stage connector motif, animated as a travelling highlight.
      const labels = ["DETAIL","CONTROL","EXPRESSION"];
      const spacing = (graphRight-graphLeft)/2;
      ctx.strokeStyle="rgba(237,193,138,.48)";
      ctx.lineWidth=2;
      ctx.beginPath();ctx.moveTo(graphLeft,graphY);ctx.lineTo(graphRight,graphY);ctx.stroke();
      for(let node=0;node<3;node++){
        const nx=graphLeft+spacing*node;
        ctx.fillStyle=progress>=node/2 ? accent : "rgba(203,185,166,.58)";
        ctx.beginPath();ctx.arc(nx,graphY,5.5,0,Math.PI*2);ctx.fill();
        ctx.fillStyle=IVORY;ctx.font="700 11px Arial, sans-serif";
        ctx.textAlign="center";ctx.fillText(labels[node],nx,graphY+23);
      }
      ctx.textAlign="left";
      const movingX=graphLeft+progress*(graphRight-graphLeft);
      ctx.fillStyle=IVORY;ctx.shadowColor=accent;ctx.shadowBlur=16;
      ctx.beginPath();ctx.arc(movingX,graphY,4,0,Math.PI*2);ctx.fill();
      ctx.shadowBlur=0;
    } else {
      // Crescendo waveform with an animated travelling light.
      ctx.beginPath();
      for(let point=0;point<=72;point++){
        const x=graphLeft+(graphRight-graphLeft)*point/72;
        const envelope=.25+.75*Math.sin(Math.PI*point/72);
        const y=graphY-17*Math.sin(point*.42-time*4.2)*envelope;
        if(point===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
      }
      ctx.strokeStyle=accent;ctx.lineWidth=2.2;ctx.stroke();
      const movingX=graphLeft+progress*(graphRight-graphLeft);
      ctx.fillStyle=IVORY;ctx.shadowColor=accent;ctx.shadowBlur=18;
      ctx.beginPath();ctx.arc(movingX,graphY-16*Math.sin(progress*72*.42-time*4.2)*(.25+.75*Math.sin(Math.PI*progress)),5,0,Math.PI*2);ctx.fill();
      ctx.shadowBlur=0;
      for(let ring=0;ring<3;ring++){
        ctx.beginPath();ctx.arc(graphRight-7,graphY,10+ring*9+8*Math.sin(time*2.2+ring),0,Math.PI*2);
        ctx.strokeStyle="rgba(237,193,138,"+(0.30-ring*.07)+")";ctx.lineWidth=1.2;ctx.stroke();
      }
    }
    ctx.restore();
  }

  function drawSceneTransition(time, transitionAt, duration) {
    const progress = easeInOut((time-transitionAt)/duration);
    const center = -W*.25 + progress*W*1.55;
    ctx.save();
    ctx.globalCompositeOperation = "screen";
    const beam = ctx.createLinearGradient(center-105,0,center+105,H);
    beam.addColorStop(0,"rgba(244,192,128,0)");
    beam.addColorStop(.42,"rgba(244,192,128,.02)");
    beam.addColorStop(.50,"rgba(255,233,197,.25)");
    beam.addColorStop(.58,"rgba(244,192,128,.025)");
    beam.addColorStop(1,"rgba(244,192,128,0)");
    ctx.fillStyle = beam;
    ctx.fillRect(0,0,W,H);
    ctx.restore();
  }

  const STOP = new Set(["a","an","and","are","as","at","be","by","for","from","in","into","is","it","of","on","or","that","the","this","to","was","were","with"]);
  const CAPTION_STYLES = ["bounce","serif","outline","underline","tilt","typewriter","glow","editorial"];

  function styleForWord(word,index) {
    if (/[!?]$/.test(word)) return "impact";
    if (/[,;:]$/.test(word)) return "editorial";
    return CAPTION_STYLES[index % CAPTION_STYLES.length];
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
    if(time > Number(active.end)+.14) return;
    const recent=words.slice(Math.max(0,found-2),found);
    const duration=Math.max(.08,Number(active.end)-Number(active.start));
    const progress=clamp((time-Number(active.start))/Math.min(.24,duration));
    const eased=easeOut(progress);
    const style=styleForWord(String(active.text||""),found);
    const textValue=String(active.text||"");
    const maxWidth=W-72;
    const fontSize=Math.max(38,Math.min(72,Math.floor(650/Math.max(5,textValue.length))));
    const isImportant=!STOP.has(textValue.toLowerCase().replace(/[^\p{L}\p{N}]/gu,""));
    const accent=isImportant ? (found%5===0 ? COPPER : GOLD) : IVORY;

    ctx.save();
    ctx.textAlign="center";
    ctx.textBaseline="middle";

    if (recent.length) {
      const context=recent.map(cue=>String(cue.text||"")).join("  ");
      ctx.font="600 21px Arial, sans-serif";
      ctx.fillStyle="rgba(255,243,226,.68)";
      ctx.shadowColor="rgba(0,0,0,.42)";
      ctx.shadowBlur=8;
      ctx.fillText(context,W/2,954,maxWidth);
      ctx.shadowBlur=0;
    }

    let x=W/2, y=1022, sx=1, sy=1, rotation=0;
    if(style==="bounce"){
      const bounce= Math.sin(progress*Math.PI)*.10;
      sx=.82+.18*eased+bounce; sy=.82+.18*eased+bounce;
      y-=18*(1-eased);
    } else if(style==="serif" || style==="editorial"){
      y-=8*(1-eased);
    } else if(style==="outline"){
      sx=.88+.12*eased; sy=.88+.12*eased;
    } else if(style==="underline"){
      y-=7*(1-eased);
    } else if(style==="tilt" || style==="impact"){
      rotation=(style==="impact" ? -.045 : .025)*(1-eased);
      sx=.72+.28*eased; sy=.78+.22*eased;
    } else if(style==="typewriter"){
      sx=.98+.02*eased;
    } else if(style==="glow"){
      sx=.90+.10*eased;
      sy=.90+.10*eased;
    }

    ctx.translate(x,y);
    ctx.rotate(rotation);
    ctx.scale(sx,sy);
    const family=(style==="serif" || style==="editorial") ? "Georgia, serif" : "Arial, sans-serif";
    const weight=style==="serif" ? "italic 700 " : "900 ";
    ctx.font=weight+fontSize+"px "+family;
    ctx.lineJoin="round";
    ctx.shadowColor=style==="glow" ? "rgba(237,193,138,.95)" : "rgba(0,0,0,.72)";
    ctx.shadowBlur=style==="glow" ? 25 : 14;
    ctx.lineWidth=style==="outline" || style==="impact" ? 4 : 1;
    ctx.strokeStyle="rgba(19,10,8,.90)";

    let visibleText=textValue;
    if(style==="typewriter"){
      const count=Math.max(1,Math.ceil(textValue.length*easeOut((time-Number(active.start)) / Math.max(.12,duration*.68))));
      visibleText=textValue.slice(0,count);
    }
    if(style==="outline" || style==="impact") ctx.strokeText(visibleText,0,0,maxWidth);
    ctx.fillStyle=style==="impact" ? IVORY : accent;
    ctx.fillText(visibleText,0,0,maxWidth);

    ctx.shadowBlur=0;
    if(style==="underline" || style==="editorial" || style==="impact"){
      const measured=Math.min(maxWidth,ctx.measureText(visibleText).width);
      const underlineProgress=style==="impact" ? eased : easeOut((time-Number(active.start))/.20);
      ctx.strokeStyle=style==="impact" ? COPPER : GOLD;
      ctx.lineWidth=style==="impact" ? 4 : 2.4;
      ctx.beginPath();
      ctx.moveTo(-measured/2,1064-y);
      ctx.lineTo(-measured/2+measured*underlineProgress,1064-y);
      ctx.stroke();
    }
    if(style==="bounce" || style==="glow"){
      const measured=Math.min(maxWidth,ctx.measureText(visibleText).width);
      ctx.globalAlpha=.56;
      ctx.strokeStyle=accent;ctx.lineWidth=1.5;
      ctx.beginPath();ctx.moveTo(-measured/2,39);ctx.lineTo(measured/2,39);ctx.stroke();
    }
    ctx.restore();

    // A thin audio-reactive pulse, independent of the subtitle treatment.
    const energy=musicEnergyAt(time);
    const pulseWidth=140+energy*260;
    ctx.save();
    ctx.globalAlpha=.18+energy*.30;
    ctx.strokeStyle=GOLD;ctx.lineWidth=1.6;
    ctx.beginPath();ctx.moveTo(W/2-pulseWidth/2,1100);ctx.lineTo(W/2+pulseWidth/2,1100);ctx.stroke();
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
    const transition=.72;
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
    drawAtmosphere(time,index);
    drawBowMotion(time,scene);
    if(index<scenes.length-1 && time>=transitionAt) drawSceneTransition(time,transitionAt,transition);
    drawBrand(index,time);
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
