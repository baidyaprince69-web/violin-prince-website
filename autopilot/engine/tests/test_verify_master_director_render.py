import unittest
from verify_master_director_render import scene_for_interval, presenter_visible_in_scene, bow_slide_motion_verified

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

    def test_measured_bow_slide_requires_travel_attachment_grip_and_no_free_translation(self):
        valid = {
            "bow_attached_tip_travel_range_px": 31.5,
            "presenter_bow_attached_transform_track_count": 1,
            "bow_grip_attachment_error_max_px": 0.25,
            "presenter_bow_translation_track_count": 0,
        }
        self.assertTrue(bow_slide_motion_verified(valid))

        for key, value in (
            ("bow_attached_tip_travel_range_px", 25.99),
            ("presenter_bow_attached_transform_track_count", 0),
            ("bow_grip_attachment_error_max_px", 0.51),
            ("bow_grip_attachment_error_max_px", None),
            ("presenter_bow_translation_track_count", 1),
        ):
            candidate = {**valid, key: value}
            with self.subTest(key=key, value=value):
                self.assertFalse(bow_slide_motion_verified(candidate))

if __name__=="__main__": unittest.main()
