import { spring } from "motion";
import { gestureKeyframes } from "./contract.mjs";
import { fitCharacterToCanvas } from "./character-layout.mjs";
import { buildStagecraftMotion } from "./stagecraft.mjs";

export function sampleMotionSpring(from, to, fps = 25, maxMs = 1400) {
  const frameRate = Math.max(1, Number(fps) || 25);
  const maximum = Math.max(250, Math.min(4000, Number(maxMs) || 1400));
  const generator = spring({
    keyframes: [Number(from), Number(to)],
    stiffness: 320,
    damping: 26,
    mass: 1
  });
  const stepMs = 1000 / frameRate;
  const values = [];
  let elapsed = 0;
  for (; elapsed <= maximum; elapsed += stepMs) {
    const state = generator.next(elapsed);
    const value = Number(state.value);
    if (!Number.isFinite(value)) {
      throw new TypeError("Motion produced a non-finite spring sample.");
    }
    values.push(value);
    if (state.done) break;
  }
  if (!values.length || Math.abs(values.at(-1) - Number(to)) > 0.001) {
    values.push(Number(to));
  }
  return {
    values,
    duration: Math.max(1 / frameRate, (values.length - 1) / frameRate)
  };
}

export function buildMusicSynchronizedPerformanceTracks({
  targetPrefix,
  start = 0,
  duration = 1,
  bpm,
  beatTimes = [],
  downbeats = [],
  onsets = [],
  noteEvents = [],
  confidence = 1,
  timingSource = "validated_audio_event_map",
  fps = 25
} = {}) {
  const total = Math.max(0.08, Number(duration) || 0.08);
  const tempo = Number(bpm);
  const certainty = Number(confidence);
  if (!targetPrefix || !Number.isFinite(tempo) || tempo < 40 || tempo > 240 ||
      !Number.isFinite(certainty) || certainty < 0.28) return [];

  const cleanTimes = values => [...new Set((Array.isArray(values) ? values : [])
    .map(value => Number(value))
    .filter(value => Number.isFinite(value) && value >= 0 && value <= total)
    .map(value => Math.round(value * 10000) / 10000))]
    .sort((a, b) => a - b);
  const beats = cleanTimes(beatTimes);
  if (beats.length < 2) return [];
  const period = 60 / tempo;
  const bars = cleanTimes(downbeats);
  const strongBeats = bars.length ? bars : beats.filter((_time, index) => index % 4 === 0);
  const attacks = cleanTimes(onsets);
  const events = (Array.isArray(noteEvents) ? noteEvents : [])
    .map(event => ({
      time: Number(event?.time),
      note: Number(event?.note),
      velocity: Number(event?.velocity ?? 76),
      durationSeconds: Number(event?.duration_seconds ?? event?.durationSeconds ?? 0.2)
    }))
    .filter(event =>
      Number.isFinite(event.time) && event.time >= 0 && event.time <= total &&
      Number.isInteger(event.note) && event.note >= 0 && event.note <= 127 &&
      Number.isFinite(event.velocity) && event.velocity >= 1 && event.velocity <= 127 &&
      Number.isFinite(event.durationSeconds) && event.durationSeconds > 0
    )
    .sort((a, b) => a.time - b.time);

  const makeTrack = (target, points) => {
    const valuesByTime = new Map([[0, 0], [total, 0]]);
    for (const point of points) {
      const time = Number(point.time);
      const value = Number(point.value);
      if (!Number.isFinite(time) || !Number.isFinite(value) || time < 0 || time > total) continue;
      valuesByTime.set(Math.round(time * 10000) / 10000, value);
    }
    const ordered = [...valuesByTime.entries()].sort((a, b) => a[0] - b[0]);
    return {
      target,
      property: "rotate",
      values: ordered.map(point => point[1]),
      key_times: ordered.map(point => point[0]),
      start: Math.max(0, Number(start) || 0),
      duration: total,
      easing: "linear"
    };
  };
  const pulse = (target, times, amplitude, releaseSeconds, sign = 1) => {
    const points = [];
    times.forEach((time, index) => {
      const hit = Math.min(total, time + 0.035);
      const release = Math.min(total, hit + releaseSeconds);
      const side = typeof sign === "function" ? sign(index, time) : sign;
      points.push(
        { time: hit, value: (index % 2 === 0 ? -1 : 1) * amplitude * side },
        { time: release, value: 0 }
      );
    });
    return makeTrack(target, points);
  };

  const strokeTimes = cleanTimes([
    0,total,
    ...beats.flatMap((beat,index)=>{
      const next=beats[index+1] ?? (beat+period), span=Math.max(.08,next-beat);
      return [beat,beat+span*.25,beat+span*.5,beat+span*.75];
    })
  ]);
  const beatPhaseAt = time => {
    let index=0;
    while(index+1<beats.length && beats[index+1]<=time) index+=1;
    const beatStart=beats[index] ?? 0, beatEnd=beats[index+1] ?? (beatStart+period);
    const progress=Math.max(0,Math.min(1,(time-beatStart)/Math.max(.08,beatEnd-beatStart)));
    return Math.PI*(index+progress);
  };
  const downbeatAccentAt = time => bars.reduce((strength,beat)=>Math.max(
    strength,Math.exp(-Math.pow((time-beat)/.22,2))
  ),0);
  // Quarter-beat samples create a continuous reciprocal bow path. The joints
  // counter-rotate together to keep the bow stable in the player's grip.
  // Put a visible share of the bow stroke through the elbow/forearm.
  // The wrist counter-rotates so the bow grip stays stable while its position travels.
  const bowShoulderStrokes = strokeTimes.map(time => ({
    time,
    value: (15.5 + downbeatAccentAt(time) * 1.2) * Math.cos(beatPhaseAt(time))
  }));
  const bowElbowStrokes = strokeTimes.map((time, index) => ({
    time,
    value: -bowShoulderStrokes[index].value * 1.12
  }));
  const bowWristStrokes=strokeTimes.map((time,index)=>({
    time,value:-bowShoulderStrokes[index].value-bowElbowStrokes[index].value
  }));
  // More visible phrase-level body and head follow-through.
  const torsoPulses=strokeTimes.map(time=>({
    time,value:3.0*Math.sin((time/Math.max(.2,period*4))*Math.PI*2)+downbeatAccentAt(time)*.45
  }));
  const headPulses=strokeTimes.map(time=>({
    time,value:-1.45*Math.sin(((time-.065)/Math.max(.2,period*4))*Math.PI*2)+
      .38*Math.sin((time/Math.max(.2,period*8))*Math.PI*2)
  }));
  const fingerNames = ["finger_index", "finger_middle", "finger_ring", "finger_little"];
  const fingerIntervals = Object.fromEntries(fingerNames.map(name => [name, []]));
  if (events.length) {
    const pitches = events.map(event => event.note);
    const minimumPitch = Math.min(...pitches);
    const pitchRange = Math.max(1, Math.max(...pitches) - minimumPitch);
    for (let eventIndex = 0; eventIndex < events.length; eventIndex += 1) {
      const event = events[eventIndex];
      // Relative pitch register chooses a first-position-like visual hand shape.
      // Lower fingers remain softly prepared as higher fingers are added; this
      // is a phrase-specific illustration cue, not a formal fingering chart.
      const fingerIndex = Math.min(3, Math.max(0,
        Math.round(((event.note - minimumPitch) / pitchRange) * 3)));
      const strength = 0.88 + (event.velocity / 127) * 0.2;
      const hit = Math.min(total, event.time + 0.018);
      const nextHit = events[eventIndex + 1]
        ? Math.min(total, events[eventIndex + 1].time + 0.018)
        : total;
      const hold = Math.min(0.82, Math.max(0.15, event.durationSeconds * 0.72));
      const release = Math.min(total, hit + hold, nextHit);
      const settle = Math.min(total, release + 0.09, nextHit);
      for (let fingerPosition = 0; fingerPosition <= fingerIndex; fingerPosition += 1) {
        const finger = fingerNames[fingerPosition];
        const amplitudes = [20.5, -18.5, 19.5, -18.0];
        const stagger = fingerPosition * 0.009;
        const start = Math.min(total, hit + stagger);
        fingerIntervals[finger].push({
          start,
          pressEnd: Math.min(total, start + 0.055, nextHit),
          end: release,
          settle,
          amplitude: amplitudes[fingerPosition] * strength
        });
      }
    }
  } else {
    attacks.forEach((time, index) => {
      const fingerIndex = index % fingerNames.length;
      const hit = Math.min(total, time + 0.025);
      const nextHit = attacks[index + 1] === undefined
        ? total : Math.min(total, attacks[index + 1] + 0.025);
      const release = Math.min(total, hit + Math.min(0.22, period * 0.3), nextHit);
      const settle = Math.min(total, release + 0.075, nextHit);
      const amplitude = [8.0, -7.5, 7.8, -7.0][fingerIndex];
      fingerIntervals[fingerNames[fingerIndex]].push({
        start: hit,
        pressEnd: Math.min(total, hit + 0.05, nextHit),
        end: release,
        settle,
        amplitude
      });
    });
  }

  const fingerTracks = fingerNames.flatMap(name => {
    const intervals = fingerIntervals[name];
    const boundaries = cleanTimes([
      0, total,
      ...intervals.flatMap(interval => [
        interval.start, interval.pressEnd, interval.end, interval.settle
      ])
    ]);
    const points = boundaries.map(time => {
      const selected = intervals
        .filter(interval => time >= interval.start && time < interval.settle)
        .sort((a, b) => b.start - a.start)[0];
      if (!selected) return { time, value: 0 };
      if (time < selected.pressEnd) {
        const attack = (time - selected.start) /
          Math.max(0.001, selected.pressEnd - selected.start);
        return { time, value: selected.amplitude * Math.min(1, Math.max(0, attack)) };
      }
      if (time < selected.end) return { time, value: selected.amplitude };
      const release = (time - selected.end) /
        Math.max(0.001, selected.settle - selected.end);
      return { time, value: selected.amplitude * (1 - Math.min(1, Math.max(0, release))) };
    });
    // Preserve the earlier one-sprite curl as an approximate total rotation,
    // but distribute it across MCP, PIP and DIP joints for a connected finger.
    const scalePoints = factor => points.map(point => ({
      time: point.time,
      value: point.value * factor
    }));
    const prefix = String(targetPrefix) + "-part-";
    return [
      makeTrack(prefix + name, scalePoints(0.52)),
      makeTrack(prefix + name + "_middle", scalePoints(0.30)),
      makeTrack(prefix + name + "_tip", scalePoints(0.18))
    ];
  });

  // Gentle lower-body counterbalance keeps the player grounded; it is weight transfer,
  // not a walking or dance cycle.
  const weightTrack = (target, amplitude, side = 1) => makeTrack(
    target,
    strokeTimes.map(time=>({
      time,value:Math.sin((time/Math.max(.2,period*4))*Math.PI*2)*amplitude*side
    }))
  );

  const prefix = String(targetPrefix);
  const frameRate = Math.max(1, Number(fps) || 25);
  const timing = String(timingSource || "validated_audio_event_map");
  const tag = (track, event) => ({
    ...track,
    music_sync_event: "performer_" + event,
    music_sync_timing_source: timing
  });
  // The bow must travel across the strings, not merely rotate with the camera
  // or arm. This local horizontal slide represents the stick moving through
  // the fixed bow-grip hand during each measured reciprocal stroke.
  const bowSlideTrack = {
    target: prefix + "-prop-bow",
    property: "translate",
    values: strokeTimes.map(time =>
      (14 * Math.sin(beatPhaseAt(time))).toFixed(2) + "px 0px"
    ),
    offsets: strokeTimes.map(time => Number((time / total).toFixed(6))),
    start: Math.max(0, Number(start) || 0),
    duration: total,
    easing: "linear"
  };
  return [
    // Bowing arm: the shoulder, elbow and wrist form one continuous chain.
    tag(makeTrack(prefix + "-part-left_upper_arm", bowShoulderStrokes), "bow_stroke"),
    tag(makeTrack(prefix + "-part-left_forearm", bowElbowStrokes), "bow_stroke"),
    tag(makeTrack(prefix + "-part-left_hand", bowWristStrokes), "bow_stroke"),
    tag(bowSlideTrack, "bow_stroke"),
    // Keep the fretting wrist planted while note events articulate finger sprites.
    tag(makeTrack(prefix + "-part-torso", torsoPulses), "body_balance"),
    tag(makeTrack(prefix + "-part-head", headPulses), "body_balance"),
    tag(weightTrack(prefix + "-part-left_thigh", 6.0, 1), "weight_shift"),
    tag(weightTrack(prefix + "-part-right_thigh", 6.0, -1), "weight_shift"),
    tag(weightTrack(prefix + "-part-left_calf", 4.0, -1), "weight_shift"),
    tag(weightTrack(prefix + "-part-right_calf", 4.0, 1), "weight_shift"),
    tag(weightTrack(prefix + "-part-left_foot", 2.2, 1), "weight_shift"),
    tag(weightTrack(prefix + "-part-right_foot", 2.2, -1), "weight_shift"),
    ...fingerTracks.map(track => tag(track, "finger_note"))
  ];
}

function cssKeyframeValues(property, values) {
  if (property === "rotate") {
    return values.map(value => typeof value === "number" ? value + "deg" : String(value));
  }
  if (property === "x" || property === "y") {
    throw new TypeError("Use CSS transform translateX/translateY for native frame-seekable movement.");
  }
  return values;
}


export function directorCameraKeyframes(camera, shotIndex = 0) {
  const movement = String(camera?.movement || "locked_off").toLowerCase();
  const size = String(camera?.shot_size || "medium").toLowerCase();
  const baseScale = {
    extreme_wide: 1.025,
    wide: 1.04,
    medium: 1.06,
    close_up: 1.085,
    extreme_close_up: 1.12,
    macro: 1.14,
    overhead: 1.055,
    point_of_view: 1.075
  }[size] || 1.06;
  const direction = String(camera?.direction || "").toLowerCase();
  const left = direction === "right" ? -1 : 1;
  const up = direction === "down" ? -1 : 1;
  const scale = value => "scale(" + value.toFixed(3) + ")";
  switch (movement) {
    case "cinematic_push":
      return [
        scale(baseScale + 0.012) + " translate3d(-5px,9px,0) rotate(-0.08deg)",
        scale(baseScale + 0.034) + " translate3d(2px,1px,0) rotate(0.04deg)",
        scale(baseScale + 0.052) + " translate3d(0px,-8px,0)"
      ];
    case "dolly_in":
      return [scale(baseScale) + " translateY(8px)", scale(baseScale + 0.085) + " translateY(-8px)"];
    case "dolly_out":
      return [scale(baseScale + 0.085) + " translateY(-8px)", scale(baseScale) + " translateY(8px)"];
    case "truck_left":
      return [scale(baseScale) + " translateX(34px)", scale(baseScale + 0.015) + " translateX(-34px)"];
    case "truck_right":
    case "tracking":
      return [scale(baseScale) + " translateX(-34px)", scale(baseScale + 0.015) + " translateX(34px)"];
    case "pan":
      return [
        scale(baseScale) + " translateX(" + (left * 34) + "px)",
        scale(baseScale + 0.012) + " translateX(" + (left * -34) + "px)"
      ];
    case "tilt":
      return [
        scale(baseScale) + " translateY(" + (up * 28) + "px)",
        scale(baseScale + 0.01) + " translateY(" + (up * -28) + "px)"
      ];
    case "crane_up":
      return [scale(baseScale) + " translateY(36px)", scale(baseScale + 0.02) + " translateY(-36px)"];
    case "crane_down":
      return [scale(baseScale) + " translateY(-36px)", scale(baseScale + 0.02) + " translateY(36px)"];
    case "orbit":
      return [
        "rotate(-1.4deg) " + scale(baseScale) + " translateX(-18px)",
        "rotate(1.4deg) " + scale(baseScale + 0.025) + " translateX(18px)"
      ];
    case "arc":
      return [
        "rotate(1.1deg) " + scale(baseScale) + " translateY(18px)",
        "rotate(-1.1deg) " + scale(baseScale + 0.02) + " translateY(-18px)"
      ];
    case "whip_pan":
      return [
        scale(baseScale + 0.05) + " translateX(86px)",
        scale(baseScale + 0.04) + " translateX(-44px)",
        scale(baseScale + 0.025) + " translateX(0px)"
      ];
    case "controlled_handheld":
      return [
        scale(baseScale + 0.025) + " translateX(-5px) translateY(3px) rotate(-0.25deg)",
        scale(baseScale + 0.03) + " translateX(5px) translateY(-3px) rotate(0.25deg)",
        scale(baseScale + 0.025) + " translateX(-3px) translateY(2px) rotate(-0.12deg)",
        scale(baseScale + 0.03) + " translateX(0px) translateY(0px)"
      ];
    case "parallax_track":
      // This is a controlled frame track on a single plate, not true multi-plane parallax.
      return [scale(baseScale) + " translateX(-26px)", scale(baseScale + 0.035) + " translateX(26px)"];
    case "zoom_in":
      return [scale(baseScale), scale(baseScale + 0.09)];
    case "zoom_out":
      return [scale(baseScale + 0.09), scale(baseScale)];
    case "locked_off":
      return [scale(baseScale), scale(baseScale)];
    default:
      throw new TypeError("Unsupported Master Director camera movement: " + movement);
  }
}

export function directorTransitionSpec(transition, duration) {
  const kind = String(transition || "cut").toLowerCase();
  const seconds = Math.max(0, Number(duration) || 0);
  if (!seconds || kind === "cut" || kind === "match_cut") {
    return { property: "opacity", values: [1, 1], easing: "linear" };
  }
  switch (kind) {
    case "dissolve":
      return { property: "opacity", values: [0, 1], easing: "linear" };
    case "whip_pan":
      return { property: "filter", values: ["blur(16px)", "blur(0px)"], easing: "ease-out" };
    case "luma_wipe":
      return { property: "clipPath", values: ["inset(0 100% 0 0)", "inset(0 0 0 0)"], easing: "ease-in-out" };
    case "shape_match":
      return { property: "clipPath", values: ["circle(0% at 50% 50%)", "circle(76% at 50% 50%)"], easing: "ease-in-out" };
    case "speed_ramp":
      // The outgoing shot uses an eased camera move; true footage retiming needs moving-image layers.
      return { property: "opacity", values: [1, 1], easing: "linear" };
    case "light_transition":
      return { property: "filter", values: ["brightness(2.1)", "brightness(1)"], easing: "ease-out" };
    case "foreground_wipe":
      return { property: "clipPath", values: ["inset(100% 0 0 0)", "inset(0 0 0 0)"], easing: "ease-in-out" };
    default:
      throw new TypeError("Unsupported Master Director transition: " + kind);
  }
}


export function directorLayerMotionKeyframes(motion, role = "subject") {
  const type = String(motion?.type || "locked").toLowerCase();
  const direction = String(motion?.direction || "subtle").toLowerCase();
  const intensity = Math.min(1, Math.max(0, Number(motion?.intensity) || 0));
  const distance = Math.round(6 + intensity * (role === "foreground" ? 54 : 34));
  const angle = Number((0.6 + intensity * 7).toFixed(2));
  const pulse = Number((1 + intensity * 0.07).toFixed(3));
  const translate = (x, y) => "translateX(" + x + "px) translateY(" + y + "px)";
  const neutral = "translateX(0px) translateY(0px) scale(1)";
  const xDir = direction === "left" ? -1 : direction === "right" ? 1 : 0;
  const yDir = direction === "up" ? -1 : direction === "down" ? 1 : 0;
  switch (type) {
    case "drift":
      return [
        translate(-xDir * distance, -yDir * distance) + " scale(" + (1 + intensity * 0.025).toFixed(3) + ")",
        translate(xDir * distance, yDir * distance) + " scale(" + (1 + intensity * 0.035).toFixed(3) + ")"
      ];
    case "float":
      return [
        "translateY(" + distance + "px) scale(1)",
        "translateY(" + -distance + "px) scale(" + pulse + ")",
        "translateY(" + Math.round(distance * 0.25) + "px) scale(1)"
      ];
    case "sway":
      return [
        "rotate(" + -angle + "deg) translateY(" + Math.round(distance * 0.15) + "px)",
        "rotate(" + angle + "deg) translateY(" + -Math.round(distance * 0.15) + "px)",
        "rotate(" + -angle * 0.35 + "deg)"
      ];
    case "pulse":
      return ["scale(1)", "scale(" + pulse + ")", "scale(1)"];
    case "rotate":
      return ["rotate(" + -angle + "deg)", "rotate(" + angle + "deg)"];
    case "reveal":
      return ["translateY(" + distance + "px) scale(.98)", neutral];
    case "parallax": {
      const factor = role === "foreground" ? 1.35 : role === "atmosphere" ? 0.75 : 0.45;
      const offset = Math.round(distance * factor);
      return [
        translate(-xDir * offset || -offset, -yDir * offset) + " scale(1.02)",
        translate(xDir * offset || offset, yDir * offset) + " scale(1.04)"
      ];
    }
    case "particle":
      return [
        translate(-xDir * distance, distance) + " rotate(-" + angle + "deg)",
        translate(xDir * distance, -distance) + " rotate(" + angle + "deg)"
      ];
    case "wave":
      return [
        "rotate(" + -angle + "deg) translateY(" + distance + "px)",
        "rotate(" + angle + "deg) translateY(" + -distance + "px)"
      ];
    case "locked":
      return [neutral, neutral];
    default:
      throw new TypeError("Unsupported Master Director layer motion: " + type);
  }
}

function multiplyMatrix(left, right) {
  return {
    a: left.a * right.a + left.c * right.b,
    b: left.b * right.a + left.d * right.b,
    c: left.a * right.c + left.c * right.d,
    d: left.b * right.c + left.d * right.d,
    e: left.a * right.e + left.c * right.f + left.e,
    f: left.b * right.e + left.d * right.f + left.f
  };
}

function translateMatrix(x, y) {
  return { a: 1, b: 0, c: 0, d: 1, e: x, f: y };
}

function rotateMatrix(degrees) {
  const radians = Number(degrees) * Math.PI / 180;
  const cosine = Math.cos(radians);
  const sine = Math.sin(radians);
  return { a: cosine, b: sine, c: -sine, d: cosine, e: 0, f: 0 };
}

function aroundPivot(point, degrees) {
  return multiplyMatrix(
    multiplyMatrix(translateMatrix(point.x, point.y), rotateMatrix(degrees)),
    translateMatrix(-point.x, -point.y)
  );
}

function cubicBezierProgress(progress, x1 = 0.42, y1 = 0, x2 = 0.58, y2 = 1) {
  const tGoal = Math.min(1, Math.max(0, progress));
  if (tGoal === 0 || tGoal === 1) return tGoal;
  const coordinate = (t, first, second) => {
    const inverse = 1 - t;
    return 3 * inverse * inverse * t * first +
      3 * inverse * t * t * second + t * t * t;
  };
  let low = 0;
  let high = 1;
  let parameter = tGoal;
  for (let iteration = 0; iteration < 18; iteration += 1) {
    parameter = (low + high) / 2;
    const x = coordinate(parameter, x1, x2);
    if (x < tGoal) low = parameter;
    else high = parameter;
  }
  return coordinate(parameter, y1, y2);
}

function numericCssValue(value) {
  const parsed = Number.parseFloat(String(value));
  return Number.isFinite(parsed) ? parsed : 0;
}

function sampleRotationTrack(track, time) {
  const values = track.values || [];
  if (values.length < 2) return numericCssValue(values[0] || 0);
  const duration = Math.max(0.001, Number(track.duration) || 0.001);
  const keyTimes = track.key_times;
  const hasTimedKeys = Array.isArray(keyTimes) &&
    keyTimes.length === values.length &&
    keyTimes.every((value, index) => Number.isFinite(Number(value)) &&
      (index === 0 || Number(value) > Number(keyTimes[index - 1])));

  let segment;
  let localProgress;
  if (hasTimedKeys) {
    const elapsed = Number(time) - Number(track.start || 0);
    if (elapsed <= Number(keyTimes[0])) return numericCssValue(values[0]);
    if (elapsed >= Number(keyTimes.at(-1))) return numericCssValue(values.at(-1));
    segment = 0;
    while (segment < keyTimes.length - 2 && elapsed > Number(keyTimes[segment + 1])) {
      segment += 1;
    }
    const segmentDuration = Math.max(
      0.0001,
      Number(keyTimes[segment + 1]) - Number(keyTimes[segment])
    );
    localProgress = (elapsed - Number(keyTimes[segment])) / segmentDuration;
  } else {
    const rawProgress = (Number(time) - Number(track.start || 0)) / duration;
    // Repeat articulated movement on an exact cycle boundary. Before the
    // action starts, hold the first pose rather than wrapping negative time.
    const progress = track.loop === true
      ? (rawProgress <= 0 ? 0 : rawProgress % 1)
      : Math.min(1, Math.max(0, rawProgress));
    const segmentPosition = progress * (values.length - 1);
    segment = Math.min(values.length - 2, Math.floor(segmentPosition));
    localProgress = segmentPosition - segment;
  }

  const eased = track.easing === "linear"
    ? localProgress
    : cubicBezierProgress(localProgress);
  const from = numericCssValue(values[segment]);
  const to = numericCssValue(values[segment + 1]);
  return from + (to - from) * eased;
}

function layerPivot(layer, joint, sourceWidth, sourceHeight, fallback = { x: 0.5, y: 0.5 }) {
  if (joint) {
    return {
      x: Number(joint.x) * sourceWidth,
      y: Number(joint.y) * sourceHeight
    };
  }
  return {
    x: Number(layer?.x || 0) + Number(layer?.width || 0) * Number(layer?.pivot_x ?? fallback.x),
    y: Number(layer?.y || 0) + Number(layer?.height || 0) * Number(layer?.pivot_y ?? fallback.y)
  };
}

function localCssMatrix(world, layer, scale) {
  const x = Number(layer?.x || 0);
  const y = Number(layer?.y || 0);
  const relative = multiplyMatrix(
    multiplyMatrix(translateMatrix(-x, -y), world),
    translateMatrix(x, y)
  );
  return "matrix(" + [
    relative.a, relative.b, relative.c, relative.d,
    relative.e * scale, relative.f * scale
  ].map(value => Number(value.toFixed(6))).join(",") + ")";
}

function transformPoint(matrix, point) {
  return {
    x: matrix.a * point.x + matrix.c * point.y + matrix.e,
    y: matrix.b * point.x + matrix.d * point.y + matrix.f
  };
}

function affineTriangleMatrix(source, target) {
  const [p0, p1, p2] = source;
  const [q0, q1, q2] = target;
  const sx1 = p1.x - p0.x;
  const sy1 = p1.y - p0.y;
  const sx2 = p2.x - p0.x;
  const sy2 = p2.y - p0.y;
  const determinant = sx1 * sy2 - sx2 * sy1;
  if (Math.abs(determinant) < 1e-7) {
    throw new TypeError("A source-mesh triangle has degenerate geometry.");
  }
  const qx1 = q1.x - q0.x;
  const qy1 = q1.y - q0.y;
  const qx2 = q2.x - q0.x;
  const qy2 = q2.y - q0.y;
  const a = (qx1 * sy2 - qx2 * sy1) / determinant;
  const c = (sx1 * qx2 - sx2 * qx1) / determinant;
  const b = (qy1 * sy2 - qy2 * sy1) / determinant;
  const d = (sy1 * qy2 - sy2 * qy1) / determinant;
  const e = q0.x - a * p0.x - c * p0.y;
  const f = q0.y - b * p0.x - d * p0.y;
  return "matrix(" + [a, b, c, d, e, f]
    .map(value => Number(value.toFixed(6))).join(",") + ")";
}

function createSourceMeshGrid(layer, specification) {
  const columns = Math.max(2, Math.min(8, Number(specification.columns) || 2));
  const rows = Math.max(2, Math.min(12, Number(specification.rows) || 2));
  const width = Number(layer.width);
  const height = Number(layer.height);
  const vertices = [];
  for (let row = 0; row <= rows; row += 1) {
    for (let column = 0; column <= columns; column += 1) {
      vertices.push({
        x: width * column / columns,
        y: height * row / rows,
        u: column / columns,
        v: row / rows
      });
    }
  }
  const triangles = [];
  const at = (column, row) => row * (columns + 1) + column;
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const tl = at(column, row);
      const tr = at(column + 1, row);
      const bl = at(column, row + 1);
      const br = at(column + 1, row + 1);
      triangles.push([tl, tr, br], [tl, br, bl]);
    }
  }
  return { vertices, triangles, columns, rows };
}

function deformJointSurfaceVertices(
  layer,
  surface,
  grid,
  parentWorld,
  childWorld,
  meshDefinitionByRole,
  localAngle,
  sourceWidth,
  sourceHeight
) {
  const axisStart = (surface.blend_axis_start || []).map(Number);
  const axisEnd = (surface.blend_axis_end || []).map(Number);
  if (axisStart.length !== 2 || axisEnd.length !== 2 ||
      ![...axisStart, ...axisEnd].every(Number.isFinite) ||
      axisStart.some(value => value < 0 || value > 1) ||
      axisEnd.some(value => value < 0 || value > 1)) {
    throw new TypeError("A joint-surface mesh needs finite, normalized parent/child blend-axis anchors.");
  }
  const start = { x: axisStart[0] * sourceWidth, y: axisStart[1] * sourceHeight };
  const end = { x: axisEnd[0] * sourceWidth, y: axisEnd[1] * sourceHeight };
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const lengthSquared = dx * dx + dy * dy;
  if (!Number.isFinite(lengthSquared) || lengthSquared < 4) {
    throw new TypeError("A joint-surface mesh blend axis is degenerate.");
  }

  const mapThroughBodyLayer = (sourcePoint, role, world) => {
    const definition = meshDefinitionByRole.get(role);
    if (!definition) return transformPoint(world, sourcePoint);

    const sourceLayer = definition.layer;
    const x = Number(sourceLayer.x || 0);
    const y = Number(sourceLayer.y || 0);
    const width = Number(sourceLayer.width);
    const height = Number(sourceLayer.height);
    const localX = sourcePoint.x - x;
    const localY = sourcePoint.y - y;

    // Reuse the adjacent surface's local source-mesh deformation when this
    // source point belongs to its canvas. Outside that rectangle, retain only
    // the parent/child world transform.
    if (localX < 0 || localY < 0 || localX > width || localY > height ||
        width <= 0 || height <= 0) {
      return transformPoint(world, sourcePoint);
    }
    const warped = deformSourceMeshVertices(
      sourceLayer,
      definition.specification,
      {
        vertices: [{
          x: localX,
          y: localY,
          u: localX / width,
          v: localY / height
        }]
      },
      localAngle(role)
    )[0];
    return transformPoint(world, {
      x: x + warped.x,
      y: y + warped.y
    });
  };

  const layerX = Number(layer.x || 0);
  const layerY = Number(layer.y || 0);
  const parentRole = String(surface.parent_role || "");
  const childRole = String(surface.child_role || "");
  return grid.vertices.map(vertex => {
    const sourcePoint = {
      x: layerX + vertex.x,
      y: layerY + vertex.y
    };
    const projection = (
      (sourcePoint.x - start.x) * dx +
      (sourcePoint.y - start.y) * dy
    ) / lengthSquared;
    const t = Math.max(0, Math.min(1, projection));
    // Smooth interpolation avoids a hard midpoint hinge: the proximal edge
    // follows the parent surface and the distal edge follows the child.
    const blend = t * t * (3 - 2 * t);
    const parentPoint = mapThroughBodyLayer(sourcePoint, parentRole, parentWorld);
    const childPoint = mapThroughBodyLayer(sourcePoint, childRole, childWorld);
    return {
      x: parentPoint.x + (childPoint.x - parentPoint.x) * blend - layerX,
      y: parentPoint.y + (childPoint.y - parentPoint.y) * blend - layerY
    };
  });
}

function deformSourceMeshVertices(layer, specification, grid, angleDegrees) {
  const start = specification.axis_start.map(Number);
  const end = specification.axis_end.map(Number);
  const width = Number(layer.width);
  const height = Number(layer.height);
  const ax = start[0] * width;
  const ay = start[1] * height;
  const bx = end[0] * width;
  const by = end[1] * height;
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSquared = dx * dx + dy * dy;
  const length = Math.max(1e-6, Math.sqrt(lengthSquared));
  const unitX = dx / length;
  const unitY = dy / length;
  const normalX = -unitY;
  const normalY = unitX;
  const cornerDistances = [
    0,
    width * normalX,
    height * normalY,
    width * normalX + height * normalY
  ];
  const maxCross = Math.max(1, ...cornerDistances.map(value => Math.abs(value)));
  const maxAngle = Math.max(0.1, Number(specification.max_angle_deg) || 1);
  const maxDisplacement = Math.max(0, Number(specification.max_displacement_px) || 0);
  const amount = Math.max(-1, Math.min(1, Number(angleDegrees) / maxAngle));
  const profile = String(specification.profile || "limb_joint");
  const influence = String(specification.influence || "center");
  const direction = influence === "proximal" ? -1 : 1;

  return grid.vertices.map(point => {
    const projection = ((point.x - ax) * dx + (point.y - ay) * dy) / lengthSquared;
    const t = Math.max(0, Math.min(1, projection));
    const cross = ((point.x - ax) * normalX + (point.y - ay) * normalY);
    const crossNorm = Math.max(-1, Math.min(1, cross / maxCross));
    const edgeFade = Math.pow(
      Math.max(0, Math.sin(Math.PI * point.u) * Math.sin(Math.PI * point.v)),
      0.28
    );
    let envelope;
    if (profile === "torso" || influence === "center") {
      envelope = Math.pow(Math.max(0, Math.sin(Math.PI * t)), 1.25);
    } else {
      const center = influence === "distal" ? 0.82 : 0.18;
      envelope = Math.exp(-Math.pow((t - center) / 0.25, 2)) *
        Math.pow(Math.max(0, Math.sin(Math.PI * t)), 0.35);
    }
    const magnitude = amount * maxDisplacement * envelope * edgeFade;
    const normalOffset = direction * magnitude * (1 - 0.42 * crossNorm * crossNorm);
    const axialOffset = -magnitude * 0.18 * crossNorm;
    return {
      x: point.x + normalX * normalOffset + unitX * axialOffset,
      y: point.y + normalY * normalOffset + unitY * axialOffset
    };
  });
}

function addHierarchicalTransformTracks(project, sourceTracks, fps) {
  const transformTracks = [];
  const width = Math.max(1, Number(project.width) || 720);
  const height = Math.max(1, Number(project.height) || 1280);
  const frameRate = Math.max(1, Number(fps) || 25);

  for (const scene of project.scenes || []) {
    const sceneStart = Number(scene.start) || 0;
    const sceneDuration = Number(scene.duration) || 1;
    const sampleOffsets = [];
    for (let elapsed = 0; elapsed < sceneDuration - 1e-8; elapsed += 1 / frameRate) {
      sampleOffsets.push(elapsed / sceneDuration);
    }
    sampleOffsets.push(1);

    for (const character of project.characters || []) {
      const action = (character.scene_actions || {})[scene.id] ||
        ((scene.character_actions || {})[character.id] || {});
      if (Array.isArray(character.scene_ids) && !character.scene_ids.includes(scene.id)) continue;
      if (action.visible === false) continue;

      const prefix = scene.id + "-" + character.id;
      const compositeBaseMode = Boolean(character.base_art && character.base_art.src);
      const segmentedBodyBaseMode = compositeBaseMode &&
        character.performance_base_mode === "segmented_source_body";
      const layers = character.layers || [];
      const props = Object.values(character.props || {});
      const layerByRole = new Map(layers.map(layer => [layer.role, layer]));
      const propById = new Map(props.map(prop => [prop.id, prop]));
      const sourceWidth = Number(character.canvas?.width) || width;
      const sourceHeight = Number(character.canvas?.height) || height;
      const { scale } = fitCharacterToCanvas(character, width, height);
      const joints = character.joints || {};
      const rotationTracks = new Map();

      for (const layer of layers) {
        const id = prefix + "-part-" + layer.id;
        rotationTracks.set(
          layer.role,
          sourceTracks.filter(track => track.target === id && track.property === "rotate")
        );
      }
      for (const prop of props) {
        const id = prefix + "-prop-" + prop.id;
        rotationTracks.set(
          "prop:" + prop.id,
          sourceTracks.filter(track => track.target === id && track.property === "rotate")
        );
      }

      const hasRotation = role => (rotationTracks.get(role) || []).length > 0;
      const dependencies = {
        torso: ["torso"],
        head: ["torso", "head"],
        face: ["torso", "head"],
        left_upper_arm: ["torso", "left_upper_arm"],
        left_forearm: ["torso", "left_upper_arm", "left_forearm"],
        left_hand: ["torso", "left_upper_arm", "left_forearm", "left_hand"],
        right_upper_arm: ["torso", "right_upper_arm"],
        right_forearm: ["torso", "right_upper_arm", "right_forearm"],
        right_hand: ["torso", "right_upper_arm", "right_forearm", "right_hand"],
        left_thigh: ["torso", "left_thigh"],
        left_calf: ["torso", "left_thigh", "left_calf"],
        left_foot: ["torso", "left_thigh", "left_calf", "left_foot"],
        right_thigh: ["torso", "right_thigh"],
        right_calf: ["torso", "right_thigh", "right_calf"],
        right_foot: ["torso", "right_thigh", "right_calf", "right_foot"],
        finger_index: ["torso", "right_upper_arm", "right_forearm", "right_hand", "finger_index"],
        finger_index_middle: ["torso", "right_upper_arm", "right_forearm", "right_hand", "finger_index", "finger_index_middle"],
        finger_index_tip: ["torso", "right_upper_arm", "right_forearm", "right_hand", "finger_index", "finger_index_middle", "finger_index_tip"],
        finger_middle: ["torso", "right_upper_arm", "right_forearm", "right_hand", "finger_middle"],
        finger_middle_middle: ["torso", "right_upper_arm", "right_forearm", "right_hand", "finger_middle", "finger_middle_middle"],
        finger_middle_tip: ["torso", "right_upper_arm", "right_forearm", "right_hand", "finger_middle", "finger_middle_middle", "finger_middle_tip"],
        finger_ring: ["torso", "right_upper_arm", "right_forearm", "right_hand", "finger_ring"],
        finger_ring_middle: ["torso", "right_upper_arm", "right_forearm", "right_hand", "finger_ring", "finger_ring_middle"],
        finger_ring_tip: ["torso", "right_upper_arm", "right_forearm", "right_hand", "finger_ring", "finger_ring_middle", "finger_ring_tip"],
        finger_little: ["torso", "right_upper_arm", "right_forearm", "right_hand", "finger_little"],
        finger_little_middle: ["torso", "right_upper_arm", "right_forearm", "right_hand", "finger_little", "finger_little_middle"],
        finger_little_tip: ["torso", "right_upper_arm", "right_forearm", "right_hand", "finger_little", "finger_little_middle", "finger_little_tip"]
      };
      for (const layer of layers) {
        if (layer.joint_surface) {
          const parentRole = String(layer.joint_surface.parent_role);
          const childRole = String(layer.joint_surface.child_role);
          dependencies[layer.role] = [...new Set([
            ...(dependencies[parentRole] || [parentRole]),
            ...(dependencies[childRole] || [childRole])
          ])];
        }
      }
      if (compositeBaseMode && !segmentedBodyBaseMode) {
        // Legacy intact-composite preview: only the bow hand and finger sprites
        // are independent while the parser-derived arm and leg masks are reviewed.
        dependencies.left_hand = ["torso"];
        for (const name of ["finger_index", "finger_middle", "finger_ring", "finger_little"]) {
          dependencies[name] = [name];
          dependencies[name + "_middle"] = [name, name + "_middle"];
          dependencies[name + "_tip"] = [name, name + "_middle", name + "_tip"];
        }
      }

      const rolesToAnimate = new Set();
      for (const [role, ancestors] of Object.entries(dependencies)) {
        // Mesh-deformed joint surfaces receive per-triangle parent/child
        // blending below, not a second rigid layer transform.
        const layer = layerByRole.get(role);
        if (ancestors.some(hasRotation) && layerByRole.has(role) &&
            !(layer?.joint_surface && layer?.mesh_deformation)) {
          rolesToAnimate.add(role);
        }
      }
      if (compositeBaseMode && !segmentedBodyBaseMode) {
        for (const role of [...rolesToAnimate]) {
          if (role !== "torso" && role !== "left_hand" && !role.startsWith("finger_")) {
            rolesToAnimate.delete(role);
          }
        }
      }
      const expressionNames = compositeBaseMode ? [] : Object.keys(character.expressions || {});
      // Segmented full-body base art has its original head cleared from the
      // underpaint. Its modular reference plates therefore remain independently
      // animatable even though the body itself is composited.
      const canAnimateHeadPlates = !compositeBaseMode || segmentedBodyBaseMode;
      const headVariants = canAnimateHeadPlates ? Object.entries(character.head_variants || {}) : [];
      const headAngles = canAnimateHeadPlates ? Object.entries(character.head_angles || {}) : [];
      const needsExpressionTransform = canAnimateHeadPlates &&
        (hasRotation("torso") || hasRotation("head"));
      const animatedProps = props.filter(prop => {
        if (compositeBaseMode && !segmentedBodyBaseMode && prop.id !== "bow") return false;
        const parentRole = String(prop.attach_to || "torso");
        const parentDependencies = dependencies[parentRole] || [parentRole];
        return parentDependencies.some(hasRotation) || hasRotation("prop:" + prop.id);
      });
      const hasHeadPlates = headVariants.length > 0 || headAngles.length > 0;
      if (!rolesToAnimate.size && !animatedProps.length &&
          !(needsExpressionTransform && (expressionNames.length || hasHeadPlates))) continue;

      const pivotFor = (jointName, layerRole) =>
        layerPivot(layerByRole.get(layerRole), joints[jointName], sourceWidth, sourceHeight);
      const torsoPivot = layerPivot(layerByRole.get("torso"), null, sourceWidth, sourceHeight);
      const neckPivot = pivotFor("neck", "head");
      const leftShoulder = pivotFor("left_shoulder", "left_upper_arm");
      const leftElbow = pivotFor("left_elbow", "left_forearm");
      const leftWrist = pivotFor("left_wrist", "left_hand");
      const rightShoulder = pivotFor("right_shoulder", "right_upper_arm");
      const rightElbow = pivotFor("right_elbow", "right_forearm");
      const rightWrist = pivotFor("right_wrist", "right_hand");
      const leftHip = pivotFor("left_hip", "left_thigh");
      const leftKnee = pivotFor("left_knee", "left_calf");
      const leftAnkle = pivotFor("left_ankle", "left_foot");
      const rightHip = pivotFor("right_hip", "right_thigh");
      const rightKnee = pivotFor("right_knee", "right_calf");
      const rightAnkle = pivotFor("right_ankle", "right_foot");
      const fingerPivots = {
        finger_index: {
          base: pivotFor("right_index_base", "finger_index"),
          pip: pivotFor("right_index_pip", "finger_index_middle"),
          dip: pivotFor("right_index_dip", "finger_index_tip")
        },
        finger_middle: {
          base: pivotFor("right_middle_base", "finger_middle"),
          pip: pivotFor("right_middle_pip", "finger_middle_middle"),
          dip: pivotFor("right_middle_dip", "finger_middle_tip")
        },
        finger_ring: {
          base: pivotFor("right_ring_base", "finger_ring"),
          pip: pivotFor("right_ring_pip", "finger_ring_middle"),
          dip: pivotFor("right_ring_dip", "finger_ring_tip")
        },
        finger_little: {
          base: pivotFor("right_little_base", "finger_little"),
          pip: pivotFor("right_little_pip", "finger_little_middle"),
          dip: pivotFor("right_little_dip", "finger_little_tip")
        }
      };

      const compositeStaticRoles = segmentedBodyBaseMode ? new Set() : new Set([
        "head", "left_upper_arm", "left_forearm", "left_hand",
        "right_upper_arm", "right_forearm", "right_hand",
        "left_thigh", "left_calf", "left_foot", "right_thigh", "right_calf", "right_foot"
      ]);
      const localAngle = (role, time) => {
        if (compositeBaseMode && compositeStaticRoles.has(role)) return 0;
        const candidates = rotationTracks.get(role) || [];
        if (!candidates.length) return 0;
        const selected = candidates[candidates.length - 1];
        return sampleRotationTrack(selected, time);
      };

      const sampledMatrices = new Map([...rolesToAnimate].map(role => [role, []]));
      const meshDefinitions = layers
        .filter(layer => layer.mesh_deformation)
        .map(layer => ({
          layer,
          specification: layer.mesh_deformation,
          grid: createSourceMeshGrid(layer, layer.mesh_deformation)
        }));
      const meshDefinitionByRole = new Map(
        meshDefinitions.map(definition => [definition.layer.role, definition])
      );
      const sampledMeshTriangleMatrices = new Map();
      for (const definition of meshDefinitions) {
        sampledMeshTriangleMatrices.set(
          definition.layer.role,
          definition.grid.triangles.map(() => [])
        );
      }
      const sampledBaseArtMatrices = compositeBaseMode ? [] : null;
      const sampledExpressionMatrices = new Map(expressionNames.map(name => [name, []]));
      const sampledHeadVariantMatrices = new Map(headVariants.map(([name]) => [name, []]));
      const sampledHeadAngleMatrices = new Map(headAngles.map(([name]) => [name, []]));
      const sampledPropMatrices = new Map(animatedProps.map(prop => [prop.id, []]));

      for (const offset of sampleOffsets) {
        const time = sceneStart + offset * sceneDuration;
        const torsoWorld = aroundPivot(torsoPivot, localAngle("torso", time));
        if (compositeBaseMode) {
          sampledBaseArtMatrices.push(localCssMatrix(
            torsoWorld,
            { x: 0, y: 0, width: sourceWidth, height: sourceHeight },
            scale
          ));
        }
        const headWorld = multiplyMatrix(
          torsoWorld,
          aroundPivot(neckPivot, localAngle("head", time))
        );

        const leftUpperWorld = multiplyMatrix(
          torsoWorld,
          aroundPivot(leftShoulder, localAngle("left_upper_arm", time))
        );
        const leftForearmWorld = multiplyMatrix(
          leftUpperWorld,
          aroundPivot(leftElbow, localAngle("left_forearm", time))
        );
        const leftHandWorld = multiplyMatrix(
          leftForearmWorld,
          aroundPivot(leftWrist, localAngle("left_hand", time))
        );

        const rightUpperWorld = multiplyMatrix(
          torsoWorld,
          aroundPivot(rightShoulder, localAngle("right_upper_arm", time))
        );
        const rightForearmWorld = multiplyMatrix(
          rightUpperWorld,
          aroundPivot(rightElbow, localAngle("right_forearm", time))
        );
        const rightHandWorld = multiplyMatrix(
          rightForearmWorld,
          aroundPivot(rightWrist, localAngle("right_hand", time))
        );

        const leftThighWorld = multiplyMatrix(
          torsoWorld,
          aroundPivot(leftHip, localAngle("left_thigh", time))
        );
        const leftCalfWorld = multiplyMatrix(
          leftThighWorld,
          aroundPivot(leftKnee, localAngle("left_calf", time))
        );
        const leftFootWorld = multiplyMatrix(
          leftCalfWorld,
          aroundPivot(leftAnkle, localAngle("left_foot", time))
        );
        const rightThighWorld = multiplyMatrix(
          torsoWorld,
          aroundPivot(rightHip, localAngle("right_thigh", time))
        );
        const rightCalfWorld = multiplyMatrix(
          rightThighWorld,
          aroundPivot(rightKnee, localAngle("right_calf", time))
        );
        const rightFootWorld = multiplyMatrix(
          rightCalfWorld,
          aroundPivot(rightAnkle, localAngle("right_foot", time))
        );

        const worldByRole = {
          torso: torsoWorld,
          head: headWorld,
          face: headWorld,
          left_upper_arm: leftUpperWorld,
          left_forearm: leftForearmWorld,
          left_hand: leftHandWorld,
          right_upper_arm: rightUpperWorld,
          right_forearm: rightForearmWorld,
          right_hand: rightHandWorld,
          left_thigh: leftThighWorld,
          left_calf: leftCalfWorld,
          left_foot: leftFootWorld,
          right_thigh: rightThighWorld,
          right_calf: rightCalfWorld,
          right_foot: rightFootWorld
        };
        for (const layer of layers) {
          const surface = layer.joint_surface;
          if (!surface || layer.mesh_deformation) continue;
          const parentWorld = worldByRole[String(surface.parent_role)] || torsoWorld;
          const childWorld = worldByRole[String(surface.child_role)] || parentWorld;
          const point = {
            x: Number(joints[String(surface.joint)]?.x) * sourceWidth,
            y: Number(joints[String(surface.joint)]?.y) * sourceHeight
          };
          const parentAngle = Math.atan2(parentWorld.b, parentWorld.a);
          const childAngle = Math.atan2(childWorld.b, childWorld.a);
          const delta = Math.atan2(
            Math.sin(childAngle - parentAngle),
            Math.cos(childAngle - parentAngle)
          );
          const blend = Math.max(0, Math.min(1, Number(surface.blend_weight ?? 0.5)));
          const jointAngle = parentAngle + delta * blend;
          const parentPoint = transformPoint(parentWorld, point);
          const childPoint = transformPoint(childWorld, point);
          const jointPoint = {
            x: parentPoint.x + (childPoint.x - parentPoint.x) * blend,
            y: parentPoint.y + (childPoint.y - parentPoint.y) * blend
          };
          worldByRole[layer.role] = multiplyMatrix(
            multiplyMatrix(
              translateMatrix(jointPoint.x, jointPoint.y),
              rotateMatrix(jointAngle * 180 / Math.PI)
            ),
            translateMatrix(-point.x, -point.y)
          );
        }

        for (const [role, pivots] of Object.entries(fingerPivots)) {
          const middleRole = role + "_middle";
          const tipRole = role + "_tip";
          const baseWorld = multiplyMatrix(
            rightHandWorld,
            aroundPivot(pivots.base, localAngle(role, time))
          );
          const middleWorld = multiplyMatrix(
            baseWorld,
            aroundPivot(pivots.pip, localAngle(middleRole, time))
          );
          const tipWorld = multiplyMatrix(
            middleWorld,
            aroundPivot(pivots.dip, localAngle(tipRole, time))
          );
          worldByRole[role] = baseWorld;
          worldByRole[middleRole] = middleWorld;
          worldByRole[tipRole] = tipWorld;
        }

        for (const definition of meshDefinitions) {
          const { layer, specification, grid } = definition;
          let deformedVertices;
          if (String(specification.profile || "") === "joint_surface") {
            const surface = layer.joint_surface || {};
            const parentWorld = worldByRole[String(surface.parent_role)] || torsoWorld;
            const childWorld = worldByRole[String(surface.child_role)] || parentWorld;
            const parentRole = String(surface.parent_role || "");
            const childRole = String(surface.child_role || "");
            deformedVertices = deformJointSurfaceVertices(
              layer, surface, grid, parentWorld, childWorld,
              meshDefinitionByRole,
              role => localAngle(role, time),
              sourceWidth, sourceHeight
            );
          } else {
            const driverAngle = localAngle(String(specification.driver_role), time);
            deformedVertices = deformSourceMeshVertices(
              layer, specification, grid, driverAngle
            );
          }
          const triangleSamples = sampledMeshTriangleMatrices.get(layer.role);
          grid.triangles.forEach((triangle, triangleIndex) => {
            const sourceTriangle = triangle.map(index => grid.vertices[index]);
            const targetTriangle = triangle.map(index => deformedVertices[index]);
            triangleSamples[triangleIndex].push(
              affineTriangleMatrix(sourceTriangle, targetTriangle)
            );
          });
        }

        for (const role of rolesToAnimate) {
          sampledMatrices.get(role).push(
            localCssMatrix(worldByRole[role], layerByRole.get(role), scale)
          );
        }
        for (const name of expressionNames) {
          sampledExpressionMatrices.get(name).push(
            localCssMatrix(headWorld, character.expressions[name], scale)
          );
        }
        for (const [name, plate] of headVariants) {
          sampledHeadVariantMatrices.get(name).push(
            localCssMatrix(headWorld, plate, scale)
          );
        }
        for (const [name, plate] of headAngles) {
          sampledHeadAngleMatrices.get(name).push(
            localCssMatrix(headWorld, plate, scale)
          );
        }
        for (const prop of animatedProps) {
          const parentWorld = worldByRole[String(prop.attach_to || "torso")] || torsoWorld;
          const pivot = layerPivot(prop, null, sourceWidth, sourceHeight);
          const propWorld = multiplyMatrix(
            parentWorld,
            aroundPivot(pivot, localAngle("prop:" + prop.id, time))
          );
          sampledPropMatrices.get(prop.id).push(localCssMatrix(propWorld, prop, scale));
        }
      }

      if (compositeBaseMode) {
        transformTracks.push({
          target: prefix + "-base-art",
          property: "transform",
          values: sampledBaseArtMatrices,
          offsets: sampleOffsets,
          start: sceneStart,
          duration: sceneDuration,
          easing: "linear"
        });
      }
      for (const role of rolesToAnimate) {
        const sourceSyncTrack = [...(rotationTracks.get(role) || [])]
          .reverse()
          .find(track => String(track.music_sync_event || "").startsWith("performer_"));
        transformTracks.push({
          target: prefix + "-part-" + layerByRole.get(role).id,
          property: "transform",
          values: sampledMatrices.get(role),
          offsets: sampleOffsets,
          start: sceneStart,
          duration: sceneDuration,
          easing: "linear",
          ...(sourceSyncTrack ? {
            music_sync_event: sourceSyncTrack.music_sync_event,
            music_sync_timing_source: sourceSyncTrack.music_sync_timing_source
          } : {})
        });
      }
      for (const definition of meshDefinitions) {
        const role = definition.layer.role;
        const triangleSamples = sampledMeshTriangleMatrices.get(role);
        triangleSamples.forEach((values, triangleIndex) => {
          transformTracks.push({
            target: prefix + "-part-" + definition.layer.id + "-mesh-triangle-" + triangleIndex,
            property: "transform",
            values,
            offsets: sampleOffsets,
            start: sceneStart,
            duration: sceneDuration,
            easing: "linear"
          });
        });
      }
      if (needsExpressionTransform) {
        for (const name of expressionNames) {
          transformTracks.push({
            target: prefix + "-expression-" + name,
            property: "transform",
            values: sampledExpressionMatrices.get(name),
            offsets: sampleOffsets,
            start: sceneStart,
            duration: sceneDuration,
            easing: "linear"
          });
        }
      }
      if (needsExpressionTransform) {
        for (const [name] of headVariants) {
          transformTracks.push({
            target: prefix + "-head-variant-" + name,
            property: "transform",
            values: sampledHeadVariantMatrices.get(name),
            offsets: sampleOffsets,
            start: sceneStart,
            duration: sceneDuration,
            easing: "linear"
          });
        }
        for (const [name] of headAngles) {
          transformTracks.push({
            target: prefix + "-head-angle-" + name,
            property: "transform",
            values: sampledHeadAngleMatrices.get(name),
            offsets: sampleOffsets,
            start: sceneStart,
            duration: sceneDuration,
            easing: "linear"
          });
        }
      }
      for (const prop of animatedProps) {
        transformTracks.push({
          target: prefix + "-prop-" + prop.id,
          property: "transform",
          values: sampledPropMatrices.get(prop.id),
          offsets: sampleOffsets,
          start: sceneStart,
          duration: sceneDuration,
          easing: "linear"
        });
      }
    }
  }
  return transformTracks;
}
export function compileMotionTracks(project, { fps = 25 } = {}) {
  const tracks = [];
  const addSpring = (target, property, from, to, start, maxMs) => {
    const sampled = sampleMotionSpring(from, to, fps, maxMs);
    tracks.push({
      target,
      property,
      values: sampled.values,
      start: Math.max(0, Number(start) || 0),
      duration: sampled.duration,
      easing: "linear"
    });
  };
  const addKeyframes = (target, properties, start, durationSeconds, easing = "ease-in-out", loop = false, keyframeEasing = null) => {
    if (!properties || typeof properties !== "object") return;
    for (const [property, rawValues] of Object.entries(properties)) {
      if (!Array.isArray(rawValues) || rawValues.length < 2) continue;
      tracks.push({
        target,
        property,
        values: cssKeyframeValues(property, rawValues),
        start: Math.max(0, Number(start) || 0),
        duration: Math.max(0.08, Number(durationSeconds) || 0.8),
        easing,
        ...(keyframeEasing ? { keyframeEasing } : {}),
        ...(loop ? { loop: true } : {})
      });
    }
  };

  for (const scene of project.scenes || []) {
    const sceneStart = Number(scene.start) || 0;
    const sceneDuration = Number(scene.duration) || 1;
    const backgroundId = scene.id + "-background";
    const titleId = scene.id + "-title";
    const captionId = scene.id + "-caption";
    const visualMode = String(scene.visual_mode || "").toLowerCase();
    const isDirectorShot = visualMode === "director_shot";
    const isProceduralScene = visualMode === "procedural_2d";
    const isDirectedScene = isDirectorShot || isProceduralScene;
    tracks.push(...buildStagecraftMotion(scene, { fps }));
    const transitionIn = String(scene.transition_in || "cut").toLowerCase();
    const transitionDuration = Math.max(0, Number(scene.transition_in_duration) || 0);
    if (isDirectedScene) {
      const transition = directorTransitionSpec(transitionIn, transitionDuration);
      if (transition.property !== "opacity") {
        addKeyframes(backgroundId, { opacity: [1, 1] }, sceneStart, Math.max(0.08, transitionDuration || 0.08), "linear");
      }
      addKeyframes(backgroundId, {
        [transition.property]: transition.values
      }, sceneStart, Math.max(0.08, transitionDuration || 0.08), transition.easing);
    } else {
      addSpring(backgroundId, "opacity", 0, 1, sceneStart, 650);
    }
    const gradeId = scene.id + "-grade";
    addSpring(gradeId, "opacity", 0, 1, sceneStart + 0.02, 420);

    if (isDirectedScene) {
      const camera = scene.director_camera || {};
      const cameraStart = sceneStart + Math.max(0, Number(scene.camera_motion_start_offset) || 0);
      const cameraDuration = Math.max(0.08, Number(scene.camera_motion_duration) || sceneDuration);
      const cameraFrames = directorCameraKeyframes(camera, Number(scene.editorial_index) || 0);
      addKeyframes(
        scene.id + "-camera-world",
        { transform: cameraFrames },
        cameraStart,
        cameraDuration,
        scene.camera_easing || "ease-in-out"
      );

      const visualLayers = isDirectorShot && Array.isArray(scene.visual_layers)
        ? scene.visual_layers : [];
      for (const layer of visualLayers) {
        const role = String(layer.role || "").toLowerCase();
        if (role === "background") continue;
        const layerId = scene.id + "-layer-" + String(layer.id || "");
        const motion = layer.motion || {};
        const offset = Math.max(0, Number(motion.start_offset_seconds) || 0);
        const layerStart = sceneStart + offset;
        const layerDuration = Math.max(0.08, sceneDuration - offset);
        const revealMs = Math.max(300, Math.min(750, layerDuration * 420));
        addSpring(layerId, "opacity", 0, 1, layerStart, revealMs);
        if (String(motion.type || "locked").toLowerCase() !== "locked") {
          const layerFrames = directorLayerMotionKeyframes(motion, role);
          addKeyframes(
            layerId,
            { transform: layerFrames },
            layerStart,
            layerDuration,
            String(motion.type || "") === "reveal" ? "ease-out" : "ease-in-out"
          );
        }
      }
    } else {
      const hasDirectedCamera = Boolean(scene.director_camera && scene.director_camera.movement);
      const cameraKeyframes = hasDirectedCamera
        ? directorCameraKeyframes(scene.director_camera, Number(scene.editorial_index) || 0)
        : visualMode === "cover_performance"
          ? ["scale(1.055) translateX(12px)", "scale(1.105) translateX(-8px)", "scale(1.12) translateX(-13px)"]
          : visualMode === "waveform" || visualMode === "mechanism_illustration"
            ? ["scale(1.055) translateY(8px)", "scale(1.105) translateY(-8px)", "scale(1.115) translateY(-12px)"]
            : ["scale(1.055) translateX(-9px)", "scale(1.105) translateX(7px)", "scale(1.12) translateX(12px)"];
      const cameraStart = sceneStart + Math.max(0, Number(scene.camera_motion_start_offset) || 0);
      const cameraDuration = Math.max(0.08, Number(scene.camera_motion_duration) || sceneDuration);
      addKeyframes(scene.id + "-camera-world", { transform: cameraKeyframes },
        cameraStart, cameraDuration, scene.camera_easing || "ease-in-out");
    }

    const brandId = scene.id + "-brand";
    addSpring(brandId, "opacity", 0, 1, sceneStart + 0.05, 520);
    addSpring(brandId, "transform", 8, 0, sceneStart + 0.05, 620);
    tracks[tracks.length - 1].values = tracks[tracks.length - 1].values.map(
      value => "translateY(" + value + "px)"
    );

    if (visualMode === "macro_illustration") {
      const motif = scene.id + "-motif";
      addKeyframes(motif + "-ring-outer",
        { transform: ["rotate(0deg) scale(.94)", "rotate(18deg) scale(1.04)", "rotate(0deg) scale(.98)"] },
        sceneStart + 0.15, sceneDuration, "ease-in-out");
      addKeyframes(motif + "-ring-inner",
        { transform: ["rotate(0deg) scale(1)", "rotate(-22deg) scale(1.08)", "rotate(0deg) scale(1.02)"] },
        sceneStart + 0.15, sceneDuration, "ease-in-out");
      addKeyframes(motif + "-ring-core",
        { transform: ["scale(.92)", "scale(1.10)", "scale(.96)"] },
        sceneStart + 0.25, sceneDuration * 0.9, "ease-in-out");
      addKeyframes(motif + "-ring-sweep",
        { strokeDashoffset: [1, 0] },
        sceneStart + 0.2, sceneDuration * 0.85, "ease-in-out");
    } else if (visualMode === "cover_performance") {
      for (let barIndex = 0; barIndex < 18; barIndex += 1) {
        const peak = 0.48 + 0.46 * Math.abs(Math.sin(barIndex * 0.83));
        const middle = 0.22 + 0.3 * Math.abs(Math.sin(barIndex * 0.61 + 0.8));
        addKeyframes(scene.id + "-motif-bar-" + barIndex, {
          transform: [
            "scaleY(.18)",
            "scaleY(" + peak.toFixed(3) + ")",
            "scaleY(" + middle.toFixed(3) + ")",
            "scaleY(" + (0.36 + peak * 0.52).toFixed(3) + ")",
            "scaleY(.2)"
          ]
        }, sceneStart + 0.12, sceneDuration * 0.92, "ease-in-out");
      }
    }
    addSpring(titleId, "opacity", 0, 1, sceneStart + 0.12, 600);
    addSpring(titleId, "transform", 30, 0, sceneStart + 0.12, 700);
    tracks[tracks.length - 1].values = tracks[tracks.length - 1].values.map(value => "translateY(" + value + "px)");
    addSpring(captionId, "opacity", 0, 1, sceneStart + 0.45, 540);
    addSpring(captionId, "transform", 20, 0, sceneStart + 0.45, 580);
    tracks[tracks.length - 1].values = tracks[tracks.length - 1].values.map(value => "translateY(" + value + "px)");

    const graphic = scene.graphic_data;
    if (graphic && typeof graphic === "object") {
      const graphicPrefix = scene.id + "-graphic";
      addSpring(graphicPrefix, "opacity", 0, 1, sceneStart + 0.08, 560);
      addSpring(graphicPrefix, "transform", 20, 0, sceneStart + 0.08, 620);
      tracks[tracks.length - 1].values = tracks[tracks.length - 1].values.map(
        value => "translateY(" + value + "px)"
      );
      addSpring(graphicPrefix + "-heading", "opacity", 0, 1, sceneStart + 0.18, 480);
      addSpring(graphicPrefix + "-heading", "transform", 14, 0, sceneStart + 0.18, 500);
      tracks[tracks.length - 1].values = tracks[tracks.length - 1].values.map(
        value => "translateY(" + value + "px)"
      );

      const graphicType = String(graphic.type || "").toLowerCase();
      const graphicItems = Array.isArray(graphic.items) ? graphic.items : [];
      if (["process_flow", "signal_path", "comparison", "arch_heights"].includes(graphicType)) {
        graphicItems.forEach((item, itemIndex) => {
          const revealAt = sceneStart + Math.max(
            0.08,
            Number(item?.reveal_at ?? (0.24 + itemIndex * 0.62)) || 0
          );
          const nodeId = graphicPrefix + "-node-" + itemIndex;
          addSpring(nodeId, "opacity", 0, 1, revealAt, 470);
          addSpring(nodeId, "transform", 18, 0, revealAt, 540);
          tracks[tracks.length - 1].values = tracks[tracks.length - 1].values.map(
            value => "translateY(" + value + "px) scale(.98)"
          );
          if (graphicType === "arch_heights") {
            addKeyframes(graphicPrefix + "-bar-" + itemIndex,
              { transform: ["scaleY(0)", "scaleY(1)"] },
              revealAt + 0.08, 0.62, "ease-out");
          }
          if (itemIndex < graphicItems.length - 1 && graphicType !== "arch_heights") {
            addKeyframes(graphicPrefix + "-connector-" + itemIndex,
              { strokeDashoffset: [1, 0] }, revealAt + 0.16, 0.58, "ease-out");
          }
        });
      } else if (graphicType === "waveform") {
        addKeyframes(graphicPrefix + "-wave",
          { strokeDashoffset: [1, 0] }, sceneStart + 0.35, 1.35, "ease-out");
        addKeyframes(graphicPrefix + "-wave-marker",
          { cx: [8, 292] }, sceneStart + 0.35, Math.max(0.8, sceneDuration - 0.6), "linear");
      }
    }

    for (const character of project.characters || []) {
      const action = (character.scene_actions || {})[scene.id] ||
        ((scene.character_actions || {})[character.id] || {});
      if (Array.isArray(character.scene_ids) && !character.scene_ids.includes(scene.id)) continue;
      if (action.visible === false) continue;
      const prefix = scene.id + "-" + character.id;
      const compositeBaseMode = Boolean(character.base_art && character.base_art.src);
      const segmentedBodyBaseMode = compositeBaseMode &&
        character.performance_base_mode === "segmented_source_body";
      const actionStart = sceneStart + Math.max(0, Number(action.start_offset) || 0);
      if (action.appear_immediately === true) {
        // Performance presenters must be fully visible on the opening frame;
        // retain the legacy entrance spring for every other presenter action.
        addKeyframes(prefix, { opacity: [1, 1] }, actionStart, 0.08, "linear");
      } else {
        addSpring(prefix, "opacity", 0, 1, actionStart, 650);
      }
      const presenterScale = Number(action.scale ?? character.scale ?? 1);
      addSpring(prefix, "transform", 28, 0, actionStart, 720);
      tracks[tracks.length - 1].values = tracks[tracks.length - 1].values.map(
        value => "translateY(" + value + "px) scale(" + presenterScale + ")"
      );
      const partIdByRole = new Map();
      for (const layer of character.layers || []) {
        const target = prefix + "-part-" + layer.id;
        partIdByRole.set(layer.role, target);
      }

      const addRigKeyframes = (role, properties, start, duration, loop = false) => {
        addKeyframes(partIdByRole.get(role), properties, start, duration, "ease-in-out", loop);
        // The face cut-out and expression overlays are separate images, but
        // they must inherit the head's neck-pivot motion to stay registered.
        if (role === "head") {
          addKeyframes(partIdByRole.get("face"), properties, start, duration, "ease-in-out", loop);
          for (const name of Object.keys(character.expressions || {})) {
            addKeyframes(prefix + "-expression-" + name, properties, start, duration, "ease-in-out", loop);
          }
        }
      };
      const pose = (character.poses || {})[action.pose || ""] || {};
      for (const [role, properties] of Object.entries(pose)) {
        addRigKeyframes(role, properties, actionStart + 0.05, Number(action.duration) || 1);
      }
      const gestures = {
        ...gestureKeyframes(action.gesture),
        ...((character.gestures || {})[action.gesture] || {})
      };
      const gestureLoop = action.loop === true;
      const gestureDuration = gestureLoop
        ? Math.max(
            0.5,
            Math.min(
              sceneDuration,
              Number(action.cycle_duration_seconds) || 1.8
            )
          )
        : (Number(action.duration) || 1.35);
      for (const [role, properties] of Object.entries(gestures)) {
        addRigKeyframes(role, properties, actionStart + 0.10, gestureDuration, gestureLoop);
      }
      for (const [role, properties] of Object.entries(action.keyframes || {})) {
        addRigKeyframes(role, properties, actionStart, gestureDuration, gestureLoop);
      }

      const instrumentPerformance = action.instrument_performance === true ||
        String(action.gesture || "").toLowerCase() === "violin_performance";
      const syncCandidate = action.music_sync && typeof action.music_sync === "object"
        ? action.music_sync : null;
      const musicSyncReady = instrumentPerformance && syncCandidate &&
        Number(syncCandidate.confidence) >= 0.28 &&
        Array.isArray(syncCandidate.beat_times) && syncCandidate.beat_times.length >= 2;
      for (const prop of Object.values(character.props || {})) {
        const authored = (action.prop_keyframes || {})[prop.id];
        let propFrames = authored;
        if (!propFrames && instrumentPerformance && prop.id === "bow") {
          // Frame-seekable alternating bow strokes around the player's grip pivot.
          propFrames = { rotate: [0, -5.5, 5.5, -5.5, 5.5, 0] };
        } else if (!propFrames && instrumentPerformance && prop.id === "violin") {
          // The violin follows the torso with a restrained responsive tilt.
          propFrames = { rotate: [0, -0.55, 0.35, 0.55, 0] };
        }
        if (musicSyncReady && prop.id === "bow" && propFrames && propFrames.translate) {
          // Replace the legacy uniform bow slide with per-frame beat-sampled translation below.
          propFrames = { ...propFrames };
          delete propFrames.translate;
        }
        if (propFrames) {
          addKeyframes(
            prefix + "-prop-" + prop.id,
            propFrames,
            actionStart + 0.10,
            gestureDuration,
            "ease-in-out",
            gestureLoop
          );
        }
      }

      // Optional real-audio timing overrides the generic loop with exact beat,
      // downbeat and onset events. Low-confidence/invalid analysis stays on the
      // existing authored performance loop instead of inventing a beat grid.
      if (musicSyncReady) {
        const sync = syncCandidate;
        const actionOffset = Math.max(0, actionStart - sceneStart);
        const toActionTimes = values => (Array.isArray(values) ? values : [])
          .map(value => Number(value) - actionOffset)
          .filter(value => Number.isFinite(value) && value >= 0)
          .map(value => Math.min(sceneDuration - actionOffset, value));
        const timedPerformanceTracks = buildMusicSynchronizedPerformanceTracks({
          targetPrefix: prefix,
          start: actionStart,
          duration: Math.max(0.08, sceneDuration - actionOffset),
          bpm: sync.bpm,
          beatTimes: toActionTimes(sync.beat_times),
          downbeats: toActionTimes(sync.downbeats),
          onsets: toActionTimes(sync.onsets),
          noteEvents: (Array.isArray(sync.note_events) ? sync.note_events : []).map(event => ({
            ...event,
            time: Number(event.time) - actionOffset
          })),
          confidence: sync.confidence,
          timingSource: sync.source || sync.analysis_source || "validated_audio_event_map",
          fps
        });
        tracks.push(...timedPerformanceTracks);
      }

      if (action.root_motion) {
        const kind = typeof action.root_motion === "string" ? action.root_motion : String(action.root_motion.type || "");
        const intensity = typeof action.root_motion === "object"
          ? Math.max(0, Math.min(1, Number(action.root_motion.intensity) || 0.45)) : 0.45;
        const distance = Math.round(12 + intensity * 44);
        let rootFrames = null;
        if (kind === "walk" || kind === "walk_cycle") {
          rootFrames = ["translateX(0px) translateY(0px)", "translateX(" + distance + "px) translateY(-7px)",
            "translateX(0px) translateY(0px)", "translateX(-" + distance + "px) translateY(-7px)",
            "translateX(0px) translateY(0px)"];
        } else if (kind === "sway") {
          rootFrames = ["translateX(-" + distance * .35 + "px) rotate(-1.5deg)",
            "translateX(" + distance * .35 + "px) rotate(1.5deg)", "translateX(-" + distance * .35 + "px) rotate(-1.5deg)"];
        } else if (kind === "float" || kind === "hover") {
          rootFrames = ["translateY(7px)", "translateY(-" + distance + "px)", "translateY(7px)"];
        } else {
          throw new TypeError("Unsupported character root_motion: " + kind);
        }
        addKeyframes(prefix + "-motion", { transform: rootFrames }, actionStart, gestureDuration, "ease-in-out", true);
      }
      const selectedExpression = String(
        action.head_expression || action.expression || "neutral"
      ).toLowerCase();
      const activePoseAsset = String(action.pose_asset || "").toLowerCase();
      // Full-body poses and the modular head plates each contain their own face.
      // Never layer the legacy face-only crop over either complete illustration.
      const hasHeadPlates =
        (!compositeBaseMode || segmentedBodyBaseMode) &&
        (Object.keys(character.head_variants || {}).length > 0 ||
         Object.keys(character.head_angles || {}).length > 0);
      if (!activePoseAsset && !hasHeadPlates) {
        for (const name of Object.keys(character.expressions || {})) {
          addSpring(prefix + "-expression-" + name, "opacity",
            name === selectedExpression ? 0 : 1,
            name === selectedExpression ? 1 : 0,
            actionStart, 140);
        }
      }

      const headVariantNames = Object.keys(character.head_variants || {});
      const headAngleNames = Object.keys(character.head_angles || {});
      const selectedHeadAngle = String(action.head_angle || "front").toLowerCase();
      const headAngleSequence = Array.isArray(action.head_angle_sequence)
        ? action.head_angle_sequence.map(value => String(value).toLowerCase())
          .filter(value => value === "front" || headAngleNames.includes(value))
        : [];
      const headExpressionSequence = Array.isArray(action.head_expression_sequence)
        ? action.head_expression_sequence.map(value => String(value).toLowerCase())
          .filter(value => headVariantNames.includes(value))
        : [];

      if (!activePoseAsset && (headVariantNames.length || headAngleNames.length)) {
        // Build one phase sequence of visible head plates. The old implementation
        // used steps(1,end), replacing complete drawings in a single frame.
        // Sample opacity crossfades at the composition frame rate instead.
        const anglePlayback = headAngleSequence.length > 1
          ? [...headAngleSequence, headAngleSequence[0]]
          : [selectedHeadAngle];
        const expressionPlayback = headExpressionSequence.length > 1
          ? [...headExpressionSequence, headExpressionSequence[0]]
          : [selectedExpression];
        const stepCount = Math.max(anglePlayback.length, expressionPlayback.length);

        if (stepCount > 1) {
          const sampleStep = (values, index) => {
            const valueIndex = Math.min(
              values.length - 1,
              Math.floor((index / stepCount) * values.length)
            );
            return values[valueIndex];
          };
          const sampledAngles = Array.from(
            { length: stepCount },
            (_unused, index) => sampleStep(anglePlayback, index)
          );
          const frontIndices = sampledAngles
            .map((angle, index) => angle === "front" ? index : -1)
            .filter(index => index >= 0);
          const activePlates = Array.from({ length: stepCount }, (_unused, index) => {
            if (sampledAngles[index] !== "front") {
              const angle = sampledAngles[index];
              return headAngleNames.includes(angle) && angle !== "front"
                ? "angle:" + angle : null;
            }
            if (!frontIndices.length || !headVariantNames.length) return null;
            const frontOrdinal = frontIndices.indexOf(index);
            const expressionIndex = Math.min(
              expressionPlayback.length - 1,
              Math.floor((frontOrdinal / frontIndices.length) * expressionPlayback.length)
            );
            const expression = expressionPlayback[expressionIndex];
            return headVariantNames.includes(expression)
              ? "variant:" + expression : null;
          });

          // Keep the loop seam identical even when the two source sequences
          // have different lengths and their sampled endpoints do not match.
          if (activePlates.at(-1) !== activePlates[0]) {
            activePlates.push(activePlates[0]);
          }
          const intervalCount = activePlates.length - 1;
          const cycleDuration = Math.max(
            0.08,
            Number(action.head_expression_cycle_duration_seconds) ||
              Number(action.head_angle_cycle_duration_seconds) ||
              gestureDuration
          );
          const sequenceLoop = headExpressionSequence.length > 1
            ? action.head_expression_loop !== false
            : action.head_angle_loop !== false;
          const sampleCount = Math.max(2, Math.ceil(cycleDuration * fps) + 1);
          const offsets = Array.from(
            { length: sampleCount },
            (_unused, index) => index / (sampleCount - 1)
          );
          const fadeSeconds = Math.min(
            0.18,
            cycleDuration / Math.max(1, intervalCount) * 0.45
          );
          const halfFade = fadeSeconds / (2 * cycleDuration);
          const plateNames = [
            ...headVariantNames.map(name => "variant:" + name),
            ...headAngleNames
              .filter(name => name !== "front")
              .map(name => "angle:" + name)
          ];

          for (const plateName of plateNames) {
            const values = offsets.map(offset => {
              const activeIndex = Math.min(
                intervalCount,
                Math.floor(offset * intervalCount)
              );
              let active = activePlates[activeIndex] || null;
              let opacity = active === plateName ? 1 : 0;

              // Transitions are centred on phase boundaries. The overlap is
              // deliberately short and frame-sampled so the renderer can seek
              // every frame deterministically.
              for (let boundaryIndex = 1; boundaryIndex < intervalCount; boundaryIndex += 1) {
                const boundary = boundaryIndex / intervalCount;
                const fadeStart = boundary - halfFade;
                const fadeEnd = boundary + halfFade;
                if (offset < fadeStart || offset > fadeEnd) continue;
                const outgoing = activePlates[boundaryIndex - 1] || null;
                const incoming = activePlates[boundaryIndex] || null;
                if (outgoing === incoming) break;
                const progress = Math.max(
                  0,
                  Math.min(1, (offset - fadeStart) / Math.max(1e-6, fadeEnd - fadeStart))
                );
                opacity = (outgoing === plateName ? 1 - progress : 0) +
                  (incoming === plateName ? progress : 0);
                active = null;
                break;
              }
              return Number(opacity.toFixed(4));
            });

            if (values.some(value => value > 0) &&
                values.some(value => value < 1)) {
              tracks.push({
                target: prefix + "-head-" +
                  (plateName.startsWith("variant:") ? "variant-" : "angle-") +
                  plateName.split(":")[1],
                property: "opacity",
                values,
                offsets,
                start: actionStart,
                duration: cycleDuration,
                easing: "linear",
                ...(sequenceLoop ? { loop: true } : {})
              });
            }
          }
        } else {
          const addHeadPlateOpacity = (target, active) => {
            if (action.appear_immediately === true) {
              const value = active ? 1 : 0;
              addKeyframes(target, { opacity: [value, value] },
                actionStart, 0.08, "linear");
            } else {
              addSpring(target, "opacity",
                active ? 0 : 1, active ? 1 : 0, actionStart, 140);
            }
          };
          for (const name of headVariantNames) {
            const active = selectedHeadAngle === "front" && name === selectedExpression;
            addHeadPlateOpacity(prefix + "-head-variant-" + name, active);
          }
          for (const name of headAngleNames) {
            if (name === "front") continue;
            const active = selectedHeadAngle === name;
            addHeadPlateOpacity(prefix + "-head-angle-" + name, active);
          }
        }
      }

      const eyeTarget = partIdByRole.get("eyes");
      if (eyeTarget) {
        addKeyframes(eyeTarget, { scaleY: [1, 0.12, 1] },
          actionStart + Math.min(1, sceneDuration * 0.4), 0.18);
      }
    }
  }
  const articulated = addHierarchicalTransformTracks(project, tracks, fps);
  return [...tracks.filter(track => track.property !== "rotate"), ...articulated];
}
