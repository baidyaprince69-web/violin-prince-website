# Violin Prince — Visual Prompt & Camera Direction

This guide adapts techniques from two public references into the original Violin Prince visual identity.

## Reference material

- [Zack D Films AI video generator — prompt guide](https://github.com/Anil-matcha/zack-d-films-ai-video-generator/blob/main/references/prompt-guide.md)
- [AI video generator Claude — faceless channel skill](https://github.com/rediumvex/ai-video-generator-claude/blob/main/skills/05-faceless-channel/SKILL.md)

The references are used for general prompt structure, shot planning and camera vocabulary—not for copying a creator's exact branded look.

## Five-part keyframe prompt

Every generated scene image should identify:

1. **Subject and action:** one concrete subject performing one readable action.
2. **Recurring asset anchor:** a short, repeatable description of the same instrument/subject that keeps identity, proportions and material cues consistent across scenes.
3. **Style and material:** illustrated editorial art with restrained dimensional shading; specify wood grain, varnish, metal, bow hair and rosin textures when relevant.
4. **Lighting and camera:** lens/framing, focal plane, depth of field, key/fill/rim light and intended camera move.
5. **Background and atmosphere:** the warm Violin Prince palette, depth layers, negative space and restrained ambient movement.

## Three-scene camera grammar

| Scene | Editorial purpose | Framing and motion |
|---|---|---|
| 1 | Two-second hook | Thumbnail-readable medium close-up; slow push-in; show the subject and action clearly |
| 2 | Distinctive physical detail | Extreme close-up macro; 85mm macro language; shallow depth of field; focus the physical interaction; lateral camera follow |
| 3 | Emotional payoff | Wider composition; slow pull-back reveal; connect the detail to the complete subject |

## Violin performance macro rules

For a performance story, scene 2 should focus on a single physically valid action: bow hair crossing the strings between bridge and fingerboard. Describe the bridge, string windings, bow hair, varnished wood, and the exact focal plane.

Do not force the right-hand bow grip and left-hand fingerboard fingering into the same extreme macro if the camera position cannot plausibly show both. Keep the hand that matters to the action in frame and preserve correct bow/string geometry. Allow motion blur on the moving bow only; keep hands, bridge and fingerboard structurally readable.

The prompt must not promise exact anatomy from image generation. A generated image still requires visual inspection.

## Camera-motion prompt template

```text
SHOT: [subject + one physical action + scene purpose]
FRAMING: [shot size, angle, focal length, depth of field]
CAMERA: [one move, direction, and speed; name what the camera follows]
LIGHT: [key / fill / rim source and color temperature]
MATERIAL: [the exact textures and physical details in focus]
MOTION: [one hero action plus restrained secondary movement]
BACKGROUND: [palette, depth layers, negative space]
SOUND: [narration-first or music-first; ambience and only necessary accents]
```

## Editing principles adopted

- Make the first two seconds readable as a thumbnail before adding motion.
- Give each scene one primary motion cue; use atmosphere and particles as restrained texture, not competing focal points.
- Keep camera movement explicit and smooth: push-in, lateral follow, focus pull, or pull-back.
- Let image, caption and infographic timing follow narration beats; do not animate every element at once.
- Keep important text and the main action away from platform-edge overlays.

## Scope and provider boundary

The V3 prototype currently renders generated still images with deterministic Canvas/Playwright camera motion, typography and graphics. It does **not** call Adobe Firefly, Krea, Leonardo, ElevenLabs, Magic Hour, Seedance, Kling, Veo or another hosted image-to-video service. Such a provider would be a separate optional adapter, with its own account, age eligibility, credentials, quota, watermark, licensing and privacy checks.

The existing cloud-first renderer remains independent of any provider API and the production publisher remains disabled during prototype evaluation.
