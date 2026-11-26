import json,tempfile,unittest
from pathlib import Path
from create_master_director_video_project import DirectorVideoProjectError,create_master_director_video_project

def make_plan():
    shots=[]
    for i in range(8):
        start=i*3
        shots.append({
          "id":f"shot-{i+1:02d}","start_seconds":start,"end_seconds":start+3,
          "purpose":"hook" if i==0 else "ending" if i==7 else "reveal",
          "visual_subject":f"Violin performance beat {i+1}",
          "setting":"A concert hall with moving stage lights",
          "visual_description":f"Distinct visual and camera beat {i+1}.",
          "composition":"Full-body performer centred with separate stage depth.",
          "camera":{"shot_size":["wide","medium","close_up"][i%3],"angle":"front three-quarter",
                    "movement":["dolly_in","truck_left","orbit","tilt"][i%4],"focus":"Violin player and bow"},
          "animation":{"subject_action":"The violin performer bows and fingers in time.",
                       "environment_motion":"Stage lighting and particles move separately.",
                       "graphic_action":"","depth_motion":"Foreground and background move at different rates.",
                       "motion_rationale":"Movement follows the phrase."},
          "procedural_scene":{"environment":"concert_stage","objects":[
            {"id":f"orb-{i}","kind":"orb","x":.25,"y":.35,"size":22,"color":"#DDAA55","motion":"pulse","period_seconds":1.8},
            {"id":f"spark-{i}","kind":"spark","x":.75,"y":.62,"size":16,"color":"#AABBCC","motion":"float","period_seconds":2.2}]},
          "character_action":{"visible":True,"gesture":"violin_performance","expression":"focused","loop":True,"cycle_duration_seconds":2.4},
          "transition_to_next":"match_cut" if i==0 else "whip_pan" if i==1 else "cut" if i<7 else "none",
          "narration_cue":f"Approved narration beat {i+1}","music_cue":f"Measured violin phrase {i+1}","graphic_data":None,
        })
    return {
      "schema_version":2,"render_mode":"procedural_2d",
      "story_understanding":{"central_truth":"A full-body violin performance follows the measured phrase.",
       "viewer_question":"How does the player shape the phrase?","emotional_arc":["anticipation","expression","resolution"],
       "key_revelations":["Bow travel","Finger articulation"]},
      "visual_concept":{"concept_name":"Resonant Hall","visual_metaphor":"Light moves with the phrase.",
       "creative_rationale":"The hall responds to the music.","art_direction":"Original cinematic concert stage.",
       "palette":{"dominant":"#12182A","secondary":"#CED8E2","accent":"#DDAA55","harmony":"temperature_contrast",
                  "reasoning":"Cool hall with warm accents.","contrast_strategy":"High contrast and readable space."},
       "lighting_plan":"Warm key with cool rim.","composition_language":"Full-body, instrument and depth."},
      "storyboard":{"duration_seconds":24,"shots":shots},
      "edit_direction":{"pacing":"Measured phrases.","transition_language":"Directed match cuts and whip pans.",
       "typography":"Minimal readable type.","sound_design":"Restrained stage ambience.","music_mood":"Expressive solo violin.",
       "music_sync_cues":[{"time_seconds":6,"event":"Phrase reveal","reason":"Measured downbeat."},
                          {"time_seconds":12,"event":"Middle phrase","reason":"Measured downbeat."},
                          {"time_seconds":21,"event":"Final resolution","reason":"Measured downbeat."}],
       "final_payoff":"Resolve on the performer and final note."},
    }

def make_base_project():
    roles=["torso","head","left_upper_arm","left_forearm","left_hand","right_upper_arm","right_forearm","right_hand",
      "left_thigh","left_calf","left_foot","right_thigh","right_calf","right_foot",
      "finger_index","finger_index_middle","finger_index_tip","finger_middle","finger_middle_middle","finger_middle_tip",
      "finger_ring","finger_ring_middle","finger_ring_tip","finger_little","finger_little_middle","finger_little_tip"]
    beats=[round(i*.75,5) for i in range(32)]
    notes=[{"time":round(i*.75+.1,5),"note":60+i%12,"velocity":84,"duration_seconds":.42} for i in range(32)]
    sync={"status":"passed","source":"sampled_violin_cc0","audio_attached":True,"bpm":80.0,"confidence":.95,
      "duration_seconds":24.0,"beat_times":beats,"downbeats":beats[::4],
      "onsets":[n["time"] for n in notes],"note_events":notes,"event_map_source":"sampled_violin_arrangement_note_events"}
    character={"id":"violin-prince","performance":{"instrument_performance":True},
      "layers":[{"id":r,"role":r,"src":"assets/"+r+".png"} for r in roles],
      "props":{"violin":{"id":"violin","src":"violin.png"},"bow":{"id":"bow","src":"bow.png"}}}
    return {"schema_version":4,"render_mode":"preview_only","duration_seconds":24,
      "publishing":{"enabled":False,"preview_only":True,"schedule_enabled":False},
      "characters":[character],"scenes":[{"id":"base","start":0,"duration":24,
        "character_actions":{"violin-prince":{"visible":True,"instrument_performance":True,
          "gesture":"violin_performance","expression":"focused","x":46,"y":58,"scale":.84,"music_sync":sync}}}]}

class MasterDirectorVideoProjectTests(unittest.TestCase):
    def test_compiles_eight_full_body_scenes_and_local_audio_maps(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); base=root/"base.json"; plan=root/"plan.json"; out=root/"project.json"
            base.write_text(json.dumps(make_base_project()),encoding="utf-8")
            plan.write_text(json.dumps(make_plan()),encoding="utf-8")
            result=create_master_director_video_project(base,plan,out)
            project=json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(result["shot_count"],8); self.assertFalse(result["rendered"])
        self.assertFalse(result["published"]); self.assertFalse(result["production_approved"])
        self.assertEqual(len(project["scenes"]),8)
        self.assertTrue(all(s["visual_mode"]=="full_body_performance" for s in project["scenes"]))
        self.assertEqual(project["scenes"][-1]["start"]+project["scenes"][-1]["duration"],24)
        self.assertEqual(project["scenes"][3]["character_actions"]["violin-prince"]["gesture"],"violin_performance")
        self.assertEqual(project["scenes"][3]["character_actions"]["violin-prince"]["music_sync"]["beat_times"][0],0)
        self.assertEqual(project["scenes"][0]["stagecraft"]["music_sync_cues"],[])
        self.assertEqual(project["scenes"][2]["stagecraft"]["music_sync_cues"][0]["time_seconds"],6)
        self.assertEqual(project["diagnostics"]["music_sync_cue_count"],3)
        self.assertTrue(project["diagnostics"]["measured_audio_sync_verified"])
        self.assertTrue(project["diagnostics"]["test_only_audio"])
        self.assertFalse(project["publishing"]["enabled"])

    def test_duration_mismatch_is_rejected_without_stretching(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); base=make_base_project(); plan=make_plan()
            plan["storyboard"]["duration_seconds"]=32
            # Keep the mismatch fixture internally valid: eight contiguous four-second
            # shots cover the 32-second storyboard while the decoded base audio stays 24s.
            for index, shot in enumerate(plan["storyboard"]["shots"]):
                shot["start_seconds"]=index*4
                shot["end_seconds"]=(index+1)*4
            bp=root/"base.json"; pp=root/"plan.json"
            bp.write_text(json.dumps(base)); pp.write_text(json.dumps(plan))
            with self.assertRaisesRegex(DirectorVideoProjectError,"must match decoded audio"):
                create_master_director_video_project(bp,pp,root/"out.json")

    def test_missing_bow_prop_blocks_the_handoff(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); base=make_base_project(); base["characters"][0]["props"].pop("bow")
            bp=root/"base.json"; pp=root/"plan.json"
            bp.write_text(json.dumps(base)); pp.write_text(json.dumps(make_plan()))
            with self.assertRaisesRegex(DirectorVideoProjectError,"both violin and bow"):
                create_master_director_video_project(bp,pp,root/"out.json")

    def test_low_confidence_audio_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); base=make_base_project()
            base["scenes"][0]["character_actions"]["violin-prince"]["music_sync"]["confidence"]=.1
            bp=root/"base.json"; pp=root/"plan.json"
            bp.write_text(json.dumps(base)); pp.write_text(json.dumps(make_plan()))
            with self.assertRaisesRegex(DirectorVideoProjectError,"confidence"):
                create_master_director_video_project(bp,pp,root/"out.json")

if __name__=="__main__": unittest.main()
