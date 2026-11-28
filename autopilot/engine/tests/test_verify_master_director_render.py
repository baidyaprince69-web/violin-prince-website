import unittest
from verify_master_director_render import scene_for_interval, presenter_visible_in_scene

class MasterDirectorRenderVerifierTests(unittest.TestCase):
    def test_intervals_never_cross_shot_boundaries(self):
        scenes=[{"id":"a","start":0,"duration":3},{"id":"b","start":3,"duration":3}]
        self.assertEqual(scene_for_interval(scenes,.5,.75)["id"],"a")
        self.assertIsNone(scene_for_interval(scenes,2.75,3.0))
        self.assertEqual(scene_for_interval(scenes,3.0,3.25)["id"],"b")

    def test_performer_visibility_is_taken_from_each_director_shot(self):
        visible={"id":"opening","character_actions":{"violin-prince":{"visible":True}}}
        hidden={"id":"mechanism","character_actions":{"violin-prince":{"visible":False}}}
        self.assertTrue(presenter_visible_in_scene(visible,"violin-prince"))
        self.assertFalse(presenter_visible_in_scene(hidden,"violin-prince"))

    def test_missing_visibility_is_rejected_instead_of_defaulting_to_visible(self):
        with self.assertRaisesRegex(Exception,"explicit character visibility"):
            presenter_visible_in_scene({"id":"missing","character_actions":{}},"violin-prince")

if __name__=="__main__": unittest.main()
