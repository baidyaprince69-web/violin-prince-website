"""Offline tests for the GitHub-native procedural scene-art renderer."""
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageChops, ImageStat
ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))
from procedural_visuals import render_scene_art


class ProceduralSceneArtTests(unittest.TestCase):
    def test_scene_image_is_created_in_portrait_colour(self):
        with tempfile.TemporaryDirectory() as folder:
            target=render_scene_art("Cinematic violin macro view with amber varnish.",0,
                {"visual_mode":"macro_3d","caption":"Violin resonance"},{"title":"Resonance"},Path(folder)/"scene.jpg")
            self.assertTrue(target.is_file())
            with Image.open(target) as image:
                self.assertEqual(image.size,(720,1280))
                self.assertEqual(image.mode,"RGB")
                self.assertGreater(len(image.getcolors(720*1280) or []),1000)

    def test_output_is_deterministic_for_the_same_scene(self):
        with tempfile.TemporaryDirectory() as folder:
            args=("Cinematic violin macro view.",1,{"visual_mode":"macro_3d"},{"title":"Test"})
            first=render_scene_art(*args,Path(folder)/"a.jpg")
            second=render_scene_art(*args,Path(folder)/"b.jpg")
            with Image.open(first) as a, Image.open(second) as b:
                self.assertIsNone(ImageChops.difference(a,b).getbbox())

    def test_modes_produce_distinct_compositions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            violin=render_scene_art("Violin body",0,{"visual_mode":"macro_3d"},{},root/"violin.jpg")
            wave=render_scene_art("Sound frequencies",1,{"visual_mode":"waveform"},{},root/"wave.jpg")
            mechanism=render_scene_art("Acoustic resonance",2,{"visual_mode":"mechanism_cutaway"},{},root/"mechanism.jpg")
            with Image.open(violin) as a, Image.open(wave) as b:
                self.assertIsNotNone(ImageChops.difference(a,b).getbbox())
            with Image.open(wave) as a, Image.open(mechanism) as b:
                self.assertIsNotNone(ImageChops.difference(a,b).getbbox())

    def test_empty_prompt_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"cannot be empty"):
            render_scene_art(" ",0,{},{})

    def test_colour_and_detail_range(self):
        with tempfile.TemporaryDirectory() as folder:
            path=render_scene_art("Violin stage",2,{"visual_mode":"cover_performance"},{},Path(folder)/"scene.jpg")
            with Image.open(path) as image:
                self.assertGreater(max(ImageStat.Stat(image).stddev),15)
                self.assertGreater(len(set(image.resize((64,64)).getdata())),500)


if __name__=="__main__":
    unittest.main()
