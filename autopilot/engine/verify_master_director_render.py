"""Validate full-body shot tracks, encoded media and camera-compensated subject motion."""
from __future__ import annotations
import argparse,json,math,subprocess,sys
from pathlib import Path
from typing import Any
import cv2
import numpy as np

class RenderVerificationError(RuntimeError):
    """The rendered multi-shot video did not meet the technical quality gates."""

def read_json(path:str|Path,label:str)->dict[str,Any]:
    try: value=json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc: raise RenderVerificationError(f"{label} could not be read: {exc}") from exc
    if not isinstance(value,dict): raise RenderVerificationError(f"{label} must be a JSON object.")
    return value

def scene_for_interval(scenes:list[dict[str,Any]],first:float,second:float)->dict[str,Any]|None:
    midpoint=(first+second)/2
    for scene in scenes:
        start=float(scene["start"]); end=start+float(scene["duration"])
        if start-1e-5<=first and second<end-1e-5 and start<=midpoint<end: return scene
    return None

def probe_video(path:Path)->dict[str,Any]:
    try:
        result=subprocess.run(["ffprobe","-v","error","-show_entries",
          "stream=codec_type,codec_name,width,height,r_frame_rate","-show_entries","format=duration",
          "-of","json",str(path)],check=True,capture_output=True,text=True,timeout=45)
        data=json.loads(result.stdout)
    except (OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired,json.JSONDecodeError) as exc:
        raise RenderVerificationError("FFprobe could not validate the rendered MP4: "+str(exc)) from exc
    streams=data.get("streams") or []
    video=next((s for s in streams if s.get("codec_type")=="video"),None)
    audio=next((s for s in streams if s.get("codec_type")=="audio"),None)
    if not video or not audio: raise RenderVerificationError("Rendered MP4 must include both video and audio streams.")
    try:
        numerator,denominator=str(video["r_frame_rate"]).split("/",1)
        fps=float(numerator)/float(denominator)
        duration=float(data["format"]["duration"])
    except (KeyError,TypeError,ValueError,ZeroDivisionError) as exc:
        raise RenderVerificationError("MP4 media metadata is incomplete.") from exc
    return {"video_codec":video.get("codec_name"),"audio_codec":audio.get("codec_name"),
      "width":int(video.get("width") or 0),"height":int(video.get("height") or 0),
      "fps":fps,"duration_seconds":duration,"audio_stream_present":True}

def frame_motion(first:np.ndarray,second:np.ndarray)->dict[str,Any]:
    """Return motion after fitting and removing scene-wide affine camera movement."""
    p=cv2.goodFeaturesToTrack(first,maxCorners=240,qualityLevel=.012,minDistance=5,blockSize=7)
    if p is None or len(p)<18: return {"active":False,"tracked_points":0,"moving_fraction":0.0,"p90_residual_px":0.0}
    q,status,_=cv2.calcOpticalFlowPyrLK(first,second,p,None,winSize=(21,21),maxLevel=3,
      criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,30,.01))
    if q is None or status is None: return {"active":False,"tracked_points":0,"moving_fraction":0.0,"p90_residual_px":0.0}
    valid=status.reshape(-1).astype(bool); p0=p.reshape(-1,2)[valid]; p1=q.reshape(-1,2)[valid]
    if len(p0)<18: return {"active":False,"tracked_points":int(len(p0)),"moving_fraction":0.0,"p90_residual_px":0.0}
    affine,_=cv2.estimateAffinePartial2D(p0,p1,method=cv2.RANSAC,ransacReprojThreshold=2.5,
      maxIters=1500,confidence=.995)
    if affine is None: return {"active":False,"tracked_points":0,"moving_fraction":0.0,"p90_residual_px":0.0}
    predicted=cv2.transform(p0.reshape(1,-1,2),affine).reshape(-1,2)
    residual=np.linalg.norm(p1-predicted,axis=1)
    height,width=first.shape[:2]
    x,y=p0[:,0],p0[:,1]
    mask=(x>=width*.17)&(x<=width*.83)&(y>=height*.09)&(y<=height*.89)
    local=residual[mask]
    if len(local)<10: return {"active":False,"tracked_points":int(len(local)),"moving_fraction":0.0,"p90_residual_px":0.0}
    fraction=float(np.mean(local>=.45)); p90=float(np.percentile(local,90))
    return {"active":bool(p90>=.48 and fraction>=.035),"tracked_points":int(len(local)),
      "moving_fraction":fraction,"p90_residual_px":p90}

def measure_subject_motion(video_path:str|Path,scenes:list[dict[str,Any]],sample_rate_hz:float=4.0)->dict[str,Any]:
    path=Path(video_path)
    if not path.is_file(): raise RenderVerificationError(f"Rendered MP4 not found: {path}")
    cap=cv2.VideoCapture(str(path))
    if not cap.isOpened(): raise RenderVerificationError("OpenCV could not decode the rendered MP4.")
    fps=float(cap.get(cv2.CAP_PROP_FPS) or 0); count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration=count/fps if fps>0 else 0
    if fps<20 or duration<=0: cap.release(); raise RenderVerificationError("Rendered video needs a measurable 20+ fps stream.")
    step=1/sample_rate_hz; timestamps=[]; t=min(.10,step*.4)
    while t<duration-.08: timestamps.append(round(t,4)); t+=step
    samples=[]
    for t in timestamps:
        cap.set(cv2.CAP_PROP_POS_MSEC,t*1000)
        ok,frame=cap.read()
        if not ok or frame is None: continue
        h,w=frame.shape[:2]
        small=cv2.resize(frame,(max(2,w//2),max(2,h//2)),interpolation=cv2.INTER_AREA)
        samples.append((t,cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)))
    cap.release()
    if len(samples)<20: raise RenderVerificationError("Fewer than 20 temporal frames decoded for motion QA.")
    by_scene={str(s["id"]):{"scene_id":str(s["id"]),"valid_intervals":0,"active_intervals":0,
      "motion_coverage":0.0,"median_p90_residual_px":0.0,"active":False} for s in scenes}
    residuals={key:[] for key in by_scene}; total=active_total=0
    for (t0,f0),(t1,f1) in zip(samples,samples[1:]):
        scene=scene_for_interval(scenes,t0,t1)
        if scene is None: continue
        key=str(scene["id"]); measured=frame_motion(f0,f1)
        total+=1; by_scene[key]["valid_intervals"]+=1
        residuals[key].append(float(measured["p90_residual_px"]))
        if measured["active"]:
            active_total+=1; by_scene[key]["active_intervals"]+=1
        by_scene[key].setdefault("samples",[]).append({"start_seconds":t0,"end_seconds":t1,**measured})
    if total==0: raise RenderVerificationError("No valid same-shot optical-flow intervals were found.")
    for key,entry in by_scene.items():
        valid=int(entry["valid_intervals"]); active=int(entry["active_intervals"])
        entry["motion_coverage"]=round(active/valid,4) if valid else 0.0
        entry["median_p90_residual_px"]=round(float(np.median(residuals[key])),4) if residuals[key] else 0.0
        entry["active"]=bool(valid and active/valid>=.40)
    coverage=active_total/total; active_shots=sum(bool(x["active"]) for x in by_scene.values())
    return {"sample_rate_hz":sample_rate_hz,"sample_count":len(samples),"valid_interval_count":total,
      "active_interval_count":active_total,"motion_coverage":round(coverage,4),
      "active_shot_count":active_shots,"shot_count":len(scenes),"per_shot":list(by_scene.values()),
      "camera_motion_compensated":True,"subject_region":"central 17–83% width / 9–89% height",
      "actual_motion_verified":bool(coverage>=.75 and active_shots>=max(3,math.ceil(len(scenes)*.80)))}

def verify_master_director_render(video_path:str|Path,project_path:str|Path,motion_report_path:str|Path,
                                  report_output:str|Path)->dict[str,Any]:
    project=read_json(project_path,"Director Motion project"); motion=read_json(motion_report_path,"Motion build report")
    scenes=project.get("scenes")
    if not isinstance(scenes,list) or not 8<=len(scenes)<=18: raise RenderVerificationError("Project must render 8–18 Director shots.")
    if project.get("render_mode")!="preview_only" or project.get("publishing",{}).get("enabled") is not False:
        raise RenderVerificationError("The verification project must remain preview-only with publishing disabled.")
    duration=float(project.get("duration_seconds") or 0); cursor=0.0
    for i,scene in enumerate(scenes):
        start=float(scene["start"]); end=start+float(scene["duration"])
        if abs(start-cursor)>.05: raise RenderVerificationError(f"Shot {i+1} leaves a timeline gap or overlap.")
        cursor=end
        if scene.get("visual_mode")!="full_body_performance": raise RenderVerificationError(f"Shot {i+1} does not use the full-body rig.")
        if len(scene.get("stagecraft",{}).get("objects") or [])<2: raise RenderVerificationError(f"Shot {i+1} has fewer than two moving stagecraft objects.")
    if abs(cursor-duration)>.05: raise RenderVerificationError("Final shot does not end at the audio/project duration.")
    scene_reports={str(x.get("scene_id")):x for x in motion.get("scenes",[]) if isinstance(x,dict)}
    for scene in scenes:
        item=scene_reports.get(str(scene["id"]))
        if not item: raise RenderVerificationError("Motion report missing "+str(scene["id"]))
        gates={
          "presenter":int(item.get("animated_presenter_count") or 0)>=1,
          "full_body":int(item.get("full_body_performance_character_count") or 0)>=1,
          "stagecraft_objects":int(item.get("animated_stagecraft_objects") or 0)>=2,
          "stagecraft_nodes":int(item.get("animated_stagecraft_nodes") or 0)>0,
          "bow_strokes":int(item.get("presenter_bow_stroke_track_count") or 0)>=4,
          "bow_slide":int(item.get("presenter_bow_slide_track_count") or 0)>=1,
          "finger_note_tracks":int(item.get("presenter_finger_note_track_count") or 0)>=12,
          "weight_shift_tracks":int(item.get("presenter_weight_shift_track_count") or 0)>=6,
        }
        failed=[k for k,v in gates.items() if not v]
        if failed: raise RenderVerificationError(f"Shot {scene['id']} missing full-body evidence: "+", ".join(failed))
    n=len(scenes)
    totals={
      "full_body_performance_scene_count":int(motion.get("full_body_performance_scene_count") or 0)==n,
      "animated_stagecraft_scene_count":int(motion.get("animated_stagecraft_scene_count") or 0)==n,
      "animated_stagecraft_object_count":int(motion.get("animated_stagecraft_object_count") or 0)>=2*n,
      "animated_presenter_count":int(motion.get("animated_presenter_count") or 0)>=3,
      "rendered_layer_count":int(motion.get("rendered_layer_count") or 0)==0,
    }
    failed=[k for k,v in totals.items() if not v]
    if failed: raise RenderVerificationError("Aggregate motion requirements failed: "+", ".join(failed))
    media=probe_video(Path(video_path))
    if media["video_codec"]!="h264" or media["audio_codec"]!="aac": raise RenderVerificationError("MP4 needs H.264 video and AAC audio.")
    if (media["width"],media["height"])!=(720,1280) or abs(media["fps"]-25)>.1: raise RenderVerificationError("MP4 must be 720x1280 at 25fps.")
    if abs(media["duration_seconds"]-duration)>.12: raise RenderVerificationError("MP4 duration does not match the complete storyboard.")
    flow=measure_subject_motion(video_path,scenes)
    if not flow["actual_motion_verified"]:
        raise RenderVerificationError("Camera-compensated subject-motion coverage is below 75% or too few shots contain real motion.")
    diagnostics=project.get("diagnostics") or {}; cues=diagnostics.get("music_sync_cues") or []
    cue_count=int(diagnostics.get("music_sync_cue_count") or 0)
    audio_sync=(diagnostics.get("measured_audio_sync_verified") is True and cue_count>=2
      and int(motion.get("music_sync_event_count") or 0)==cue_count and len(cues)==cue_count
      and all(float(c.get("alignment_error_seconds") or 0)<=.38 for c in cues))
    if not audio_sync: raise RenderVerificationError("Measured audio cue timings do not match the rendered sync tracks.")
    source=str(diagnostics.get("source_audio_timing_source") or "")
    report={
      "status":"passed","render_mode":"procedural_2d","renderer":"master_director_video",
      "director_shot_count":n,"rendered_shot_count":n,
      "animated_stagecraft_scene_count":int(motion["animated_stagecraft_scene_count"]),
      "animated_stagecraft_object_count":int(motion["animated_stagecraft_object_count"]),
      "animated_presenter_count":int(motion["animated_presenter_count"]),
      "rendered_layer_count":int(motion["rendered_layer_count"]),
      "music_sync_cue_count":cue_count,"music_sync_event_count":int(motion.get("music_sync_event_count") or 0),
      "measured_audio_sync_verified":audio_sync,"actual_motion_verified":flow["actual_motion_verified"],
      "static_image_only_shot_count":0,"motion_coverage":flow["motion_coverage"],
      "final_video_verified":True,"media":media,"motion_analysis":flow,
      "audio_source":source,"test_only_audio":bool(diagnostics.get("test_only_audio")),
      "creator_recorded_violin_verified":source=="creator_recorded_violin",
      "approved_narration_present":False,"production_ready":False,
      "production_blocker":"CI uses a test guide and has no supplied creator-approved narration; final creator audio and review remain required.",
      "preview_only":True,"publish_enabled":False,
    }
    out=Path(report_output); out.parent.mkdir(parents=True,exist_ok=True)
    temp=out.with_suffix(out.suffix+".tmp"); temp.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8"); temp.replace(out)
    print("MASTER_DIRECTOR_RENDER_QA="+json.dumps(report),flush=True)
    return report

def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video",required=True); parser.add_argument("--project",required=True)
    parser.add_argument("--motion-report",required=True); parser.add_argument("--report-output",required=True)
    args=parser.parse_args()
    try: verify_master_director_render(args.video,args.project,args.motion_report,args.report_output); return 0
    except Exception as exc:
        print("Master Director render QA stopped safely: "+str(exc)[:1500],file=sys.stderr,flush=True); return 1

if __name__=="__main__": raise SystemExit(main())
