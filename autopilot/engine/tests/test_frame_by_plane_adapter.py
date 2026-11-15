"""Pure-Python safety tests for the Frame By Plane layer manifest."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ENGINE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ENGINE))
from frame_by_plane_adapter import FrameByPlaneError,load_background_manifest


class FrameByPlaneManifestTests(unittest.TestCase):
    def make_bundle(self,root,layers=None):
        (root/"background.png").write_bytes(b"\x89PNG\r\n\x1a\n"+b"x"*128)
        data={
            "schema_version":1,"style":"midnight_resonance","resolution":[1080,1920],
            "layers":layers or [{
                "name":"Distant Environment","file":"background.png","role":"background",
                "distance":3.0,"cover_scale":1.4,
            }],
        }
        path=root/"background-manifest.json"
        path.write_text(json.dumps(data),encoding="utf-8")
        return path

    def test_valid_bundle_resolves_story_layer(self):
        with tempfile.TemporaryDirectory() as temp:
            result=load_background_manifest(self.make_bundle(Path(temp)))
            self.assertEqual(result["style"],"midnight_resonance")
            self.assertEqual(result["layers"][0]["file_names"],["background.png"])

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            path=self.make_bundle(root,[{"name":"Escaping layer","file":"../outside.png"}])
            with self.assertRaises(FrameByPlaneError):
                load_background_manifest(path)

    def test_rejects_duplicate_layer_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/"other.png").write_bytes(b"\x89PNG\r\n\x1a\n"+b"x"*128)
            path=self.make_bundle(root,[
                {"name":"Same Layer","file":"background.png"},
                {"name":"same-layer","file":"other.png"},
            ])
            with self.assertRaises(FrameByPlaneError):
                load_background_manifest(path)

    def test_rejects_missing_media(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            path=self.make_bundle(root,[{"name":"Missing","file":"missing.png"}])
            with self.assertRaises(FrameByPlaneError):
                load_background_manifest(path)

    def test_rejects_out_of_range_depth(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            path=self.make_bundle(root,[{
                "name":"Too far","file":"background.png","distance":100,
            }])
            with self.assertRaises(FrameByPlaneError):
                load_background_manifest(path)


if __name__=="__main__":
    unittest.main()
