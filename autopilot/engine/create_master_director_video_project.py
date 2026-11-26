"""Compile a validated Master Director storyboard onto the complete Violin Prince rig."""
from __future__ import annotations
import argparse, copy, json, math, re, sys
from pathlib import Path
from typing import Any
ENGINE_DIR=Path(__file__).resolve().parent
if str(ENGINE_DIR) not in sys.path: sys.path.insert(0,str(ENGINE_DIR))
from master_creative_director import require_valid_director_plan  # noqa: E402

class DirectorVideoProjectError(ValueError):
    """A storyboard or source audio map cannot safely drive the performance rig."""

SAFE_ID=re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
REQUIRED_ROLES={
 "torso","head","left_upper_arm","left_forearm","left_hand",
 "right_upper_arm","right_forearm","right_hand",
 "left_thigh","left_calf","left_foot","right_thigh","right_calf","right_foot",
 "finger_index","finger_index_middle","finger_index_tip",
 "finger_middle","finger_middle_middle","finger_middle_tip",
 "finger_ring","finger_ring_middle","finger_ring_tip",
 "finger_little","finger_little_middle","finger_little_tip",
}
ENVIRONMENTS={"city_night","forest_dusk","space","concert_stage","laboratory","abstract"}

def read_json(path: str|Path,label: str)->dict[str,Any]:
    try: value=json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise DirectorVideoProjectError(f"{label} could not be read as JSON: {exc}") from exc
    if not isinstance(value,dict): raise DirectorVideoProjectError(f"{label} must be a JSON object.")
    return value

def validate_base(project:dict[str,Any])->tuple[dict[str,Any],dict[str,Any],float]:
    if project.get("schema_version")!=4 or project.get("render_mode")!="preview_only":
        raise DirectorVideoProjectError("Base must be a schema-version-4 preview-only Motion project.")
    publishing=project.get("publishing") or {}
    if publishing.get("enabled") is not False or publishing.get("preview_only") is not True or publishing.get("schedule_enabled") is not False:
        raise DirectorVideoProjectError("Publishing and scheduling must be explicitly disabled.")
    characters=project.get("characters")
    if not isinstance(characters,list) or len(characters)!=1:
        raise DirectorVideoProjectError("Exactly one source-aligned Violin Prince character is required.")
    character=characters[0]
    if character.get("performance",{}).get("instrument_performance") is not True:
        raise DirectorVideoProjectError("The character bundle is not marked as an instrument-performance rig.")
    roles={str(layer.get("role") or "") for layer in character.get("layers",[]) if isinstance(layer,dict)}
    missing=sorted(REQUIRED_ROLES-roles)
    if missing: raise DirectorVideoProjectError("Full-body rig layers are missing: "+", ".join(missing))
    if not {"violin","bow"}.issubset(set((character.get("props") or {}).keys())):
        raise DirectorVideoProjectError("The source-aligned character must include both violin and bow props.")
    scenes=project.get("scenes")
    if not isinstance(scenes,list) or len(scenes)!=1:
        raise DirectorVideoProjectError("Base project must contain one validated source-audio scene.")
    actions=scenes[0].get("character_actions") or {}
    action=actions.get(character["id"])
    if not isinstance(action,dict) or action.get("instrument_performance") is not True:
        raise DirectorVideoProjectError("Base project has no full-body instrument-performance action.")
    sync=action.get("music_sync")
    if not isinstance(sync,dict) or sync.get("audio_attached") is not True:
        raise DirectorVideoProjectError("A decoded audio file and its measured event map are required.")
    confidence=sync.get("confidence"); bpm=sync.get("bpm")
    if isinstance(confidence,bool) or not isinstance(confidence,(int,float)) or confidence<.28:
        raise DirectorVideoProjectError("Audio beat confidence must be at least 0.28.")
    if isinstance(bpm,bool) or not isinstance(bpm,(int,float)) or not 40<=bpm<=240:
        raise DirectorVideoProjectError("Measured music tempo must be between 40 and 240 BPM.")
    if not isinstance(sync.get("beat_times"),list) or len(sync["beat_times"])<2:
        raise DirectorVideoProjectError("Decoded audio must contain at least two measured beats.")
    if not isinstance(sync.get("onsets"),list) or not sync["onsets"]:
        raise DirectorVideoProjectError("Decoded audio must contain measured note/onset events.")
    if not isinstance(sync.get("note_events"),list) or len(sync["note_events"])<4:
        raise DirectorVideoProjectError("Full-body fingering requires at least four measured note events.")
    duration=float(project.get("duration_seconds") or 0)
    if not math.isfinite(duration) or not 20<=duration<=60:
        raise DirectorVideoProjectError("Source-audio duration must be between 20 and 60 seconds.")
    if abs(float(sync.get("duration_seconds") or 0)-duration)>.08:
        raise DirectorVideoProjectError("Measured audio map does not cover the complete base-project duration.")
    return character,action,duration

def valid_times(sync:dict[str,Any],field:str,duration:float)->list[float]:
    values=[]
    for raw in sync.get(field) or []:
        if isinstance(raw,bool): continue
        try: value=float(raw)
        except (TypeError,ValueError): continue
        if math.isfinite(value) and 0<=value<duration: values.append(round(value,5))
    return sorted(set(values))

def align_cues(plan:dict[str,Any],sync:dict[str,Any],duration:float)->list[dict[str,Any]]:
    raw=(plan.get("edit_direction") or {}).get("music_sync_cues")
    beats=valid_times(sync,"beat_times",duration)
    if not isinstance(raw,list) or len(raw)<2 or len(beats)<2:
        raise DirectorVideoProjectError("At least two director cues and two measured audio beats are required.")
    aligned=[]
    for i,cue in enumerate(raw):
        if not isinstance(cue,dict): raise DirectorVideoProjectError(f"Music cue {i+1} must be an object.")
        requested=cue.get("time_seconds")
        if isinstance(requested,bool) or not isinstance(requested,(int,float)) or not 0<=requested<duration:
            raise DirectorVideoProjectError(f"Music cue {i+1} falls outside the audio duration.")
        beat=min(beats,key=lambda item:abs(item-float(requested)))
        error=abs(beat-float(requested))
        if error>.38: raise DirectorVideoProjectError(f"Music cue {i+1} is {error:.3f}s away from the measured beat grid.")
        event=str(cue.get("event") or "").strip(); reason=str(cue.get("reason") or "").strip()
        if not event or not reason: raise DirectorVideoProjectError(f"Music cue {i+1} needs an event and reason.")
        aligned.append({"time_seconds":round(beat,5),"event":event,"reason":reason,
                        "requested_time_seconds":round(float(requested),5),
                        "source_time_seconds":round(beat,5),"alignment_error_seconds":round(error,5),
                        "timing_source":"decoded_audio_beat_map"})
    aligned.sort(key=lambda item:item["time_seconds"])
    if any(aligned[i]["time_seconds"]<=aligned[i-1]["time_seconds"] for i in range(1,len(aligned))):
        raise DirectorVideoProjectError("Music cues must resolve to distinct measured beats.")
    return aligned

def slice_sync(sync:dict[str,Any],start:float,end:float)->dict[str,Any]:
    duration=end-start
    def local(field:str)->list[float]:
        return [round(t-start,5) for t in valid_times(sync,field,float(sync["duration_seconds"])) if start-1e-5<=t<end-1e-5]
    notes=[]
    for event in sync.get("note_events") or []:
        try:
            t=float(event["time"]); note=int(event["note"]); velocity=int(event["velocity"])
            note_duration=float(event.get("duration_seconds",.2))
        except (KeyError,TypeError,ValueError): continue
        if start-1e-5<=t<end-1e-5:
            notes.append({"time":round(t-start,5),"note":note,"velocity":velocity,"duration_seconds":note_duration})
    return {
      "status":sync.get("status","analysed"),"source":sync.get("source") or sync.get("analysis_source") or "decoded_audio",
      "audio_attached":True,"bpm":float(sync["bpm"]),"confidence":float(sync["confidence"]),
      "duration_seconds":round(duration,5),"beat_times":local("beat_times"),"downbeats":local("downbeats"),
      "onsets":local("onsets"),"note_events":notes,"audio_license":sync.get("audio_license"),
      "audio_attribution":sync.get("audio_attribution"),"event_map_source":sync.get("event_map_source"),
      "analysis_status":sync.get("analysis_status"),"analysis_source":sync.get("analysis_source"),
    }

def create_master_director_video_project(base_project_path:str|Path,director_plan_path:str|Path,output_path:str|Path)->dict[str,Any]:
    base=read_json(base_project_path,"Full-body base project"); plan=read_json(director_plan_path,"Master Director plan")
    try: require_valid_director_plan(plan)
    except Exception as exc: raise DirectorVideoProjectError("Director plan failed its v3 contract: "+str(exc)) from exc
    if plan.get("render_mode")!="procedural_2d": raise DirectorVideoProjectError("Only procedural_2d Director plans are supported.")
    character,base_action,audio_duration=validate_base(base)
    storyboard=plan["storyboard"]; plan_duration=float(storyboard["duration_seconds"])
    if abs(plan_duration-audio_duration)>.08:
        raise DirectorVideoProjectError(f"Storyboard duration {plan_duration:.3f}s must match decoded audio ({audio_duration:.3f}s); timeline stretching is disabled.")
    sync=base_action["music_sync"]; cues=align_cues(plan,sync,audio_duration); shots=storyboard["shots"]
    if not 8<=len(shots)<=18: raise DirectorVideoProjectError("Production storyboard must contain 8–18 shots.")
    project=copy.deepcopy(base); project["duration_seconds"]=audio_duration
    project["director_palette"]=copy.deepcopy(plan["visual_concept"]["palette"])
    character_id=character["id"]; scenes=[]
    for index,shot in enumerate(shots):
        shot_id=str(shot.get("id") or "").strip().casefold()
        if not SAFE_ID.fullmatch(shot_id): raise DirectorVideoProjectError(f"Shot {index+1} has an invalid ID.")
        start=float(shot["start_seconds"]); end=float(shot["end_seconds"]); duration=end-start
        if not .8<=duration<=8: raise DirectorVideoProjectError(f"{shot_id} duration is outside .8–8 seconds.")
        camera=shot["camera"]; procedural=shot["procedural_scene"]
        environment=str(procedural["environment"]).casefold()
        objects=copy.deepcopy(procedural["objects"])
        if environment not in ENVIRONMENTS: raise DirectorVideoProjectError(f"{shot_id} has an unsupported stagecraft environment.")
        if not 2<=len(objects)<=8: raise DirectorVideoProjectError(f"{shot_id} needs 2–8 animated stagecraft objects.")
        scene_cues=[{key:cue[key] for key in ("time_seconds","event","reason")}
                    for cue in cues if start-1e-5<=cue["time_seconds"]<end-1e-5]
        transition="cut" if index==0 else str(shots[index-1]["transition_to_next"])
        action=copy.deepcopy(base_action)
        action.update({
          "visible":True,"appear_immediately":True,"gesture":"violin_performance",
          "instrument_performance":True,"expression":"focused","head_angle":"front","head_expression":"focused",
          "loop":True,"cycle_duration_seconds":2.4,"start_offset":0.0,
          "music_sync":slice_sync(sync,start,end),
        })
        for field in ("x","y","scale","root_motion"):
            if field in base_action: action[field]=copy.deepcopy(base_action[field])
        scene={
          "id":"director-"+shot_id,"start":start,"duration":duration,
          "visual_mode":"full_body_performance","background_color":plan["visual_concept"]["palette"]["dominant"],
          "graphic_label":str(plan["visual_concept"].get("concept_name") or "VIOLIN PRINCE").upper(),
          "title":"","caption":"",
          "director_camera":{"movement":str(camera["movement"]),"shot_size":str(camera["shot_size"]),
                             "direction":str(camera.get("direction") or camera.get("angle") or "").casefold(),
                             "focus":str(camera.get("focus") or "")},
          "camera_motion_duration":duration,"camera_easing":"ease-in-out",
          "transition_in":transition if transition!="none" else "cut",
          "transition_in_duration":.22 if transition not in {"none","cut","match_cut"} else .08,
          "editorial_index":index,
          "stagecraft":{"environment":environment,"objects":objects,"music_sync_cues":scene_cues},
          "character_actions":{character_id:action},
          "narration_cue":str(shot.get("narration_cue") or ""),
          "music_cue":str(shot.get("music_cue") or ""),
          "transition_to_next":str(shot.get("transition_to_next") or "none"),
        }
        if shot.get("graphic_data") is not None: scene["graphic_data"]=copy.deepcopy(shot["graphic_data"])
        scenes.append(scene)
    project["scenes"]=scenes
    project["render_mode"]="preview_only"
    project["publishing"]={"enabled":False,"preview_only":True,"schedule_enabled":False}
    diagnostics=dict(project.get("diagnostics") or {})
    audio_source=str(sync.get("source") or "")
    diagnostics.update({
      "publishing":"disabled","preview_only":True,"renderer":"master_director_video",
      "director_contract_version":"violin-prince-master-director-v3","director_shot_count":len(scenes),
      "static_image_fallback_allowed":False,"generated_scene_image_count":0,
      "source_audio_duration_seconds":audio_duration,"source_audio_timing_source":audio_source,
      "measured_audio_sync_verified":len(cues)>=2 and all(c["alignment_error_seconds"]<=.38 for c in cues),
      "music_sync_cue_count":len(cues),"music_sync_cues":cues,
      "test_only_audio":audio_source.startswith("sampled_violin_cc0"),
    })
    project["diagnostics"]=diagnostics
    destination=Path(output_path); destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_suffix(destination.suffix+".tmp")
    temporary.write_text(json.dumps(project,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    temporary.replace(destination)
    summary={"status":"full_body_director_project_created","rendered":False,"published":False,
             "production_approved":False,"shot_count":len(scenes),"duration_seconds":audio_duration,
             "presenter":character_id,"render_mode":"procedural_2d","music_sync_cue_count":len(cues),
             "measured_audio_sync_verified":diagnostics["measured_audio_sync_verified"],
             "test_only_audio":diagnostics["test_only_audio"],"output":str(destination)}
    print("MASTER_DIRECTOR_VIDEO_PROJECT="+json.dumps(summary,ensure_ascii=False),flush=True)
    return summary

def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-project",required=True); parser.add_argument("--director-plan",required=True); parser.add_argument("--output",required=True)
    args=parser.parse_args()
    try: create_master_director_video_project(args.base_project,args.director_plan,args.output); return 0
    except Exception as exc:
        print("Master Director video assembly stopped safely: "+str(exc)[:1400],file=sys.stderr,flush=True); return 1

if __name__=="__main__": raise SystemExit(main())
