import unittest
import numpy as np
from PIL import Image

from create_full_body_performance_preview import (
    _build_preview_music_sync,
    _build_head_expression_sequence,
)
from full_body_performance_rig import (
    _authored_performance_layers,
    _build_segmented_source_base,
    _clip_hand_from_violin_prop,
    _foot_mask,
    _leg_layers,
    _skin_material_mask,
    _decontaminate_edge_matte_rgb,
    _remove_embedded_props_from_static_layers,
    _restore_bow_hair_in_prop_asset,
    _prepare_fingers,
    _canvas_alpha_mask_for_layers,
)


class FullBodyPerformanceRigTests(unittest.TestCase):
    def test_preserved_composite_keeps_body_and_cuts_only_bow_and_finger_regions(self):
        import json
        import tempfile
        from pathlib import Path
        from PIL import ImageDraw

        from full_body_performance_rig import _build_preserved_composite_base

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = Image.new("RGBA", (64, 64), (42, 48, 55, 255))
            draw = ImageDraw.Draw(source)
            draw.rectangle((8, 24, 22, 40), fill=(185, 122, 86, 255))
            # A white bow-hair stroke passes through the hand region; it must
            # be removed from the hand overlay and restored only by the bow prop.
            draw.line((26, 22, 21, 42), fill=(245, 238, 225, 255), width=3)
            original_hand_pixel = source.getpixel((14, 30))
            bow_alpha = np.zeros((64, 64), dtype=np.uint8)
            bow_alpha[6:58, 29:34] = 255
            bow_line = Image.new("L", (64, 64), 0)
            ImageDraw.Draw(bow_line).line((26, 22, 21, 42), fill=255, width=3)
            bow_alpha = np.maximum(bow_alpha, np.asarray(bow_line, dtype=np.uint8))
            source.crop((8, 20, 26, 42)).save(root / "left_hand.png")

            finger_manifest = root / "fingers.json"
            finger_manifest.write_text(json.dumps({
                "schema_version": 1,
                "canvas": {"width": 64, "height": 64},
                "fingers": {
                    "index": {
                        "polygon": [[9, 9], [16, 9], [16, 19], [9, 19]],
                        "pivot": [13, 18]
                    }
                }
            }), encoding="utf-8")

            character = {
                "layers": [{
                    "id": "left_hand", "role": "left_hand", "src": "left_hand.png",
                    "x": 8, "y": 20, "width": 18, "height": 22, "z_index": 40,
                }],
                "joints": {"left_wrist": {"x": 0.25, "y": 0.55}},
            }
            result = _build_preserved_composite_base(
                source,
                root,
                bow_canvas_alpha=bow_alpha,
                finger_manifest_path=finger_manifest,
                character=character,
            )
            with Image.open(root / result["src"]) as opened:
                composite = opened.convert("RGBA")
            pixels = np.asarray(composite)
            self.assertEqual(composite.size, (64, 64))
            self.assertEqual(tuple(pixels[30, 14]), original_hand_pixel)
            self.assertEqual(int(pixels[12, 12, 3]), 0)
            self.assertEqual(int(pixels[30, 31, 3]), 255)
            self.assertLess(int(pixels[30, 31, :3].max()), 245)
            self.assertEqual(result["mode"], "intact_full_body_with_bow_and_finger_cutouts")
            self.assertTrue(result["preserves_original_arms_hands_legs_and_head"])
            self.assertGreater(result["bow_pixels_reconstructed"], 0)
            self.assertGreater(result["finger_pixels_separated"], 0)
            self.assertTrue(result["bow_grip_hand"]["excludes_original_bow_pixels"])
            hand_layer = next(layer for layer in character["layers"] if layer["role"] == "left_hand")
            self.assertEqual(hand_layer["src"], "bow-grip-hand.png")
            with Image.open(root / hand_layer["src"]) as hand_asset:
                hand_rgba = hand_asset.convert("RGBA")
                x0, y0, _x1, _y1 = result["bow_grip_hand"]["bbox"]
                self.assertEqual(hand_rgba.getpixel((26 - x0, 29 - y0))[3], 0,
                    "the bright bow hair must not be baked into the hand overlay")



    def test_recovers_source_bow_hair_into_the_same_animated_prop(self):
        import tempfile
        from pathlib import Path
        from PIL import ImageDraw

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
            draw = ImageDraw.Draw(source)
            # A dark bow shaft already exists in the extracted prop.
            draw.line((34, 230, 214, 20), fill=(92, 52, 30, 255), width=4)
            # The pale hair strand is source-baked and runs parallel, 5 px away.
            draw.line((39, 230, 219, 20), fill=(224, 224, 220, 255), width=2)
            # A separate bright spot near the bow corridor must not be selected.
            draw.rectangle((70, 130, 72, 132), fill=(230, 230, 230, 255))

            x, y, width, height = 28, 10, 195, 235
            prop = source.crop((x, y, x + width, y + height))
            prop_pixels = np.asarray(prop, dtype=np.uint8).copy()
            # Keep only the dark shaft in the currently extracted sprite.
            shaft = (
                (prop_pixels[:, :, 3] > 12)
                & (prop_pixels[:, :, 0] < 150)
                & (prop_pixels[:, :, 1] < 130)
            )
            prop_pixels[~shaft, 3] = 0
            Image.fromarray(prop_pixels, mode="RGBA").save(root / "prop-bow.webp", format="WEBP", quality=98)

            bow_mask = np.zeros((256, 256), dtype=np.uint8)
            bow_mask[y:y + height, x:x + width] = np.asarray(
                Image.open(root / "prop-bow.webp").convert("RGBA").getchannel("A"),
                dtype=np.uint8,
            )
            report, updated_mask = _restore_bow_hair_in_prop_asset(
                source,
                root,
                {"src": "prop-bow.webp", "x": x, "y": y},
                bow_mask,
            )

            with Image.open(root / report["src"]) as opened:
                result = np.asarray(opened.convert("RGBA"), dtype=np.uint8)
            hair_added = int(np.count_nonzero(
                (result[:, :, 3] > 12) & (prop_pixels[:, :, 3] <= 12)
            ))
            self.assertEqual(report["method"], "largest_neutral_source_component_recovered_into_animated_bow")
            self.assertGreater(report["pixels_added"], 250)
            self.assertEqual(report["selected_component_count"], 1)
            self.assertTrue(report["shared_bow_transform"])
            self.assertGreater(hair_added, 250)
            self.assertGreater(int((updated_mask > 12).sum()), int((bow_mask > 12).sum()))


    def test_canvas_head_mask_combines_source_aligned_head_and_face_alpha(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            head = np.zeros((40, 40, 4), dtype=np.uint8)
            head[2:27, 2:27] = (30, 40, 50, 255)
            face = np.zeros((30, 30, 4), dtype=np.uint8)
            face[5:20, 5:20] = (180, 120, 90, 255)
            Image.fromarray(head, mode="RGBA").save(root / "head.png")
            Image.fromarray(face, mode="RGBA").save(root / "face.png")

            mask = _canvas_alpha_mask_for_layers(
                root,
                [
                    {"role": "head", "src": "head.png", "x": 4, "y": 3},
                    {"role": "face", "src": "face.png", "x": 28, "y": 28},
                    {"role": "torso", "src": "head.png", "x": 0, "y": 0},
                ],
                canvas_width=72,
                canvas_height=72,
                roles=("head", "face"),
            )

            self.assertEqual(mask.shape, (72, 72))
            self.assertTrue(mask[5, 6])
            self.assertTrue(mask[34, 34])
            self.assertFalse(mask[2, 2])
            self.assertFalse(mask[60, 60])
            self.assertEqual(int(np.count_nonzero(mask)), 850)

    def test_finger_sprites_are_clipped_to_the_source_aligned_skin_hand(self):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pixels = np.zeros((64, 64, 4), dtype=np.uint8)
            pixels[15:25, 15:25] = (190, 128, 91, 255)
            # A bright prop/edge fragment intrudes into the authored finger polygon.
            pixels[15:25, 25:28] = (225, 35, 40, 255)
            source = Image.fromarray(pixels, mode="RGBA")

            hand_image = source.crop((10, 10, 30, 30)).convert("RGBA")
            hand_alpha = np.zeros((20, 20), dtype=np.uint8)
            hand_alpha[5:15, 5:15] = 255
            hand_image.putalpha(Image.fromarray(hand_alpha, mode="L"))
            hand_image.save(root / "right-hand.png")

            manifest = {
                "schema_version": 1,
                "canvas": {"width": 64, "height": 64},
                "side": "right",
                "fingers": {
                    "index": {
                        "polygon": [[14, 14], [28, 14], [28, 27], [14, 27]],
                        "pivot": [24, 24],
                        "joints": {
                            "pip": [21, 20],
                            "dip": [19, 17],
                            "tip": [18, 14]
                        }
                    }
                }
            }
            manifest_path = root / "finger-regions.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            character = {
                "layers": [{
                    "id": "right_hand", "role": "right_hand", "src": "right-hand.png",
                    "x": 10, "y": 10, "width": 20, "height": 20,
                    "pivot_x": .5, "pivot_y": .5
                }]
            }

            layers, joints, areas = _prepare_fingers(
                source, root, character, manifest_path
            )
            self.assertEqual(
                {layer["role"] for layer in layers},
                {"finger_index", "finger_index_middle", "finger_index_tip"},
            )
            for joint in ("right_index_base", "right_index_pip", "right_index_dip"):
                self.assertIn(joint, joints)
            self.assertEqual(areas["finger_index"], 100)
            total_segments = 0
            for layer in layers:
                with Image.open(root / layer["src"]) as opened:
                    finger = np.asarray(opened.convert("RGBA"), dtype=np.uint8)
                    # The red prop pixels inside the polygon are never part of a phalanx.
                    self.assertEqual(int(finger[:, :, 3][finger[:, :, 0] > 210].sum()), 0)
                    self.assertGreater(int(np.count_nonzero(finger[:, :, 3])), 12)
                    total_segments += int(np.count_nonzero(finger[:, :, 3]))
            self.assertGreaterEqual(
                total_segments, 100,
                "overlapping phalanx seams must preserve the full source finger silhouette",
            )

            with Image.open(root / "right-hand.png") as opened:
                palm_alpha = np.asarray(opened.convert("RGBA").getchannel("A"), dtype=np.uint8)
                self.assertEqual(int(palm_alpha[5, 5]), 0,
                    "only parent-hand pixels assigned to the finger are removed from the palm")

    def test_removes_embedded_violin_and_bow_from_static_torso_and_head_plates(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_size = (64, 64)
            torso = np.full((32, 36, 4), (34, 42, 48, 255), dtype=np.uint8)
            head = np.full((24, 24, 4), (170, 120, 92, 255), dtype=np.uint8)
            Image.fromarray(torso, mode="RGBA").save(root / "torso.png")
            Image.fromarray(head, mode="RGBA").save(root / "head.png")

            character = {
                "layers": [
                    {"role": "torso", "src": "torso.png", "x": 10, "y": 20},
                    {"role": "head", "src": "head.png", "x": 30, "y": 0},
                ]
            }
            violin = np.zeros(source_size, dtype=bool)
            bow = np.zeros(source_size, dtype=bool)
            violin[26:36, 20:34] = True
            bow[8:32, 25:28] = True
            bow[8:32, 37:40] = True

            report = _remove_embedded_props_from_static_layers(
                root,
                character,
                {"violin": violin, "bow": bow},
            )

            with Image.open(root / "torso.png") as opened:
                torso_after = np.asarray(opened.convert("RGBA"), dtype=np.uint8)
            with Image.open(root / "head.png") as opened:
                head_after = np.asarray(opened.convert("RGBA"), dtype=np.uint8)

            self.assertGreater(report["layers"]["torso"]["violin_pixels_removed"], 50)
            self.assertGreater(report["layers"]["torso"]["bow_pixels_removed"], 10)
            self.assertGreater(report["layers"]["head"]["bow_pixels_removed"], 10)
            self.assertGreater(report["total_pixels_removed"], 100)
            self.assertEqual(int(torso_after[5, 5, 3]), 255,
                "unrelated torso pixels must remain opaque")
            self.assertEqual(int(head_after[2, 2, 3]), 255,
                "unrelated head pixels must remain opaque")
            self.assertEqual(int(torso_after[8, 12, 3]), 0,
                "source violin pixels must be cleared from the static torso plate")
            self.assertEqual(int(torso_after[12, 16, 3]), 0,
                "source bow pixels must be cleared from the static torso plate")
            self.assertEqual(int(head_after[12, 8, 3]), 0,
                "source bow pixels must be cleared from the static head plate")

    def test_source_aligned_manifest_extracts_twelve_independent_limb_layers(self):
        import json
        import tempfile
        from pathlib import Path

        asset_root = (
            Path(__file__).resolve().parents[1]
            / "assets" / "characters" / "violin-prince-performance"
        )
        source_path = asset_root / "master-character-performance.webp"
        manifest_path = asset_root / "performance-regions.json"
        prop_manifest = json.loads(
            (asset_root / "instrument-props.json").read_text(encoding="utf-8")
        )
        with Image.open(source_path) as opened:
            source = opened.convert("RGBA")

        prop_masks = {}
        for name, specification in prop_manifest["props"].items():
            with Image.open(asset_root / specification["src"]) as opened:
                prop_alpha = np.asarray(opened.convert("RGBA").getchannel("A"), dtype=np.uint8)
            canvas = np.zeros((source.height, source.width), dtype=np.uint8)
            x, y = int(specification["x"]), int(specification["y"])
            canvas[y:y + prop_alpha.shape[0], x:x + prop_alpha.shape[1]] = prop_alpha
            prop_masks[name] = canvas

        with tempfile.TemporaryDirectory() as folder:
            layers, joints, report, moving = _authored_performance_layers(
                source,
                Path(folder),
                regions_manifest_path=manifest_path,
                prop_masks=prop_masks,
            )
            self.assertEqual(len(layers), 12)
            self.assertEqual(report["independent_layer_count"], 12)
            self.assertEqual(set(report["parts"]), {
                "left_upper_arm", "left_forearm", "left_hand",
                "right_upper_arm", "right_forearm", "right_hand",
                "left_thigh", "left_calf", "left_foot",
                "right_thigh", "right_calf", "right_foot",
            })
            self.assertEqual(len(joints), 12)
            self.assertGreater(int(moving.sum()), 30000)
            self.assertLessEqual(max(report["joint_overlap_pixels"].values()), 500)
            self.assertLessEqual(report["joint_overlap_pixels"]["left_ankle"], 200)
            self.assertLessEqual(report["joint_overlap_pixels"]["right_ankle"], 200)
            self.assertGreater(report["parts"]["left_hand"]["pixel_area"], 500)
            self.assertGreater(report["parts"]["right_hand"]["pixel_area"], 700)
            self.assertTrue(all((Path(folder) / layer["src"]).is_file() for layer in layers))

    def test_skin_mask_rejects_violin_wood_inside_hand_region(self):
        pixels = np.full((40, 60, 4), (30, 30, 30, 255), dtype=np.uint8)
        pixels[8:25, 5:22, :3] = (173, 121, 88)   # illustrated hand skin
        pixels[8:25, 34:51, :3] = (182, 98, 38)   # warm violin varnish
        image = Image.fromarray(pixels, mode="RGBA")
        allowed = np.zeros((40, 60), dtype=bool)
        allowed[2:31, 2:55] = True
        mask = _skin_material_mask(
            image,
            allowed,
            thresholds={
                "red_min": 120, "red_max": 240, "green_min": 70, "blue_min": 55,
                "red_minus_green_min": 20, "green_minus_blue_min": 10,
                "red_minus_blue_min": 35,
            },
        )
        self.assertTrue(mask[15, 14], "skin pixels must remain in the source-derived hand")
        self.assertFalse(mask[15, 43], "low-blue violin wood must not be classified as a finger")

    def test_clips_source_hand_from_violin_prop_without_changing_other_alpha(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            hand = Image.new("RGBA", (18, 16), (170, 115, 85, 0))
            hand_pixels = np.asarray(hand, dtype=np.uint8).copy()
            hand_pixels[4:13, 5:16, 3] = 255
            hand = Image.fromarray(hand_pixels, mode="RGBA")
            hand.save(root / "right_hand.png")

            violin = Image.new("RGBA", (30, 20), (125, 62, 30, 255))
            violin.save(root / "prop-violin.webp", format="WEBP", lossless=True)

            report = _clip_hand_from_violin_prop(
                root,
                violin_specification={"src": "violin-prop.webp", "x": 20, "y": 15},
                hand_layer={
                    "src": "right_hand.png",
                    "x": 27, "y": 20,
                    "width": 18, "height": 16,
                },
                dilation_radius=1,
            )
            with Image.open(root / "prop-violin.webp") as opened:
                result = np.asarray(opened.convert("RGBA"), dtype=np.uint8)

            self.assertEqual(report["method"], "source_hand_alpha_cutout_plus_one_pixel_seam")
            self.assertGreater(report["pixels_removed"], 40)
            self.assertEqual(int(result[13, 15, 3]), 0,
                "overlapping fretting-hand pixels must be transparent in the violin sprite")
            self.assertEqual(int(result[0, 0, 3]), 255,
                "the violin body outside the hand overlap must remain opaque")

    def test_edge_matte_rgb_repair_preserves_alpha_and_protected_props(self):
        pixels = np.zeros((32, 32, 4), dtype=np.uint8)
        pixels[:, :, :3] = (232, 234, 236)  # transparent pixels retain a pale source matte
        pixels[8:25, 8:25] = (34, 40, 43, 255)

        # Matte-contaminated edge pixels: fully opaque and partially antialiased.
        pixels[14, 7] = (184, 184, 182, 255)
        pixels[15, 7] = (162, 163, 161, 153)
        # A genuine warm skin edge and a protected pale prop edge must remain unchanged.
        pixels[16, 7] = (190, 126, 91, 255)
        pixels[22, 7] = (238, 232, 218, 255)

        source = Image.fromarray(pixels, mode="RGBA")
        protected = np.zeros((32, 32), dtype=bool)
        protected[22, 7] = True
        cleaned, report = _decontaminate_edge_matte_rgb(
            source,
            protected_masks=(protected,),
        )
        result = np.asarray(cleaned, dtype=np.uint8)

        self.assertEqual(report["method"], "distance_aware_neutral_matte_decontamination")
        self.assertGreater(report["pixels_recoloured"], 0)
        self.assertLess(int(result[14, 7, :3].mean()), 100,
            "neutral matte colour should be replaced by adjacent interior colour")
        self.assertLess(int(result[15, 7, :3].mean()), 100,
            "semi-transparent fringe RGB should also be decontaminated")
        self.assertEqual(tuple(result[16, 7]), (190, 126, 91, 255),
            "warm skin edge colour must not be changed")
        self.assertEqual(tuple(result[22, 7]), (238, 232, 218, 255),
            "known prop highlight must remain unchanged")
        np.testing.assert_array_equal(result[:, :, 3], pixels[:, :, 3])
        self.assertTrue(report["source_alpha_preserved"])
        self.assertTrue(report["source_silhouette_geometry_preserved"])


    def test_removes_multi_pixel_neutral_halo_without_erasing_interior_highlights(self):
        pixels = np.zeros((40, 40, 4), dtype=np.uint8)
        pixels[:, :, :3] = (232, 234, 236)
        pixels[8:32, 8:32] = (34, 40, 43, 255)

        # A three-pixel pale fringe runs along the top silhouette boundary.
        pixels[8:11, 13:27] = (190, 190, 190, 255)
        # This genuine bright detail is well inside the silhouette.
        pixels[17, 17] = (248, 248, 248, 255)
        # A known prop highlight on the boundary must remain untouched.
        pixels[8, 20] = (238, 232, 218, 255)

        source = Image.fromarray(pixels, mode="RGBA")
        protected = np.zeros((40, 40), dtype=bool)
        protected[8, 20] = True
        cleaned, report = _decontaminate_edge_matte_rgb(
            source,
            protected_masks=(protected,),
        )
        result = np.asarray(cleaned, dtype=np.uint8)

        self.assertEqual(report["method"], "distance_aware_neutral_matte_decontamination")
        self.assertGreater(report["pixels_recoloured"], 10)
        self.assertLess(int(result[8, 16, :3].mean()), 90)
        self.assertLess(int(result[9, 16, :3].mean()), 90)
        self.assertLess(int(result[10, 16, :3].mean()), 90)
        self.assertEqual(tuple(result[17, 17]), (248, 248, 248, 255))
        self.assertEqual(tuple(result[8, 20]), (238, 232, 218, 255))
        np.testing.assert_array_equal(result[:, :, 3], pixels[:, :, 3])
        self.assertTrue(report["source_alpha_preserved"])
        self.assertTrue(report["source_silhouette_geometry_preserved"])
        self.assertTrue(report["interior_highlights_preserved"])



    def test_head_expression_sequence_uses_phrase_peaks_and_note_energy(self):
        sequence = _build_head_expression_sequence({
            "note_events": [
                {"time": 0.0, "note": 60, "velocity": 72, "duration_seconds": 0.3},
                {"time": 0.7, "note": 61, "velocity": 55, "duration_seconds": 0.25},
                {"time": 1.5, "note": 72, "velocity": 90, "duration_seconds": 0.3},
                {"time": 2.2, "note": 74, "velocity": 80, "duration_seconds": 1.0},
            ]
        })
        self.assertEqual(sequence, ["focused", "neutral", "surprised", "happy"])
        self.assertLessEqual(len(sequence), 8)
        self.assertEqual(
            _build_head_expression_sequence({"note_events": []}),
            ["focused", "neutral", "focused", "happy"],
        )
        short_phrase = _build_head_expression_sequence({
            "note_events": [
                {"time": 0.0, "note": 64, "velocity": 110, "duration_seconds": 0.2},
                {"time": 0.5, "note": 65, "velocity": 100, "duration_seconds": 0.2},
            ]
        })
        self.assertEqual(short_phrase, ["focused", "neutral", "happy"])

    def test_preview_music_sync_uses_explicit_tempo_grid_when_no_audio_is_attached(self):
        timing = _build_preview_music_sync(8, bpm=100)
        self.assertEqual(timing["status"], "preview_grid")
        self.assertEqual(timing["source"], "preview_tempo_grid_no_audio_asset")
        self.assertFalse(timing["audio_attached"])
        self.assertEqual(timing["bpm"], 100)
        self.assertAlmostEqual(timing["beat_times"][0], 0.0)
        self.assertAlmostEqual(timing["beat_times"][1], 0.6)
        self.assertEqual(timing["downbeats"], timing["beat_times"][::4])
        self.assertGreater(len(timing["onsets"]), 0)

    def test_preview_music_sync_validates_sampled_violin_audio_against_note_event_map(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as folder:
            audio_path = Path(folder) / "sampled-violin.wav"
            audio_path.write_bytes(b"mock audio payload")
            music_map = {
                "audio_source": "sampled_violin_cc0",
                "license": "CC0-1.0",
                "attribution": "Versilian Studios",
                "duration_seconds": 24.0,
                "bpm": 80.0,
                "beat_times": [round(index * 0.75, 4) for index in range(32)],
                "downbeats": [round(index * 0.75, 4) for index in range(0, 32, 4)],
                "onsets": [0.0, 1.5, 3.0, 4.5, 6.0, 7.5, 9.0],
                "note_events": [
                    {"time": 0.0, "note": 62, "velocity": 60, "duration_seconds": 1.5},
                    {"time": 1.5, "note": 65, "velocity": 58, "duration_seconds": 0.75},
                    {"time": 3.0, "note": 67, "velocity": 64, "duration_seconds": 0.75},
                    {"time": 4.5, "note": 69, "velocity": 72, "duration_seconds": 1.5},
                    {"time": 6.0, "note": 72, "velocity": 78, "duration_seconds": 0.75},
                    {"time": 7.5, "note": 70, "velocity": 66, "duration_seconds": 0.75},
                    {"time": 9.0, "note": 69, "velocity": 70, "duration_seconds": 1.5},
                ],
            }
            verified_analysis = {
                "status": "metadata_verified",
                "source": "declared_bpm_and_arrangement_event_map",
                "decode_backend": "soundfile",
                "duration_seconds": 24.0,
                "bpm": 80.0,
                "confidence": 1.0,
                "beat_times": music_map["beat_times"],
                "downbeats": music_map["downbeats"],
                "onsets": music_map["onsets"],
            }
            with patch("audio_analysis.analyse_audio_file", return_value=verified_analysis) as analyse:
                timing = _build_preview_music_sync(
                    8, audio_path=audio_path, music_map=music_map
                )

            analyse.assert_called_once_with(
                audio_path,
                known_bpm=80.0,
                known_beat_times=music_map["beat_times"],
                known_downbeats=music_map["downbeats"],
                known_onsets=music_map["onsets"],
            )
            self.assertEqual(timing["status"], "metadata_verified")
            self.assertEqual(timing["source"], "sampled_violin_cc0")
            self.assertTrue(timing["audio_attached"])
            self.assertEqual(timing["audio_license"], "CC0-1.0")
            self.assertEqual(timing["event_map_source"], "sampled_violin_arrangement_note_events")
            self.assertEqual(timing["bpm"], 80.0)
            self.assertEqual(timing["beat_times"], music_map["beat_times"][:11])
            self.assertEqual(timing["downbeats"], [0.0, 3.0, 6.0])
            self.assertEqual(timing["onsets"], music_map["onsets"][:6])
            self.assertEqual(timing["decode_backend"], "soundfile")
            self.assertEqual(len(timing["note_events"]), 6)
            self.assertEqual(timing["note_events"][0]["note"], 62)
            self.assertEqual(timing["note_events"][-1]["time"], 7.5)

    def test_segmented_source_base_preserves_untouched_pixels_and_alpha(self):
        import tempfile
        from pathlib import Path
        import cv2

        source = Image.new("RGBA", (80, 80), (42, 48, 55, 255))
        pixels = np.asarray(source, dtype=np.uint8).copy()
        pixels[12:68, 12:68, :3] = (30, 35, 40)
        pixels[12:68, 12:68, 3] = 255
        source = Image.fromarray(pixels, mode="RGBA")
        original = np.asarray(source, dtype=np.uint8)

        # A source-colour head patch is replaced by modular reference head plates.
        pixels[10:24, 10:24, :3] = (214, 168, 132)
        source = Image.fromarray(pixels, mode="RGBA")
        original = np.asarray(source, dtype=np.uint8)
        moving = np.zeros((80, 80), dtype=bool)
        moving[22:52, 20:35] = True
        head = np.zeros((80, 80), dtype=np.uint8)
        head[10:24, 10:24] = 255
        bow = np.zeros((80, 80), dtype=np.uint8)
        bow[18:58, 38:41] = 255
        violin = np.zeros((80, 80), dtype=np.uint8)
        violin[28:50, 48:63] = 255

        with tempfile.TemporaryDirectory() as folder:
            report = _build_segmented_source_base(
                source,
                Path(folder),
                bow_canvas_alpha=bow,
                violin_canvas_alpha=violin,
                moving_mask=moving,
                head_canvas_alpha=head,
            )
            with Image.open(Path(folder) / report["src"]) as opened:
                output = np.asarray(opened.convert("RGBA"), dtype=np.uint8)

        self.assertEqual(report["mode"], "segmented_source_body")
        self.assertLess(report["z_index"], 4,
            "the underpaint must remain behind the thigh/calf/foot sprites")
        self.assertGreater(report["pixels_cut_from_source"], 900)
        np.testing.assert_array_equal(output[:, :, 3], original[:, :, 3])
        untouched = np.ones((80, 80), dtype=bool)
        cut = cv2.dilate(
            (moving | (bow > 12) | (violin > 12) | (head > 12)).astype(np.uint8),
            np.ones((5, 5), dtype=np.uint8),
        ) > 0
        cut &= original[:, :, 3] > 12
        untouched &= ~cut
        np.testing.assert_array_equal(output[untouched], original[untouched])
        self.assertGreater(report["violin_pixels_reconstructed"], 0)
        self.assertGreater(report["bow_pixels_reconstructed"], 0)
        self.assertGreater(report["head_pixels_reconstructed"], 100)
        self.assertTrue(report["head_plate_replacement_enabled"])
        self.assertEqual(report["head_cutout_method"], "source_aligned_autorig_head_and_face_alpha")
        self.assertEqual(
            report["underpaint_quality"],
            "approximate_nonsemantic_inpaint_requires_manual_art_reconstruction",
            "inpainted hidden regions must not be represented as finished anatomical artwork",
        )
        self.assertLess(float(output[16, 16, :3].mean()), 100.0,
            "the original head pixels must be reconstructed under the modular head plates")
        self.assertTrue(report["source_alpha_preserved"])
        self.assertTrue(report["source_pixels_outside_cut_mask_preserved"])


    def test_segmented_underpaint_does_not_sample_white_transparent_matte_pixels(self):
        import tempfile
        from pathlib import Path

        pixels = np.full((64, 64, 4), (246, 246, 246, 0), dtype=np.uint8)
        # A dark source character sits directly against transparent white RGB.
        yy, xx = np.mgrid[:64, :64]
        visible = (xx >= 4) & (xx < 60) & (yy >= 4) & (yy < 60)
        shade = (30 + ((xx + yy) % 18)).astype(np.uint8)
        pixels[visible, 0] = shade[visible]
        pixels[visible, 1] = (shade[visible] + 5)
        pixels[visible, 2] = (shade[visible] + 9)
        pixels[visible, 3] = 255
        source = Image.fromarray(pixels, mode="RGBA")
        
        # The cut reaches the outer silhouette, where transparent white RGB
        # used to seed Telea and create a pale streak in the reconstructed plate.
        bow = np.zeros((64, 64), dtype=np.uint8)
        bow[8:56, 4:27] = 255
        violin = np.zeros((64, 64), dtype=np.uint8)
        moving = np.zeros((64, 64), dtype=bool)

        with tempfile.TemporaryDirectory() as folder:
            report = _build_segmented_source_base(
                source,
                Path(folder),
                bow_canvas_alpha=bow,
                violin_canvas_alpha=violin,
                moving_mask=moving,
            )
            with Image.open(Path(folder) / report["src"]) as opened:
                result = np.asarray(opened.convert("RGBA"), dtype=np.uint8)

        # Check all visible pixels reconstructed from the cut; they should
        # remain in the dark character range, never pick up the white matte.
        import cv2
        cut = cv2.dilate(
            (bow > 12).astype(np.uint8),
            np.ones((5, 5), np.uint8),
            iterations=1,
        ) > 0
        cut &= pixels[:, :, 3] > 12
        self.assertGreater(int(cut.sum()), 100)
        self.assertLess(float(result[cut, :3].mean()), 100.0)
        np.testing.assert_array_equal(result[:, :, 3], pixels[:, :, 3])
        self.assertTrue(report["transparent_rgb_excluded_from_reconstruction"])
        self.assertGreater(report["transparent_source_pixels_excluded_from_inpaint"], 500)

    def test_shoe_mask_isolated_from_trouser_and_connected_to_bottom(self):
        width, height, split_x = 100, 120, 50
        rgb = np.full((height, width, 3), 220, dtype=np.uint8)
        alpha = np.zeros((height, width), dtype=np.uint8)
        # Lower trouser leg ends just above the shoe band.
        rgb[82:112, 18:39] = 32
        alpha[82:112, 18:39] = 255
        # Shoe is a distinct dark connected foreground component at the bottom.
        rgb[111:120, 12:43] = 28
        alpha[111:120, 12:43] = 255
        mask = _foot_mask(rgb, alpha, side="left", split_x=split_x)
        self.assertGreater(int(mask.sum()), 100)
        self.assertTrue(mask[116, 25])
        self.assertFalse(mask[90, 25])

    def test_leg_layers_create_hip_knee_ankle_anchors_for_both_sides(self):
        width, height = 240, 300
        pixels = np.zeros((height, width, 4), dtype=np.uint8)
        labels = np.zeros((height, width), dtype=np.uint8)
        # A torso with two distinct leg columns and a gap between the shoes.
        pixels[48:126, 92:148] = (30, 31, 34, 255)
        labels[48:126, 92:148] = 2
        pixels[120:186, 88:116] = (35, 35, 38, 255)
        pixels[120:186, 126:154] = (35, 35, 38, 255)
        labels[120:186, 88:116] = 5
        labels[120:186, 126:154] = 5
        pixels[180:270, 88:112] = (32, 33, 35, 255)
        pixels[180:270, 132:156] = (32, 33, 35, 255)
        labels[180:270, 88:112] = 6
        labels[180:270, 132:156] = 6
        pixels[267:299, 72:115] = (18, 18, 20, 255)
        pixels[267:299, 130:173] = (18, 18, 20, 255)
        source = Image.fromarray(pixels, mode="RGBA")
        character = {"layers":[{"role":"torso","x":92,"y":48,"width":56,"height":78}]}

        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            layers, joints, report = _leg_layers(source, labels, character, Path(folder))
            self.assertEqual(len(layers), 6)
            for side in ("left", "right"):
                for joint in ("hip", "knee", "ankle"):
                    self.assertIn(side + "_" + joint, joints)
                    self.assertGreaterEqual(joints[side + "_" + joint]["x"], 0)
                    self.assertLessEqual(joints[side + "_" + joint]["x"], 1)
            self.assertTrue(report["review_required"])
            z_by_role = {layer["role"]: layer["z_index"] for layer in layers}
            for side in ("left", "right"):
                self.assertLess(z_by_role[side + "_thigh"], z_by_role[side + "_calf"])
                self.assertLess(z_by_role[side + "_calf"], z_by_role[side + "_foot"])
            self.assertTrue(all((Path(folder) / layer["src"]).is_file() for layer in layers))


if __name__ == "__main__":
    unittest.main()
