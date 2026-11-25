import unittest
from verify_master_director_render import _scene_for_interval

class MasterDirectorRenderVerifierTests(unittest.TestCase):
    def test_intervals_never_cross_shot_boundaries(self):
        scenes=[{"id":"a","start":0,"duration":3},{"id":"b","start":3,"duration":3}]
        self.assertEqual(_scene_for_interval(scenes,.5,.75)["id"],"a")
        self.assertIsNone(_scene_for_interval(scenes,2.75,3.0))
        self.assertEqual(_scene_for_interval(scenes,3.0,3.25)["id"],"b")

if __name__=="__main__": unittest.main()
