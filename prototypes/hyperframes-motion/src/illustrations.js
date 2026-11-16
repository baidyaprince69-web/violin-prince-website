const SVG_NS = "http://www.w3.org/2000/svg";

function svgNode(tag, attributes = {}, parent = null) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value !== undefined && value !== null) node.setAttribute(key, String(value));
  }
  if (parent) parent.appendChild(node);
  return node;
}

function svgText(parent, x, y, value, size = 15, color = "#e8edf6", extra = {}) {
  const node = svgNode("text", {
    x, y, fill: color, "font-size": size, "font-family": "Arial, Helvetica, sans-serif",
    "font-weight": 700, "letter-spacing": 1.4, ...extra
  }, parent);
  node.textContent = String(value || "");
  return node;
}

function addDefs(svg) {
  const defs = svgNode("defs", {}, svg);
  const bg = svgNode("linearGradient", {id:"vp-scene-bg",x1:"0",y1:"0",x2:"1",y2:"1"}, defs);
  svgNode("stop", {offset:"0%","stop-color":"#17243d"}, bg);
  svgNode("stop", {offset:"100%","stop-color":"#080d1b"}, bg);
  const gold = svgNode("linearGradient", {id:"vp-scene-gold",x1:"0",y1:"0",x2:"1",y2:"1"}, defs);
  svgNode("stop", {offset:"0%","stop-color":"#f6dfb7"}, gold);
  svgNode("stop", {offset:"100%","stop-color":"#b9894f"}, gold);
  const teal = svgNode("linearGradient", {id:"vp-scene-teal",x1:"0",y1:"0",x2:"1",y2:"0"}, defs);
  svgNode("stop", {offset:"0%","stop-color":"#5ad0c3","stop-opacity":"0.18"}, teal);
  svgNode("stop", {offset:"100%","stop-color":"#5ad0c3","stop-opacity":"0.92"}, teal);
  const glow = svgNode("filter", {id:"vp-scene-glow",x:"-60%",y:"-60%",width:"220%",height:"220%"}, defs);
  svgNode("feGaussianBlur", {stdDeviation:"5",result:"blur"}, glow);
  const merge = svgNode("feMerge", {}, glow);
  svgNode("feMergeNode", {in:"blur"}, merge);
  svgNode("feMergeNode", {in:"SourceGraphic"}, merge);
}

function addPanel(svg) {
  svgNode("rect", {x:9,y:8,width:882,height:364,rx:28,fill:"url(#vp-scene-bg)",stroke:"rgba(214,190,151,0.34)","stroke-width":1.5}, svg);
  svgNode("path", {d:"M30 305 C180 270 260 340 420 305 S690 270 870 310",fill:"none",stroke:"rgba(112,151,190,0.16)","stroke-width":1}, svg);
  for(let i=0;i<7;i+=1) svgNode("circle",{cx:70+i*128,cy:35+(i%2)*18,r:2+(i%3),fill:i%2?"#70cfc4":"#d8bd91","fill-opacity":0.25+(i%3)*0.08},svg);
}

function addSpeaker(parent,x,y,scale=1) {
  const g=svgNode("g",{transform:`translate(${x} ${y}) scale(${scale})`},parent);
  svgNode("rect",{x:0,y:0,width:66,height:112,rx:10,fill:"#111b30",stroke:"#d8bd91","stroke-opacity":0.72,"stroke-width":2},g);
  svgNode("rect",{x:7,y:8,width:52,height:96,rx:7,fill:"#24314b",stroke:"#6b7e9a","stroke-opacity":0.65},g);
  svgNode("circle",{cx:33,cy:38,r:11,fill:"#111b30",stroke:"#d8bd91","stroke-width":2},g);
  svgNode("circle",{cx:33,cy:77,r:20,fill:"#0b1325",stroke:"#70cfc4","stroke-opacity":0.75,"stroke-width":2},g);
  svgNode("circle",{cx:33,cy:77,r:8,fill:"#b9894f","fill-opacity":0.65},g);
  return g;
}

function buildRoom(svg) {
  const room=svgNode("g",{class:"room-art"},svg);
  svgNode("path",{d:"M78 65 L822 65 L850 263 L50 263 Z",fill:"#192944",stroke:"#72839e","stroke-opacity":0.38,"stroke-width":2},room);
  svgNode("path",{d:"M50 263 L850 263 L800 342 L100 342 Z",fill:"#111c31",stroke:"#8b9ab1","stroke-opacity":0.22,"stroke-width":1.5},room);
  for(let i=0;i<8;i+=1){const x=130+i*90;svgNode("path",{d:`M${x} 67 L${x-18} 262`,stroke:"#9aa8bd","stroke-opacity":0.08,"stroke-width":1},room);}
  addSpeaker(room,118,135,1.02);addSpeaker(room,710,135,1.02);
  svgText(room,117,125,"LEFT MONITOR",10,"#d8bd91");
  svgText(room,706,125,"RIGHT MONITOR",10,"#d8bd91");
  svgNode("path",{d:"M90 275 L810 275",stroke:"#d8bd91","stroke-opacity":0.25,"stroke-width":2},room);
  svgNode("path",{d:"M155 290 L745 290",stroke:"#6d819e","stroke-opacity":0.2,"stroke-width":1},room);
  const waves=svgNode("g",{class:"room-wave-group"},room);
  [
    "M188 186 C250 125 330 130 390 190",
    "M188 186 C270 95 365 100 435 190",
    "M710 186 C650 125 570 130 510 190",
    "M710 186 C630 95 535 100 465 190",
    "M250 208 C330 260 570 260 650 208"
  ].forEach((d,i)=>svgNode("path",{d,class:"sound-wave",fill:"none",stroke:i%2?"#70cfc4":"#d8bd91","stroke-width":i===4?2:2.4,"stroke-linecap":"round","stroke-dasharray":"8 13","stroke-opacity":0.68},waves));
  const person=svgNode("g",{class:"listener-character"},room);
  svgNode("circle",{cx:585,cy:155,r:24,fill:"#b9894f",stroke:"#f0d9b0","stroke-width":2},person);
  svgNode("path",{d:"M563 151 Q565 119 595 128 Q607 137 609 155 Q594 144 581 145 Z",fill:"#111827"},person);
  svgNode("path",{d:"M565 188 Q586 173 608 190 L628 267 L549 267 Z",fill:"#314766",stroke:"#8da3c6","stroke-width":2},person);
  svgNode("path",{d:"M566 211 Q530 218 503 244 L493 252",fill:"none",stroke:"#d9b88c","stroke-width":13,"stroke-linecap":"round"},person);
  svgNode("path",{d:"M594 210 Q632 218 651 243",fill:"none",stroke:"#d9b88c","stroke-width":12,"stroke-linecap":"round"},person);
  svgNode("path",{d:"M562 264 L550 321 M613 264 L627 321",fill:"none",stroke:"#101a2b","stroke-width":16,"stroke-linecap":"round"},person);
  svgNode("path",{d:"M533 324 L568 324 M610 324 L645 324",fill:"none",stroke:"#b9894f","stroke-width":8,"stroke-linecap":"round"},person);
  const mic=svgNode("g",{class:"microphone"},room);
  svgNode("path",{d:"M448 220 L448 306 M425 306 L471 306",stroke:"#d8bd91","stroke-width":3,"stroke-linecap":"round"},mic);
  svgNode("rect",{x:438,y:178,width:20,height:48,rx:10,fill:"#d8bd91",stroke:"#fff1d6","stroke-width":2},mic);
  svgNode("path",{d:"M442 190 L442 213 M448 190 L448 213 M454 190 L454 213",stroke:"#56627a","stroke-width":1.6},mic);
  svgText(room,395,338,"MEASUREMENT POINT",10,"#d8bd91");
  svgText(room,655,338,"LISTENING POSITION",10,"#70cfc4");
}

function buildSignalChain(svg) {
  const g=svgNode("g",{class:"signal-art"},svg);
  const cards=[
    {x:48,label:"MEASURE",detail:"Room response",accent:"#70cfc4"},
    {x:340,label:"PROCESS",detail:"DSP correction",accent:"#d8bd91"},
    {x:632,label:"PLAY BACK",detail:"Monitor output",accent:"#70cfc4"}
  ];
  cards.forEach((card,index)=>{
    const c=svgNode("g",{class:"signal-card"},g);
    svgNode("rect",{x:card.x,y:88,width:220,height:190,rx:20,fill:"#111d33",stroke:card.accent,"stroke-opacity":0.7,"stroke-width":2},c);
    svgNode("rect",{x:card.x+12,y:100,width:196,height:166,rx:14,fill:"#1c2b46","fill-opacity":0.62,stroke:"#d7e2f4","stroke-opacity":0.08},c);
    if(index===0){
      svgNode("rect",{x:card.x+91,y:133,width:38,height:54,rx:18,fill:"#d8bd91"},c);
      svgNode("path",{d:`M${card.x+110} 187 L${card.x+110} 220 M${card.x+83} 220 L${card.x+137} 220`,stroke:"#d8bd91","stroke-width":4,"stroke-linecap":"round"},c);
      svgNode("path",{d:`M${card.x+74} 160 Q${card.x+58} 188 ${card.x+75} 201 M${card.x+146} 160 Q${card.x+162} 188 ${card.x+145} 201`,fill:"none",stroke:"#70cfc4","stroke-width":3,"stroke-dasharray":"5 6"},c);
    } else if(index===1){
      svgNode("rect",{x:card.x+69,y:132,width:82,height:72,rx:8,fill:"#101b30",stroke:"#d8bd91","stroke-width":2},c);
      for(let pin=0;pin<4;pin+=1)svgNode("path",{d:`M${card.x+78+pin*18} 122 L${card.x+78+pin*18} 132 M${card.x+78+pin*18} 204 L${card.x+78+pin*18} 214`,stroke:"#d8bd91","stroke-width":3},c);
      svgNode("path",{d:`M${card.x+82} 178 Q${card.x+96} 145 ${card.x+110} 166 T${card.x+140} 151`,fill:"none",stroke:"#70cfc4","stroke-width":3},c);
    } else addSpeaker(c,card.x+79,130,0.9);
    svgText(c,card.x+110,239,card.label,15,"#f4f0e9",{"text-anchor":"middle"});
    svgText(c,card.x+110,258,card.detail,10,"#b8c5d9",{"text-anchor":"middle","letter-spacing":0.6,"font-weight":500});
  });
  for(let i=0;i<2;i+=1){
    const x1=268+i*292,x2=x1+69;
    svgNode("path",{d:`M${x1} 181 L${x2} 181`,stroke:"#d8bd91","stroke-width":3,"stroke-linecap":"round","stroke-dasharray":"8 7"},g);
    svgNode("path",{d:`M${x2-12} 171 L${x2} 181 L${x2-12} 191`,fill:"none",stroke:"#d8bd91","stroke-width":3,"stroke-linecap":"round","stroke-linejoin":"round"},g);
    svgNode("circle",{cx:x1,cy:181,r:7,fill:"#70cfc4",class:"signal-pulse","data-start-x":x1,"data-end-x":x2},g);
  }
  svgText(g,450,322,"A CONCEPTUAL SIGNAL PATH — NOT A MEASURED RESPONSE",10,"#9eabc0",{"text-anchor":"middle","letter-spacing":1});
}

function buildViolinPerformance(svg) {
  const g=svgNode("g",{class:"violin-performance"},svg);
  const performer=svgNode("g",{class:"performer-character"},g);
  svgNode("circle",{cx:184,cy:145,r:33,fill:"#c89b67",stroke:"#f2d9b2","stroke-width":2},performer);
  svgNode("path",{d:"M151 142 Q151 98 188 105 Q214 111 218 146 Q196 128 176 132 Z",fill:"#111827"},performer);
  svgNode("path",{d:"M173 181 Q208 167 238 196 L254 306 L120 306 L137 207 Z",fill:"#304463",stroke:"#8da3c6","stroke-width":2},performer);
  svgNode("path",{d:"M229 202 Q270 189 319 207 L375 191",fill:"none",stroke:"#c89b67","stroke-width":18,"stroke-linecap":"round",class:"performer-arm"},performer);
  svgNode("path",{d:"M153 214 Q123 235 110 274",fill:"none",stroke:"#c89b67","stroke-width":17,"stroke-linecap":"round"},performer);

  const violin=svgNode("g",{class:"illustrated-violin"},g);
  svgNode("path",{d:"M451 47 L475 47 L470 164 L456 178 L444 164 Z",fill:"#a66d3f",stroke:"#f0d4a6","stroke-width":2},violin);
  svgNode("circle",{cx:463,cy:40,r:15,fill:"#a66d3f",stroke:"#f0d4a6","stroke-width":3},violin);
  svgNode("path",{d:"M453 70 L473 70 L466 244 L450 244 Z",fill:"#172035",stroke:"#d8bd91","stroke-width":1.5},violin);
  svgNode("path",{d:"M450 132 C419 113 388 130 390 164 C362 181 368 222 397 242 C403 270 430 292 462 310 C494 292 521 270 527 242 C556 222 562 181 534 164 C536 130 505 113 474 132 L462 154 Z",fill:"url(#vp-scene-gold)",stroke:"#f8e4c1","stroke-width":3},violin);
  svgNode("path",{d:"M410 168 Q430 158 450 172 L450 229 Q429 241 410 223 M514 168 Q494 158 474 172 L474 229 Q495 241 514 223",fill:"none",stroke:"#7c4e2e","stroke-width":5},violin);
  svgNode("path",{d:"M430 183 C418 194 440 201 428 218 M492 183 C504 194 482 201 494 218",fill:"none",stroke:"#633d29","stroke-width":5,"stroke-linecap":"round"},violin);
  svgNode("path",{d:"M448 205 L476 205 L472 221 L452 221 Z",fill:"#e7d1a9",stroke:"#8d633d","stroke-width":2},violin);
  svgNode("path",{d:"M454 227 L470 227 L482 282 L442 282 Z",fill:"#74492e",stroke:"#d6b58a","stroke-width":2},violin);
  for(let i=0;i<4;i+=1)svgNode("path",{d:`M${454+i*5} 55 L${450+i*5} 285`,stroke:i===1?"#fff0d1":"#594a40","stroke-width":i===1?1.8:1.2,"stroke-opacity":0.92},violin);
  svgNode("path",{d:"M445 288 Q462 300 479 288",fill:"none",stroke:"#f0d8b2","stroke-width":3},violin);

  const bow=svgNode("g",{class:"bow-rig"},g);
  svgNode("path",{d:"M325 219 Q450 184 580 211",stroke:"#d8bd91","stroke-width":7,"stroke-linecap":"round",fill:"none"},bow);
  svgNode("path",{d:"M325 227 Q450 192 580 219",stroke:"#f7ecd7","stroke-width":2,"stroke-linecap":"round",fill:"none"},bow);
  svgNode("rect",{x:315,y:207,width:18,height:32,rx:5,fill:"#27283a",stroke:"#d8bd91","stroke-width":2},bow);
  svgText(g,630,112,"SOUND TAKES SHAPE",12,"#d8bd91",{"text-anchor":"middle"});
  svgNode("path",{d:"M600 155 Q670 112 740 155 M595 178 Q670 135 745 178 M590 201 Q670 158 750 201",class:"sound-wave",fill:"none",stroke:"#70cfc4","stroke-width":3,"stroke-linecap":"round","stroke-dasharray":"7 12"},g);
  svgText(g,690,270,"♪",34,"#f0d8b2",{"text-anchor":"middle",class:"music-note note-float"});
  svgText(g,755,235,"♫",27,"#70cfc4",{"text-anchor":"middle",class:"music-note note-float"});
  svgText(g,450,345,"ILLUSTRATED VIOLIN PERFORMANCE",10,"#9eabc0",{"text-anchor":"middle","letter-spacing":1});
}

function renderSceneIllustration(scene, topic = "") {
  const type=String(scene?.graphic_data?.type || "").toLowerCase();
  const caption=String(scene?.caption || topic || "Illustrated explanation");
  const svg=svgNode("svg",{viewBox:"0 0 900 380",preserveAspectRatio:"xMidYMid meet",class:"scene-illustration","role":"img","aria-label":caption});
  addDefs(svg);addPanel(svg);
  if(type==="room_acoustics")buildRoom(svg);
  else if(type==="signal_chain")buildSignalChain(svg);
  else if(type==="violin_performance_2d")buildViolinPerformance(svg);
  else svgText(svg,450,195,caption,22,"#e8edf6",{"text-anchor":"middle"});
  return svg;
}

function syncSceneIllustration(svg, seconds, progress=0) {
  if(!svg)return;
  const t=Math.max(0,Number(seconds)||0),waveOffset=(t*42)%260;
  svg.querySelectorAll(".sound-wave").forEach((path,index)=>{
    path.setAttribute("stroke-dashoffset",String(-waveOffset*(index%2?-1:1)));
    path.setAttribute("opacity",String(0.42+0.34*(0.5+0.5*Math.sin(t*2.1+index*0.8))));
  });
  const person=svg.querySelector(".listener-character");
  if(person)person.setAttribute("transform",`translate(0 ${Math.sin(t*1.7)*2.2})`);
  const bow=svg.querySelector(".bow-rig");
  if(bow)bow.setAttribute("transform",`translate(0 ${Math.sin(t*2.8)*10}) rotate(${Math.sin(t*2.8)*1.2} 450 215)`);
  const arm=svg.querySelector(".performer-arm");
  if(arm)arm.setAttribute("transform",`rotate(${Math.sin(t*2.8)*2.8} 270 206)`);
  const violin=svg.querySelector(".illustrated-violin");
  if(violin)violin.setAttribute("transform",`rotate(${Math.sin(t*0.8)*1.1} 460 210)`);
  svg.querySelectorAll(".signal-pulse").forEach((pulse,index)=>{
    const start=Number(pulse.getAttribute("data-start-x")||0),end=Number(pulse.getAttribute("data-end-x")||0);
    const local=(progress*1.8+index*0.42)%1;
    pulse.setAttribute("cx",String(start+(end-start)*local));
    pulse.setAttribute("opacity",String(0.45+0.5*Math.sin(local*Math.PI)));
  });
  svg.querySelectorAll(".note-float").forEach((note,index)=>{
    note.setAttribute("transform",`translate(0 ${-((t*22+index*22)%42)})`);
    note.setAttribute("opacity",String(0.55+0.4*Math.sin(t*1.8+index)));
  });
}

export { renderSceneIllustration, syncSceneIllustration };
