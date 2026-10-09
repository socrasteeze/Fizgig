import { useEffect, useRef, useState } from "react";
import { BrowseButton } from "./extra";

interface Sens { label: string; threshold: number }
interface GizmoForm {
  fps: number;
  grid_frames: number[];
  audio_grid_frames?: number[];
  scene_sensitivities: Sens[];
  threshold: number;
}
interface Probe {
  fps: number | null; width: number | null; height: number | null; duration: number | null;
  display_width?: number | null; display_height?: number | null;
}

async function readError(response: Response): Promise<string> {
  const body = await response.json().catch(() => ({})) as { detail?: string; problems?: string[] };
  return body.problems?.length ? body.problems.join("\n") : (body.detail || `request failed (${response.status})`);
}

async function poll(id: string): Promise<string> {
  for (;;) {
    const body = await fetch(`/api/jobs/${id}`).then((response) => response.json()) as { status?: string };
    if (body.status === "done" || body.status === "failed" || body.status === "stopped") return body.status;
    await new Promise((resolve) => window.setTimeout(resolve, 250));
  }
}

function join(folder: string, leaf: string): string {
  const sep = folder.includes("\\") ? "\\" : "/";
  return `${folder}${folder.endsWith(sep) ? "" : sep}${leaf}`;
}

export function GizmoPanel() {
  const [form, setForm] = useState<GizmoForm | null>(null);
  const [source, setSource] = useState("");
  const [dataset, setDataset] = useState("");
  const [probe, setProbe] = useState<Probe | null>(null);
  const [frames, setFrames] = useState(22);
  const [muted, setMuted] = useState(false);
  const [threshold, setThreshold] = useState(0.3);
  const [caption, setCaption] = useState("");
  const [inFrame, setInFrame] = useState(0);
  const [outFrame, setOutFrame] = useState<number | null>(null);
  const [starts, setStarts] = useState<number[]>([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [recording, setRecording] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const fps = probe?.fps || form?.fps || 24;

  useEffect(() => {
    fetch("/api/gizmo/form").then((response) => response.json()).then((body: GizmoForm) => {
      setForm(body);
      setFrames(body.grid_frames.includes(22) ? 22 : body.grid_frames[0]);
      setThreshold(body.threshold);
    }).catch(() => setError("gizmo form failed"));
  }, []);

  useEffect(() => {
    if (!source) { setProbe(null); return; }
    fetch(`/api/gizmo/probe?path=${encodeURIComponent(source)}`).then(async (response) => {
      if (!response.ok) throw new Error(await readError(response));
      return response.json() as Promise<Probe>;
    }).then((body) => { setProbe(body); setError(""); })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "probe failed"));
  }, [source]);

  function snap(which: "in" | "out") {
    const video = videoRef.current;
    if (!video) return;
    const frame = Math.round(video.currentTime * fps);
    video.currentTime = frame / fps;
    if (which === "in") setInFrame(frame); else setOutFrame(frame);
  }

  async function upload(file: File | undefined) {
    if (!file) return;
    if (!dataset) { setError("Pick a dataset folder first."); return; }
    const data = new FormData();
    data.set("dest", dataset);
    data.set("file", file);
    const response = await fetch("/api/gizmo/upload", { method: "POST", body: data });
    if (!response.ok) { setError(await readError(response)); return; }
    const body = await response.json() as { written?: string[]; folder?: string };
    if (body.written?.[0] && body.folder) {
      setSource(join(body.folder, body.written[0]));
      setStatus(`Uploaded ${body.written[0]}`);
    }
  }

  function clip(start: number): Record<string, unknown> {
    const row: Record<string, unknown> = { start, frames, muted };
    if (caption.trim()) row.caption = caption;
    return row;
  }

  async function postJob(path: string, payload: unknown): Promise<{ id: string; status: string } | null> {
    setError("");
    const response = await fetch(path, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
    });
    if (!response.ok) { setError(await readError(response)); return null; }
    const job = await response.json() as { id: string };
    return { id: job.id, status: await poll(job.id) };
  }

  async function cut(rows: Array<Record<string, unknown>>) {
    if (!source || !dataset) { setError("Pick a source and a dataset folder."); return; }
    const done = await postJob("/api/gizmo/clips", { source, dataset, clips: rows });
    if (done) setStatus(done.status === "done" ? "Cut saved." : `Cut ${done.status}.`);
  }

  async function chop() {
    if (!source || probe?.duration == null) { setError(source ? "Probe the source first." : "Pick a source."); return; }
    const done = await postJob("/api/gizmo/scan", {
      source, threshold, duration: probe.duration, span_s: frames / 24, fill: true,
    });
    if (!done) return;
    if (done.status !== "done") { setStatus(`Chop ${done.status}.`); return; }
    const text = await fetch(`/api/jobs/${done.id}/log?offset=0`).then((response) => response.json()) as { text?: string };
    const line = (text.text || "").split(/\r?\n/).find((item) => item.startsWith("STARTS:"));
    const found = line ? line.slice("STARTS:".length).trim().split(/\s+/).filter(Boolean).map(Number) : [];
    setStarts(found);
    setStatus(found.length ? `${found.length} starts.` : "No starts.");
  }

  async function transcribe() {
    if (!source || !dataset) { setError("Pick a source and a dataset folder."); return; }
    const span = outFrame != null && outFrame > inFrame ? (outFrame - inFrame) / fps : frames / fps;
    const stem = (source.split(/[/\\]/).pop() || "clip").replace(/\.[^.]+$/, "");
    const done = await postJob("/api/gizmo/transcribe", {
      source, start: inFrame / fps, span, language: "Auto detect", output: join(dataset, `${stem}_whisper.txt`),
    });
    if (!done) return;
    if (done.status !== "done") { setStatus(`Transcribe ${done.status}.`); return; }
    const chunk = await fetch(`/api/jobs/${done.id}/log?offset=0`).then((response) => response.json()) as { text?: string };
    const line = (chunk.text || "").split(/\r?\n/).find((item) => item.startsWith("CAPTION:"));
    if (line) setCaption(line.slice("CAPTION:".length).trim());
    setStatus(line ? "Transcribed." : "Transcribed. The caption was empty.");
  }

  async function saveVoice() {
    if (!source || !dataset) { setError("Pick a source and a dataset folder."); return; }
    if (!caption.trim()) { setError("Write a caption first."); return; }
    const allowed = form?.audio_grid_frames || [22, 39, 56, 73, 90, 107, 124];
    const length = allowed.includes(frames) ? frames : allowed[0];
    const done = await postJob("/api/gizmo/voices", {
      source, dataset, segments: [{ start: inFrame / fps, frames: length, caption }],
    });
    if (done) setStatus(done.status === "done" ? "Voice segment saved." : `Voice ${done.status}.`);
  }

  return (
    <section>
      <h2>Gizmo</h2>
      <div className="field">
        <label>Source<input value={source} onChange={(event) => setSource(event.target.value)} /></label>
        <BrowseButton select="file" onPick={setSource} />
        <input type="file" onChange={(event) => void upload(event.target.files?.[0])} />
      </div>
      {source ? <video ref={videoRef} src={`/api/gizmo/media?path=${encodeURIComponent(source)}`} controls /> : null}
      <p className="meta">
        {probe ? `${probe.display_width || probe.width}x${probe.display_height || probe.height} · ${probe.duration ?? "?"}s · in ${inFrame}` : "No probe"}
        {outFrame != null ? ` · out ${outFrame}` : ""}
      </p>
      <div className="controls">
        <button type="button" onClick={() => snap("in")}>Mark in</button>
        <button type="button" onClick={() => snap("out")}>Mark out</button>
        <label>
          Length
          <select value={frames} onChange={(event) => setFrames(Number(event.target.value))}>
            {(form?.grid_frames || [22]).map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label>
          <input type="checkbox" checked={muted} onChange={(event) => setMuted(event.target.checked)} />
          Mute
        </label>
      </div>
      <div className="field">
        <label>Dataset<input value={dataset} onChange={(event) => setDataset(event.target.value)} /></label>
        <BrowseButton select="folder" onPick={setDataset} />
      </div>
      <div className="field">
        <label>Caption<input value={caption} onChange={(event) => setCaption(event.target.value)} /></label>
      </div>
      <div className="controls">
        <button type="button" onClick={() => void cut([clip(inFrame / fps)])}>Cut</button>
        <button type="button" onClick={() => void saveVoice()}>Save voice</button>
        <label>
          Scenes
          <select value={threshold} onChange={(event) => setThreshold(Number(event.target.value))}>
            {(form?.scene_sensitivities || []).map((item) => <option key={item.label} value={item.threshold}>{item.label}</option>)}
          </select>
        </label>
        <button type="button" onClick={() => void chop()}>Chop</button>
        <button type="button" disabled={!starts.length} onClick={() => void cut(starts.map((start) => clip(start)))}>Cut kept starts</button>
        <button type="button" onClick={() => void transcribe()}>Transcribe</button>
        <button type="button" onClick={() => {
          if (recording) { recorderRef.current?.stop(); return; }
          if (!dataset) { setError("Pick a dataset folder first."); return; }
          void navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
            const recorder = new MediaRecorder(stream);
            const chunks: Blob[] = [];
            recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
            recorder.onstop = () => {
              stream.getTracks().forEach((track) => track.stop());
              setRecording(false);
              const data = new FormData();
              data.set("dest", dataset);
              data.set("file", new File([new Blob(chunks, { type: "audio/webm" })], "take.webm", { type: "audio/webm" }));
              void fetch("/api/gizmo/recordings", { method: "POST", body: data }).then(async (response) => {
                if (!response.ok) { setError(await readError(response)); return; }
                const body = await response.json() as { path?: string };
                if (body.path) setSource(body.path);
                setStatus(body.path ? "Recorded." : "Recorded.");
              });
            };
            recorderRef.current = recorder;
            recorder.start();
            setRecording(true);
            setError("");
          }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "microphone failed"));
        }}>{recording ? "Stop" : "Record"}</button>
      </div>
      {starts.length ? <p className="meta">{starts.join(", ")}</p> : null}
      {status ? <p className="status">{status}</p> : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
