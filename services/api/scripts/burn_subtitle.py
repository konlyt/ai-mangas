"""手动把 29.json 字幕烧到最新成片上，验证字幕链路。"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.utils.ffmpeg import build_srt

root = Path(r"E:\Class Project\ai漫剧\services\api")
proj_root = Path(r"E:\Class Project\ai漫剧")
sub_json = root / "static" / "subtitles" / "29.json"
data = json.loads(sub_json.read_text(encoding="utf-8"))
srt = build_srt(data["segments"])
print("=== SRT content ===")
print(srt)

work = root / "static" / "outputs" / "29"
sub_srt = work / "manual_sub.srt"
sub_srt.write_text(srt, encoding="utf-8")

latest = sorted(work.glob("final_*.mp4"), key=lambda p: p.stat().st_mtime)[-1]
out = work / "final_with_sub.mp4"
cmd = [
    str(proj_root / "tools" / "ffmpeg.exe"), "-y",
    "-i", str(latest),
    "-vf", "subtitles=manual_sub.srt:force_style='FontSize=22,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,BorderStyle=1,Outline=2,Alignment=2,MarginV=40'",
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
    "-c:a", "copy",
    str(out),
]
print("=== running ffmpeg ===")
r = subprocess.run(cmd, cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace")
print("rc=", r.returncode)
print("stderr tail:", r.stderr[-1500:] if r.stderr else "(empty)")
print("out exists:", out.exists(), "size:", out.stat().st_size if out.exists() else 0)
