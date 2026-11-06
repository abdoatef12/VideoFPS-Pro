#!/usr/bin/env python3
"""
VideoFPS Pro - ملف واحد كامل (سيرفر + واجهة).
تحويل الفيديوهات لـ 60 / 90 / 120 fps باستخدام FFmpeg minterpolate.

التشغيل:
    pip install Flask
    python VideoFPS_Pro.py
ثم افتح: http://127.0.0.1:5000

المتطلب: ffmpeg و ffprobe في PATH.
"""
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

try:
    from flask import Flask, Response, abort, jsonify, render_template_string, request, send_file
except ImportError:
    sys.exit("Flask مش متثبت. شغّل: pip install Flask")

__version__ = "1.0.0"
HOST = "127.0.0.1"   # غيّرها لـ 0.0.0.0 لو عايز تفتحه من جهاز تاني على نفس الشبكة
PORT = 5000

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
ALLOWED_FPS = (30, 60, 90, 120, 144)
PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB

jobs: dict = {}
jobs_lock = threading.Lock()


# ---------------------------------------------------------------- helpers

def safe_stem(name: str) -> str:
    stem = re.sub(r"[^\w\-]+", "_", Path(name).stem, flags=re.UNICODE).strip("_")
    return stem or "video"


def get_duration(path: Path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(r.stdout.strip())
    except (ValueError, subprocess.SubprocessError):
        return None


def update_job(job_id: str, **fields) -> None:
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(fields)


def is_cancelled(job_id: str) -> bool:
    with jobs_lock:
        return jobs.get(job_id, {}).get("status") == "cancelled"


# ---------------------------------------------------------------- worker

def run_conversion(job_id: str) -> None:
    with jobs_lock:
        job = dict(jobs[job_id])

    src, dst = Path(job["src"]), Path(job["dst"])
    duration = get_duration(src)
    update_job(job_id, status="running", duration=duration)

    vf = f"minterpolate=fps={job['fps']}:mi_mode=mci:mc_mode=aobmc:vsbmc=1"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src),
        "-vf", vf,
        "-c:v", "libx264", "-preset", job["preset"], "-crf", str(job["crf"]),
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(dst),
    ]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        update_job(job_id, proc=proc)

        for line in proc.stdout:
            if is_cancelled(job_id):
                proc.terminate()
                break
            if line.startswith("out_time_us=") and duration:
                try:
                    done = int(line.split("=", 1)[1]) / 1_000_000
                    update_job(job_id, progress=min(done / duration * 100, 99.9))
                except ValueError:
                    pass  # أحياناً القيمة N/A

        stderr = proc.stderr.read()
        code = proc.wait()

        if is_cancelled(job_id):
            dst.unlink(missing_ok=True)
            return

        if code == 0 and dst.exists():
            update_job(job_id, status="done", progress=100.0,
                       size=dst.stat().st_size, finished_at=time.time())
        else:
            dst.unlink(missing_ok=True)
            lines = stderr.strip().splitlines()
            update_job(job_id, status="error",
                       error=lines[-1] if lines else "ffmpeg فشل لسبب غير معروف")
    except FileNotFoundError:
        update_job(job_id, status="error", error="ffmpeg مش متثبت أو مش في PATH")
    finally:
        src.unlink(missing_ok=True)  # نمسح الأصل بعد المعالجة


# ---------------------------------------------------------------- routes

@app.route("/")
def index():
    return render_template_string(HTML, version=__version__)


@app.route("/api/convert", methods=["POST"])
def api_convert():
    files = request.files.getlist("files")
    if not files:
        return jsonify(error="مفيش ملفات مرفوعة"), 400

    try:
        fps = int(request.form.get("fps", 90))
        crf = int(request.form.get("crf", 23))
    except ValueError:
        return jsonify(error="قيم غير صحيحة"), 400
    preset = request.form.get("preset", "medium")

    if fps not in ALLOWED_FPS:
        return jsonify(error="معدل الفريمات غير مدعوم"), 400
    if not 15 <= crf <= 35 or preset not in PRESETS:
        return jsonify(error="إعدادات الجودة غير صحيحة"), 400

    created = []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in ALLOWED_EXT:
            continue
        job_id = uuid.uuid4().hex[:12]
        src = UPLOAD_DIR / f"{job_id}{ext}"
        out_name = f"{safe_stem(f.filename)}_{fps}fps.mp4"
        dst = OUTPUT_DIR / f"{job_id}_{out_name}"
        f.save(src)

        job = {
            "id": job_id, "name": f.filename, "out_name": out_name,
            "fps": fps, "crf": crf, "preset": preset,
            "src": str(src), "dst": str(dst),
            "status": "queued", "progress": 0.0,
            "duration": None, "size": None, "error": None,
            "created_at": time.time(),
        }
        with jobs_lock:
            jobs[job_id] = job
        threading.Thread(target=run_conversion, args=(job_id,), daemon=True).start()
        created.append(job_id)

    if not created:
        return jsonify(error="الصيغة مش مدعومة"), 400
    return jsonify(ids=created), 202


def run_download_then_convert(job_id: str, url: str) -> None:
    update_job(job_id, status="downloading")

    # اسم الفيديو (لو فشل نكمّل بالاسم الافتراضي)
    try:
        t = subprocess.run(
            ["yt-dlp", "--no-playlist", "--no-warnings", "--get-title", url],
            capture_output=True, text=True, timeout=90,
        )
        title = (t.stdout or "").strip().splitlines()
        if t.returncode == 0 and title:
            with jobs_lock:
                if job_id in jobs:
                    fps = jobs[job_id]["fps"]
                    out_name = f"{safe_stem(title[0])}_{fps}fps.mp4"
                    jobs[job_id]["name"] = title[0]
                    jobs[job_id]["out_name"] = out_name
                    jobs[job_id]["dst"] = str(OUTPUT_DIR / f"{job_id}_{out_name}")
    except (FileNotFoundError, subprocess.SubprocessError):
        pass

    out_tpl = str(UPLOAD_DIR / f"{job_id}.%(ext)s")
    cmd = [
        "yt-dlp", "--no-playlist", "--no-warnings",
        "-f", "bv*+ba/b", "--merge-output-format", "mp4",
        "-o", out_tpl, url,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except FileNotFoundError:
        update_job(job_id, status="error", error="yt-dlp مش متثبت. شغّل: pip install -U yt-dlp")
        return
    except subprocess.TimeoutExpired:
        update_job(job_id, status="error", error="التحميل أخد وقت أطول من المسموح")
        return

    files = [p for p in UPLOAD_DIR.glob(f"{job_id}.*")
             if p.suffix not in (".part", ".ytdl") and p.is_file()]
    if r.returncode != 0 or not files:
        lines = (r.stderr or "").strip().splitlines()
        update_job(job_id, status="error",
                   error=lines[-1] if lines else "فشل تحميل الفيديو من الرابط ده")
        return

    src = max(files, key=lambda p: p.stat().st_size)
    with jobs_lock:
        if job_id not in jobs:
            src.unlink(missing_ok=True)
            return
        jobs[job_id]["src"] = str(src)
    run_conversion(job_id)


@app.route("/api/from-url", methods=["POST"])
def api_from_url():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "")).strip()
    if not re.match(r"^https?://\S+$", url):
        return jsonify(error="الرابط لازم يبدأ بـ http:// أو https://"), 400
    try:
        fps = int(data.get("fps", 90))
        crf = int(data.get("crf", 23))
    except (TypeError, ValueError):
        return jsonify(error="قيم غير صحيحة"), 400
    preset = str(data.get("preset", "medium"))
    if fps not in ALLOWED_FPS:
        return jsonify(error="معدل الفريمات غير مدعوم"), 400
    if not 15 <= crf <= 35 or preset not in PRESETS:
        return jsonify(error="إعدادات الجودة غير صحيحة"), 400

    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id, "name": url, "out_name": f"video_{fps}fps.mp4",
        "fps": fps, "crf": crf, "preset": preset,
        "src": str(UPLOAD_DIR / f"{job_id}.mp4"),
        "dst": str(OUTPUT_DIR / f"{job_id}_video_{fps}fps.mp4"),
        "status": "queued", "progress": 0.0,
        "duration": None, "size": None, "error": None,
        "created_at": time.time(),
    }
    with jobs_lock:
        jobs[job_id] = job
    threading.Thread(target=run_download_then_convert, args=(job_id, url), daemon=True).start()
    return jsonify(ids=[job_id]), 202


@app.route("/api/jobs")
def api_jobs():
    with jobs_lock:
        items = [{k: v for k, v in j.items() if k not in ("proc", "src", "dst")}
                 for j in jobs.values()]
    items.sort(key=lambda j: j["created_at"], reverse=True)
    return jsonify(items)


@app.route("/api/jobs/<job_id>", methods=["DELETE"])
def api_delete(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            abort(404)
        if job["status"] == "running":
            job["status"] = "cancelled"
            proc = job.get("proc")
            if proc:
                proc.terminate()
        jobs.pop(job_id, None)
    Path(job["dst"]).unlink(missing_ok=True)
    Path(job["src"]).unlink(missing_ok=True)
    return jsonify(ok=True)


@app.route("/download/<job_id>")
def download(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job or job["status"] != "done":
        abort(404)
    return send_file(job["dst"], as_attachment=True, download_name=job["out_name"])


@app.route("/api/health")
def health():
    return jsonify(ffmpeg=shutil.which("ffmpeg") is not None,
                   ffprobe=shutil.which("ffprobe") is not None)


# ---------------------------------------------------------------- UI

HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#7c5cff">
<link rel="icon" href="/icon.svg">
<link rel="manifest" href="/manifest.json">
<title>VideoFPS Pro</title>
<style>
  :root {
    --bg: #0b0d14; --card: rgba(255,255,255,0.04); --border: rgba(255,255,255,0.08);
    --text: #eef0f6; --muted: #8b90a3; --accent: #7c5cff; --accent2: #22d3ee;
    --ok: #34d399; --err: #f87171; --input: #141726;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh;
    font-family: "Segoe UI", Tahoma, "Noto Sans Arabic", sans-serif;
    background:
      radial-gradient(1000px 500px at 90% -10%, rgba(124,92,255,.25), transparent),
      radial-gradient(800px 500px at -10% 110%, rgba(34,211,238,.18), transparent),
      var(--bg);
    color: var(--text);
  }
  .wrap { max-width: 880px; margin: 0 auto; padding: 32px 18px 60px; }
  header { display: flex; align-items: center; gap: 14px; margin-bottom: 28px; flex-wrap: wrap; }
  .logo {
    width: 48px; height: 48px; border-radius: 14px; display: grid; place-items: center;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    font-weight: 800; font-size: 13px; color: #fff; box-shadow: 0 8px 30px rgba(124,92,255,.35);
  }
  h1 { font-size: 22px; margin: 0; }
  .sub { color: var(--muted); font-size: 13px; margin-top: 3px; }
  .pill {
    margin-inline-start: auto; font-size: 12px; padding: 6px 12px; border-radius: 999px;
    background: var(--card); border: 1px solid var(--border); color: var(--muted);
  }
  .pill.ok::before { content: "● "; color: var(--ok); }
  .pill.bad::before { content: "● "; color: var(--err); }
  .card {
    background: var(--card); border: 1px solid var(--border); border-radius: 20px;
    padding: 22px; margin-bottom: 18px; backdrop-filter: blur(10px);
  }
  .drop {
    border: 2px dashed rgba(124,92,255,.45); border-radius: 18px; padding: 42px 20px;
    text-align: center; cursor: pointer; transition: .2s; background: rgba(124,92,255,.04);
  }
  .drop:hover, .drop.over { border-color: var(--accent2); background: rgba(34,211,238,.06); }
  .drop .icon { font-size: 40px; margin-bottom: 8px; }
  .drop b { font-size: 16px; }
  .drop small { display: block; color: var(--muted); margin-top: 6px; }
  #fileInput { display: none; }
  .picked { margin-top: 12px; font-size: 13px; color: var(--muted); min-height: 18px; word-break: break-all; }
  .settings { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-top: 18px; }
  @media (max-width: 640px) { .settings { grid-template-columns: 1fr; } }
  label { font-size: 12px; color: var(--muted); display: block; margin-bottom: 6px; }
  select {
    width: 100%; padding: 11px 12px; border-radius: 12px; font-size: 14px; font-family: inherit;
    background: var(--input); color: var(--text); border: 1px solid var(--border);
  }
  input[type=range] { width: 100%; }
  .seg { display: flex; gap: 8px; }
  .seg button {
    flex: 1; padding: 11px 0; border-radius: 12px; cursor: pointer; font-family: inherit; font-size: 14px;
    background: var(--input); border: 1px solid var(--border); color: var(--muted); transition: .15s;
  }
  .seg button.active {
    color: #fff; border-color: transparent; background: linear-gradient(135deg, var(--accent), var(--accent2));
    box-shadow: 0 6px 20px rgba(124,92,255,.3);
  }
  .actions { display: flex; align-items: center; gap: 12px; margin-top: 20px; flex-wrap: wrap; }
  .btn {
    padding: 13px 26px; border-radius: 14px; border: none; cursor: pointer; font-family: inherit;
    font-size: 15px; font-weight: 700; color: #fff;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    box-shadow: 0 10px 30px rgba(124,92,255,.35); transition: transform .1s, opacity .2s;
  }
  .btn:hover { transform: translateY(-1px); }
  .btn:disabled { opacity: .5; cursor: not-allowed; transform: none; }
  .hint { color: var(--muted); font-size: 12px; }
  .section-title { display: flex; align-items: center; justify-content: space-between; margin: 8px 4px 12px; }
  .section-title h2 { font-size: 16px; margin: 0; }
  .link-btn { background: none; border: none; color: var(--muted); cursor: pointer; font-family: inherit; font-size: 13px; }
  .link-btn:hover { color: var(--text); }
  .job { padding: 16px 18px; }
  .job-top { display: flex; align-items: center; gap: 12px; }
  .job-name { font-weight: 600; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
  .badge { font-size: 11px; padding: 4px 10px; border-radius: 999px; white-space: nowrap; background: rgba(255,255,255,.07); color: var(--muted); }
  .badge.running { color: var(--accent2); background: rgba(34,211,238,.1); }
  .badge.done { color: var(--ok); background: rgba(52,211,153,.1); }
  .badge.error { color: var(--err); background: rgba(248,113,113,.1); }
  .bar { height: 8px; border-radius: 99px; background: rgba(255,255,255,.07); overflow: hidden; margin: 12px 0 8px; }
  .bar > div { height: 100%; width: 0%; border-radius: 99px; background: linear-gradient(90deg, var(--accent), var(--accent2)); transition: width .4s ease; }
  .job-meta { font-size: 12px; color: var(--muted); }
  .job-actions { display: flex; gap: 8px; margin-top: 12px; }
  .small-btn {
    padding: 8px 14px; border-radius: 10px; font-size: 13px; cursor: pointer; font-family: inherit;
    border: 1px solid var(--border); background: var(--input); color: var(--text); text-decoration: none;
  }
  .small-btn.primary { background: var(--ok); color: #05130d; border-color: transparent; font-weight: 700; }
  .small-btn.danger:hover { color: var(--err); border-color: rgba(248,113,113,.4); }
  .error-text { color: var(--err); font-size: 12px; margin-top: 8px; word-break: break-all; }
  .empty { text-align: center; color: var(--muted); padding: 26px; font-size: 14px; }
  .urlrow { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
  input.url {
    flex: 1; min-width: 200px; padding: 13px 14px; border-radius: 12px; font-size: 14px;
    font-family: inherit; background: var(--input); color: var(--text); border: 1px solid var(--border);
  }
  input.url:focus { outline: none; border-color: var(--accent2); }
  .toast {
    position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%) translateY(120px);
    background: #1a1e30; border: 1px solid var(--border); padding: 12px 18px; border-radius: 14px;
    font-size: 14px; transition: transform .3s; box-shadow: 0 10px 40px rgba(0,0,0,.4); z-index: 10;
  }
  .toast.show { transform: translateX(-50%) translateY(0); }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">FPS</div>
    <div>
      <h1>VideoFPS Pro</h1>
      <div class="sub">حوّل فيديوهاتك لـ 90fps بسلاسة · v{{ version }}</div>
    </div>
    <div id="ffStatus" class="pill">جاري الفحص...</div>
  </header>

  <section class="card">
    <label>أو حمّل فيديو من رابط</label>
    <div class="urlrow">
      <input type="url" id="urlInput" class="url" placeholder="https://..." dir="ltr">
      <button id="urlBtn" class="btn">تحميل وتحويل</button>
    </div>
    <div class="hint">بيستخدم الإعدادات اللي فوق (FPS والجودة والسرعة)</div>
  </section>

  <section class="card">
    <div id="drop" class="drop">
      <div class="icon">🎬</div>
      <b>اسحب الفيديوهات هنا أو اضغط للاختيار</b>
      <small>MP4 · MOV · MKV · WEBM · AVI · M4V</small>
      <input type="file" id="fileInput" multiple accept="video/*,.mp4,.mov,.mkv,.webm,.avi,.m4v">
    </div>
    <div id="picked" class="picked"></div>

    <div class="settings">
      <div>
        <label>معدل الفريمات</label>
        <div class="seg" id="fpsSeg">
          <button data-v="60">60</button>
          <button data-v="90" class="active">90</button>
          <button data-v="120">120</button>
        </div>
      </div>
      <div>
        <label>سرعة المعالجة</label>
        <select id="preset">
          <option value="ultrafast">سريع جداً (أقل جودة)</option>
          <option value="veryfast">سريع</option>
          <option value="medium" selected>متوسط (موصى به)</option>
          <option value="slow">بطيء (أفضل جودة)</option>
        </select>
      </div>
      <div>
        <label>جودة الفيديو (CRF: <span id="crfVal">23</span>)</label>
        <input type="range" id="crf" min="18" max="30" value="23">
        <div class="hint">أقل = جودة أعلى وحجم أكبر</div>
      </div>
    </div>

    <div class="actions">
      <button id="startBtn" class="btn" disabled>ابدأ التحويل</button>
      <span class="hint" id="hint">اختار فيديو الأول</span>
    </div>
  </section>

  <div class="section-title">
    <h2>المهام</h2>
    <button class="link-btn" id="clearDone">امسح المكتملة</button>
  </div>
  <div id="jobs"></div>
</div>
<div id="toast" class="toast"></div>

<script>
const $ = (s) => document.querySelector(s);
const drop = $("#drop"), fileInput = $("#fileInput"), startBtn = $("#startBtn");
let files = [];
let fps = 90;

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2600);
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function fmtSize(b) {
  if (!b) return "";
  const u = ["B", "KB", "MB", "GB"]; let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return b.toFixed(1) + " " + u[i];
}
function setFiles(list) {
  files = [...list];
  $("#picked").textContent = files.length
    ? `تم اختيار ${files.length} ملف: ` + files.map(f => f.name).join("، ") : "";
  updateStart();
}
function updateStart() {
  startBtn.disabled = files.length === 0;
  $("#hint").textContent = files.length ? `هيتحول لـ ${fps}fps` : "اختار فيديو الأول";
}

drop.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", e => setFiles(e.target.files));
["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", e => setFiles(e.dataTransfer.files));

document.querySelectorAll("#fpsSeg button").forEach(b => b.addEventListener("click", () => {
  document.querySelectorAll("#fpsSeg button").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  fps = +b.dataset.v;
  updateStart();
}));
$("#crf").addEventListener("input", e => $("#crfVal").textContent = e.target.value);

startBtn.addEventListener("click", async () => {
  if (!files.length) return;
  startBtn.disabled = true;
  const fd = new FormData();
  files.forEach(f => fd.append("files", f));
  fd.append("fps", fps);
  fd.append("preset", $("#preset").value);
  fd.append("crf", $("#crf").value);
  try {
    const r = await fetch("/api/convert", { method: "POST", body: fd });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "فشل الرفع");
    toast(`بدأ تحويل ${data.ids.length} فيديو ✔`);
    files = []; fileInput.value = ""; $("#picked").textContent = "";
    loadJobs();
  } catch (err) {
    toast("⚠ " + err.message);
  } finally {
    updateStart();
  }
});

function jobCard(j) {
  const statusText = { queued: "في الانتظار", downloading: "جاري التحميل", running: "جاري التحويل", done: "مكتمل", error: "فشل", cancelled: "اتلغى" }[j.status] || j.status;
  const pct = j.status === "done" ? 100 : Math.round(j.progress || 0);
  const meta = [`${j.fps}fps`, `CRF ${j.crf}`, j.size ? fmtSize(j.size) : null,
                j.status === "running" ? `${pct}%` : null].filter(Boolean).join(" · ");
  const actions = [];
  if (j.status === "done") actions.push(`<a class="small-btn primary" href="/download/${j.id}">تحميل</a>`);
  actions.push(`<button class="small-btn danger" data-del="${j.id}">${j.status === "running" ? "إلغاء" : "حذف"}</button>`);
  return `
    <div class="card job">
      <div class="job-top">
        <div class="job-name" title="${esc(j.name)}">${esc(j.name)}</div>
        <span class="badge ${j.status}">${statusText}</span>
      </div>
      <div class="bar"><div style="width:${pct}%"></div></div>
      <div class="job-meta">${esc(meta)}</div>
      ${j.error ? `<div class="error-text">${esc(j.error)}</div>` : ""}
      <div class="job-actions">${actions.join("")}</div>
    </div>`;
}

async function startFromUrl() {
  const url = $("#urlInput").value.trim();
  if (!url) return toast("اكتب الرابط الأول");
  const btn = $("#urlBtn");
  btn.disabled = true;
  try {
    const r = await fetch("/api/from-url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, fps, crf: $("#crf").value, preset: $("#preset").value }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "فشل");
    toast("بدأ التحميل والتحويل ✔");
    $("#urlInput").value = "";
    loadJobs();
  } catch (err) {
    toast("⚠ " + err.message);
  } finally {
    btn.disabled = false;
  }
}
$("#urlBtn").addEventListener("click", startFromUrl);

async function loadJobs() {
  const jobs = await (await fetch("/api/jobs")).json();
  const box = $("#jobs");
  box.innerHTML = jobs.length
    ? jobs.map(jobCard).join("")
    : `<div class="card empty">مفيش مهام لسه، ارفع فيديو وابدأ</div>`;
}

$("#jobs").addEventListener("click", async (e) => {
  const id = e.target.dataset.del;
  if (!id) return;
  await fetch(`/api/jobs/${id}`, { method: "DELETE" });
  loadJobs();
});

$("#clearDone").addEventListener("click", async () => {
  const jobs = await (await fetch("/api/jobs")).json();
  await Promise.all(jobs
    .filter(j => ["done", "error", "cancelled"].includes(j.status))
    .map(j => fetch(`/api/jobs/${j.id}`, { method: "DELETE" })));
  loadJobs();
});

async function checkHealth() {
  try {
    const h = await (await fetch("/api/health")).json();
    const pill = $("#ffStatus");
    if (h.ffmpeg && h.ffprobe) { pill.textContent = "FFmpeg جاهز"; pill.classList.add("ok"); }
    else { pill.textContent = "FFmpeg مش متثبت"; pill.classList.add("bad"); }
  } catch { $("#ffStatus").textContent = "السيرفر مش شغال"; }
}

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
checkHealth();
loadJobs();
setInterval(loadJobs, 1200);
</script>
</body>
</html>
"""


MANIFEST = {
    "name": "VideoFPS Pro",
    "short_name": "VideoFPS",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#0b0d14",
    "theme_color": "#7c5cff",
    "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"}, {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}],
}

ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#7c5cff"/><stop offset="1" stop-color="#22d3ee"/>'
    '</linearGradient></defs>'
    '<rect width="512" height="512" rx="110" fill="url(#g)"/>'
    '<text x="256" y="300" font-size="150" font-family="Arial" font-weight="bold" '
    'fill="#fff" text-anchor="middle">FPS</text></svg>'
)

SW_JS = (
    "self.addEventListener('install', e => self.skipWaiting());\n"
    "self.addEventListener('activate', e => self.clients.claim());\n"
    "self.addEventListener('fetch', e => e.respondWith(fetch(e.request)));\n"
)


@app.route("/manifest.json")
def manifest():
    return jsonify(MANIFEST)


@app.route("/icon.svg")
def icon():
    return Response(ICON_SVG, mimetype="image/svg+xml")


@app.route("/sw.js")
def service_worker():
    return Response(SW_JS, mimetype="application/javascript")


import struct
import zlib


def make_png(size: int) -> bytes:
    """أيقونة PNG بتدرج ألوان التطبيق (من غير مكتبات خارجية)."""
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter type
        for x in range(size):
            t = (x + y) / (2 * size)
            raw += bytes((int(124 + (34 - 124) * t),
                          int(92 + (211 - 92) * t),
                          int(255 + (238 - 255) * t), 255))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


ICON_192 = make_png(192)
ICON_512 = make_png(512)


@app.route("/icon-192.png")
def icon_192():
    return Response(ICON_192, mimetype="image/png")


@app.route("/icon-512.png")
def icon_512():
    return Response(ICON_512, mimetype="image/png")


if __name__ == "__main__":
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        print("[تحذير] ffmpeg أو ffprobe مش موجودين في PATH، ثبّتهم الأول.")
    print(f"VideoFPS Pro شغال على http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
