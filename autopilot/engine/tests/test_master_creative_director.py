"""Offline contract tests for the Master Creative Director."""
import sys
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from master_creative_director import (
    DirectorPlanError,
    build_director_request,
    require_valid_director_plan,
    validate_director_plan,
)


def valid_director_plan():
    purposes = ["hook", "context", "reveal", "explanation", "contrast", "reveal", "payoff", "ending"]
    sizes = ["extreme_wide", "wide", "medium", "close_up", "macro", "overhead", "point_of_view", "close_up"]
    movements = ["dolly_in", "truck_left", "orbit", "pan", "crane_up", "tracking", "whip_pan", "dolly_out"]
    transitions = ["match_cut", "whip_pan", "dissolve", "cut", "foreground_wipe", "speed_ramp", "light_transition", "none"]
    shots = []
    for index in range(8):
        start = index * 4
        shots.append({
            "id": f"shot-{index + 1:02d}",
            "start_seconds": start,
            "end_seconds": start + 4,
            "purpose": purposes[index],
            "visual_subject": f"Distinct musical subject {index + 1}",
            "setting": f"Original visual environment {index + 1}",
            "visual_description": f"A unique cinematic visual moment showing subject detail {index + 1}",
            "composition": f"Layered composition with focal hierarchy {index + 1}",
            "camera": {
                "shot_size": sizes[index],
                "angle": f"Purposeful camera angle {index + 1}",
                "movement": movements[index],
                "focus": f"Focus follows visual detail {index + 1}",
            },
            "animation": {
                "subject_action": f"Subject performs a meaningful action {index + 1}",
                "environment_motion": f"Environment responds with a distinct movement {index + 1}",
                "graphic_action": "",
                "depth_motion": f"Foreground and background shift at different rates {index + 1}",
                "motion_rationale": f"Movement reveals the next part of the story {index + 1}",
            },
            "transition_to_next": transitions[index],
            "narration_cue": f"Narration beat {index + 1}",
            "music_cue": f"Musical moment {index + 1}",
            "sound_effects": [],
        })
    return {
        "schema_version": 1,
        "story_understanding": {
            "central_truth": "A violin string transfers energy through the bridge into the instrument body.",
            "viewer_question": "How does a vibrating string become an audible sound?",
            "emotional_arc": ["curiosity", "discovery", "wonder"],
            "key_revelations": ["The bridge transfers vibration.", "The body moves air to create sound."],
        },
        "visual_concept": {
            "concept_name": "The Hidden Journey of Sound",
            "visual_metaphor": "A travelling energy pulse through a physical instrument.",
            "creative_rationale": "The metaphor makes an invisible mechanism visible without claiming literal footage.",
            "art_direction": "Tactile cinematic macro scenes and grounded technical visualisations.",
            "palette": {
                "dominant": "#24152E",
                "secondary": "#D45A4C",
                "accent": "#EACB8B",
                "harmony": "split_complementary",
                "reasoning": "The deep plum conveys mystery while warm coral suggests the energy being revealed.",
                "contrast_strategy": "Warm highlights are isolated against deep shadows; all captions use high-contrast backing.",
            },
            "lighting_plan": "Directional warm key light with cool controlled fill and atmospheric depth.",
            "composition_language": "Asymmetric framing, purposeful negative space, and foreground-to-background separation.",
        },
        "storyboard": {"duration_seconds": 32, "shots": shots},
        "edit_direction": {
            "pacing": "Begin with a rapid hook, breathe during the explanation, then accelerate into the payoff.",
            "transition_language": "Match the movement direction between related shots and use a whip pan only for the revelation.",
            "typography": "Large restrained editorial titles with word-level emphasis on key facts.",
            "sound_design": "Subtle tactile string, wood and air accents mixed beneath narration.",
            "music_mood": "Curious, intimate and progressively uplifting.",
            "music_sync_cues": [
                {"time_seconds": 2, "event": "First title reveal", "reason": "Land the hook on the opening accent."},
                {"time_seconds": 19, "event": "Energy transfer visual", "reason": "Align the key mechanism reveal with a musical pulse."},
                {"time_seconds": 29, "event": "Performance payoff", "reason": "Give the musical conclusion its own accent."},
            ],
            "final_payoff": "Resolve the energy journey into a short original violin phrase.",
        },
    }


class MasterCreativeDirectorTests(unittest.TestCase):
    def test_valid_shot_led_director_plan_passes(self):
        plan = valid_director_plan()
        self.assertEqual(validate_director_plan(plan), [])
        self.assertIs(require_valid_director_plan(plan), plan)

    def test_three_picture_slideshow_is_rejected(self):
        plan = valid_director_plan()
        plan["storyboard"]["shots"] = plan["storyboard"]["shots"][:3]
        self.assertTrue(any("8 to 18" in item for item in validate_director_plan(plan)))

    def test_fixed_or_unreasoned_palette_is_rejected(self):
        plan = valid_director_plan()
        plan["visual_concept"]["palette"]["harmony"] = "blue and gold"
        plan["visual_concept"]["palette"]["reasoning"] = ""
        issues = validate_director_plan(plan)
        self.assertTrue(any("colour-theory" in item for item in issues))
        self.assertTrue(any("reasoning is required" in item for item in issues))

    def test_camera_zoom_without_animated_scene_layer_is_rejected(self):
        plan = valid_director_plan()
        shot = plan["storyboard"]["shots"][0]
        shot["camera"]["movement"] = "zoom_in"
        shot["animation"] = {
            "subject_action": "",
            "environment_motion": "",
            "graphic_action": "",
            "depth_motion": "",
            "motion_rationale": "Only a camera push.",
        }
        self.assertTrue(any("camera zoom on a still image" in item for item in validate_director_plan(plan)))

    def test_timeline_gaps_are_rejected(self):
        plan = valid_director_plan()
        plan["storyboard"]["shots"][4]["start_seconds"] += 0.5
        self.assertTrue(any("gap or overlap" in item for item in validate_director_plan(plan)))

    def test_mechanical_single_transition_is_rejected(self):
        plan = valid_director_plan()
        for shot in plan["storyboard"]["shots"][:-1]:
            shot["transition_to_next"] = "cut"
        self.assertTrue(any("two distinct transition styles" in item for item in validate_director_plan(plan)))

    def test_missing_music_synchronization_is_rejected(self):
        plan = valid_director_plan()
        plan["edit_direction"]["music_sync_cues"] = []
        self.assertTrue(any("at least two time-coded events" in item for item in validate_director_plan(plan)))

    def test_request_keeps_preferences_optional_and_does_not_invent_them(self):
        request = build_director_request({
            "topic": "How a violin bridge transfers vibration",
            "title": "How Sound Travels Through a Violin",
            "narration_script": "A verified narration about the instrument.",
            "verified_sources": [{"url": "https://example.com/a"}, {"url": "https://example.org/b"}],
        })
        self.assertIn("colour theory", request["system"])
        self.assertIn("Do not blindly reuse a fixed", request["system"])
        self.assertIn('"creator_preferences":{}', request["user"])

    def test_request_requires_verified_sources(self):
        with self.assertRaises(DirectorPlanError):
            build_director_request({
                "topic": "A story",
                "title": "A title",
                "narration_script": "A narration",
                "verified_sources": [],
            })


if __name__ == "__main__":
    unittest.main()
