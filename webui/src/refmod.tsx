import { useEffect, useRef, useState } from "react";
import { BrowseButton } from "./extra";

interface ModRow {
  on: boolean;
  mod: string;
  value: string;
  copies: string;
}

interface Curve {
  direction: string;
  shape: string;
  amount: string;
}

interface RefmodForm {
  model: string;
  base: string;
  prompt: string;
  seed: string;
  frames: string;
  width: string;
  height: string;
  steps: string;
  turbo: string;
  sound: boolean;
  early: boolean;
  retention: number;
  scramble: string;
  frame_curve: [string, string, number];
  step_curve: [string, string, number];
  step_on: boolean;
  numbered: boolean;
  compare: string;
  folder: string;
  lora: string;
  debounce_redraw_ms: number;
  models: string[];
  bases: string[];
  lengths: string[];
  compares: string[];
  sizes: string[];
  directions: string[];
  shapes: string[];
  presets: string[];
}

interface ModInfo {
  name: string;
  kind: string;
  path: string;
}

interface EngineEvent {
  event?: string;
  message?: string;
  restarted?: boolean;
  gen?: number;
  step?: number;
  total?: number;
  file_url?: string;
  baseline_url?: string;
  image_url?: string;
  side?: string;
}

interface PresetFile {
  model?: string;
  base?: string;
  prompt?: string;
  seed?: string;
  frames?: string;
  width?: string;
  height?: string;
  steps?: string;
  turbo?: string;
  sound?: boolean;
  early?: boolean;
  retention?: number;
  scramble?: string;
  frame_curve?: [string, string, number];
  step_curve?: [string, string, number];
  step_on?: boolean;
  numbered?: boolean;
  compare?: string;
  folder?: string;
  lora?: string;
  rows?: Array<{ on?: boolean; mod?: string; value?: number; copies?: number }>;
}

const BLANK: ModRow = { on: true, mod: "", value: "1", copies: "1" };

let refmodGen: number | null = null;
let refmodWait = false;
// The newest engine event seq this panel has seen. A remount resumes after it with ?since=.
let refmodSince = 0;

function readError(response: Response): Promise<string> {
  return response.json().then(
    (body) => body.detail || (body.problems || []).join(" ") || `request failed (${response.status})`,
    () => `request failed (${response.status})`,
  );
}

function curveFrom(raw: [string, string, number] | undefined, fallback: Curve): Curve {
  if (!raw || raw.length < 3) {
    return fallback;
  }
  return { direction: String(raw[0]), shape: String(raw[1]), amount: String(raw[2]) };
}

export function RefmodPanel() {
  const [form, setForm] = useState<RefmodForm | null>(null);
  const [folder, setFolder] = useState("");
  const [model, setModel] = useState("Reference (ref2va)");
  const [base, setBase] = useState("Auto (by free VRAM)");
  const [lora, setLora] = useState("");
  const [prompt, setPrompt] = useState("a woman smiles at the camera, soft window light");
  const [seed, setSeed] = useState("300");
  const [frames, setFrames] = useState("22 frames (~1s)");
  const [width, setWidth] = useState("640");
  const [height, setHeight] = useState("768");
  const [steps, setSteps] = useState("4");
  const [turbo, setTurbo] = useState("1.0");
  const [sound, setSound] = useState(true);
  const [early, setEarly] = useState(true);
  const [retention, setRetention] = useState("1");
  const [scramble, setScramble] = useState("-1");
  const [frameCurve, setFrameCurve] = useState<Curve>({ direction: "concept_at_start", shape: "ease", amount: "1" });
  const [stepCurve, setStepCurve] = useState<Curve>({ direction: "concept_at_start", shape: "ease", amount: "1" });
  const [stepOn, setStepOn] = useState(false);
  const [numbered, setNumbered] = useState(false);
  const [compare, setCompare] = useState("No mod (LoRA alone)");
  const [rows, setRows] = useState<ModRow[]>([{ ...BLANK }]);
  const [mods, setMods] = useState<ModInfo[]>([]);
  const [presetName, setPresetName] = useState("");
  const [presets, setPresets] = useState<string[]>([]);
  const [imageUrl, setImageUrl] = useState("");
  const [baselineUrl, setBaselineUrl] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const timer = useRef<number | null>(null);
  const pending = useRef<{ gen: number; image?: string; baseline?: string } | null>(null);
  const delay = useRef(60);

  function applyForm(body: RefmodForm) {
    setForm(body);
    setModel(body.model);
    setBase(body.base);
    setPrompt(body.prompt);
    setSeed(body.seed);
    setFrames(body.frames);
    setWidth(body.width);
    setHeight(body.height);
    setSteps(body.steps);
    setTurbo(body.turbo);
    setSound(body.sound);
    setEarly(body.early);
    setRetention(String(body.retention));
    setScramble(body.scramble);
    setFrameCurve(curveFrom(body.frame_curve, frameCurve));
    setStepCurve(curveFrom(body.step_curve, stepCurve));
    setStepOn(body.step_on);
    setNumbered(body.numbered);
    setCompare(body.compare);
    setFolder(body.folder || "");
    setLora(body.lora || "");
    setPresets(body.presets || []);
    delay.current = body.debounce_redraw_ms || 60;
  }

  function applyPreset(body: PresetFile) {
    if (body.model) setModel(body.model);
    if (body.base) setBase(body.base);
    if (body.prompt != null) setPrompt(body.prompt);
    if (body.seed != null) setSeed(String(body.seed));
    if (body.frames) setFrames(body.frames);
    if (body.width != null) setWidth(String(body.width));
    if (body.height != null) setHeight(String(body.height));
    if (body.steps != null) setSteps(String(body.steps));
    if (body.turbo != null) setTurbo(String(body.turbo));
    if (body.sound != null) setSound(Boolean(body.sound));
    if (body.early != null) setEarly(Boolean(body.early));
    if (body.retention != null) setRetention(String(body.retention));
    if (body.scramble != null) setScramble(String(body.scramble));
    if (body.frame_curve) setFrameCurve(curveFrom(body.frame_curve, frameCurve));
    if (body.step_curve) setStepCurve(curveFrom(body.step_curve, stepCurve));
    if (body.step_on != null) setStepOn(Boolean(body.step_on));
    if (body.numbered != null) setNumbered(Boolean(body.numbered));
    if (body.compare) setCompare(body.compare);
    if (body.folder != null) setFolder(body.folder);
    if (body.lora != null) setLora(body.lora);
    const next = (body.rows || []).map((row) => ({
      on: Boolean(row.on),
      mod: String(row.mod || ""),
      value: String(row.value ?? 1),
      copies: String(row.copies ?? 1),
    }));
    setRows(next.length ? next : [{ ...BLANK }]);
  }

  useEffect(() => {
    fetch("/api/refmod/form")
      .then((response) => response.json())
      .then((body: RefmodForm) => applyForm(body))
      .catch(() => setError("RefMod form failed"));
  }, []);

  useEffect(() => {
    if (!folder) {
      setMods([]);
      return;
    }
    const handle = window.setTimeout(() => {
      fetch("/api/refmod/scan", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ folder }),
      })
        .then(async (response) => {
          if (!response.ok) {
            throw new Error(await readError(response));
          }
          return response.json() as Promise<{ mods: ModInfo[] }>;
        })
        .then((body) => setMods(body.mods || []))
        .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "scan failed"));
    }, 0);
    return () => window.clearTimeout(handle);
  }, [folder]);

  function queueImage(eventGen: number, patch: { image?: string; baseline?: string }) {
    if (eventGen !== refmodGen) {
      return;
    }
    const previous = pending.current && pending.current.gen === eventGen ? pending.current : { gen: eventGen };
    pending.current = { ...previous, ...patch, gen: eventGen };
    if (timer.current != null) {
      window.clearTimeout(timer.current);
    }
    timer.current = window.setTimeout(() => {
      const next = pending.current;
      pending.current = null;
      timer.current = null;
      if (!next || next.gen !== refmodGen) {
        return;
      }
      if (next.image) {
        setImageUrl(next.image);
      }
      if (next.baseline) {
        setBaselineUrl(next.baseline);
      }
    }, delay.current);
  }

  useEffect(() => {
    let source: EventSource | null = null;
    let retry: number | null = null;
    let stopped = false;

    function open() {
      source = new EventSource(refmodSince > 0 ? `/api/events?since=${refmodSince}` : "/api/events");
      source.addEventListener("engine", (event) => {
      const seq = Number((event as MessageEvent).lastEventId);
      if (Number.isInteger(seq) && seq > 0) {
        refmodSince = seq;
      }
      const body = JSON.parse((event as MessageEvent).data) as EngineEvent;
      if (body.gen != null && (body.event === "frame" || body.event === "done" || body.event === "cancelled")) {
        if (refmodWait && (body.event === "frame" || body.event === "done")) {
          refmodGen = body.gen;
          refmodWait = false;
        }
        if (body.gen !== refmodGen) {
          return;
        }
      }
      if (body.event === "loading") {
        setStatus("Loading…");
      } else if (body.event === "frame" && body.file_url && body.gen != null) {
        if (body.side === "early" || body.side === "tweaked") {
          queueImage(body.gen, { image: body.file_url });
          setStatus(`Early look, pass ${body.step} of ${body.total}`);
        }
      } else if (body.event === "done" && body.gen != null) {
        queueImage(body.gen, { image: body.image_url, baseline: body.baseline_url });
        setStatus("Ready.");
      } else if (body.event === "cancelled") {
        setStatus("Restarting with your latest change…");
      } else if (body.event === "error") {
        setError(body.message || "The engine failed.");
        if (body.restarted) {
          setStatus("The engine worker stopped. It will start again on the next request.");
        }
      } else if (body.event === "unloaded") {
        setStatus("Unloaded.");
      }
      });
      source.onerror = () => {
        if (stopped || source == null || source.readyState !== EventSource.CLOSED) {
          return;
        }
        source.close();
        source = null;
        retry = window.setTimeout(() => {
          retry = null;
          if (!stopped) {
            open();
          }
        }, 2000);
      };
    }

    open();
    return () => {
      stopped = true;
      if (retry != null) {
        window.clearTimeout(retry);
      }
      source?.close();
      if (timer.current != null) {
        window.clearTimeout(timer.current);
      }
    };
  }, []);

  function postedRows() {
    return rows.filter((row) => row.mod.trim()).map((row) => ({
      on: row.on,
      mod: row.mod.trim(),
      value: Number(row.value) || 0,
      copies: Number(row.copies) || 1,
    }));
  }

  function setupBody() {
    return {
      folder,
      model,
      base,
      lora,
      prompt,
      seed,
      frames,
      width,
      height,
      steps,
      turbo,
      sound,
      early,
      retention: Number(retention),
      scramble,
      frame_curve: [frameCurve.direction, frameCurve.shape, Number(frameCurve.amount) || 1],
      step_curve: [stepCurve.direction, stepCurve.shape, Number(stepCurve.amount) || 1],
      step_on: stepOn,
      numbered,
      compare,
      rows: postedRows(),
    };
  }

  async function loadEngine() {
    setError("");
    const response = await fetch("/api/refmod/load", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ folder, lora, model, base }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    setStatus("Base loaded.");
  }

  async function unload() {
    await fetch("/api/engine/unload", { method: "POST" });
    setStatus("Unloaded.");
  }

  async function render() {
    setError("");
    setStatus("Rendering…");
    refmodWait = true;
    const response = await fetch("/api/refmod/render", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(setupBody()),
    });
    if (!response.ok) {
      refmodWait = false;
      setError(await readError(response));
      return;
    }
    const body = await response.json() as { gen?: number };
    refmodWait = false;
    if (typeof body.gen === "number") {
      refmodGen = body.gen;
    }
  }

  async function savePreset() {
    setError("");
    const response = await fetch("/api/refmod/presets", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: presetName, overwrite: true, ...setupBody() }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    const listed = await fetch("/api/refmod/presets").then((item) => item.json());
    setPresets(listed.presets || []);
    setStatus(`Saved ${presetName}`);
  }

  async function loadPreset(name: string) {
    setPresetName(name);
    if (!name) {
      return;
    }
    const response = await fetch(`/api/refmod/presets/file?name=${encodeURIComponent(name)}`);
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    applyPreset(await response.json());
    setStatus(`Loaded ${name}`);
  }

  function patchRow(index: number, patch: Partial<ModRow>) {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  const models = form?.models || ["Reference (ref2va)", "First / Last Frame (fl2va)"];
  const bases = form?.bases || ["Auto (by free VRAM)"];
  const lengths = form?.lengths || ["Still (1 frame)", "22 frames (~1s)"];
  const compares = form?.compares || ["No mod (LoRA alone)", "No LoRA (mods alone)", "Neither (base model)"];
  const sizes = form?.sizes || ["640", "768"];
  const directions = form?.directions || ["concept_at_start", "concept_at_end", "constant"];
  const shapes = form?.shapes || ["ease", "linear"];

  return (
    <main>
      <section>
        <h2>RefMod Studio</h2>
        <p className="help">Mods on the H3 reference base. The picture waits 60 ms before it changes.</p>
        <div className="field">
          <label>
            Folder
            <input value={folder} onChange={(event) => setFolder(event.target.value)} />
          </label>
          <BrowseButton select="folder" onPick={setFolder} />
        </div>
        <div className="field">
          <label>
            Model
            <select value={model} onChange={(event) => setModel(event.target.value)}>
              {models.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>
            Base
            <select value={base} onChange={(event) => setBase(event.target.value)}>
              {bases.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>
            LoRA
            <input value={lora} onChange={(event) => setLora(event.target.value)} />
          </label>
          <BrowseButton select="file" onPick={setLora} />
        </div>
        <div className="field">
          <label>
            Prompt
            <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} />
          </label>
        </div>
        <div className="field">
          <label>
            Seed
            <input value={seed} onChange={(event) => setSeed(event.target.value)} />
          </label>
        </div>
        <div className="field">
          <label>
            Length
            <select value={frames} onChange={(event) => setFrames(event.target.value)}>
              {lengths.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>
            Width
            <select value={width} onChange={(event) => setWidth(event.target.value)}>
              {sizes.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label>
            Height
            <select value={height} onChange={(event) => setHeight(event.target.value)}>
              {sizes.map((item) => <option key={`h-${item}`} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>
            Steps
            <input value={steps} onChange={(event) => setSteps(event.target.value)} />
          </label>
          <label>
            Turbo
            <input value={turbo} onChange={(event) => setTurbo(event.target.value)} />
          </label>
        </div>
        <label className="field">
          <input type="checkbox" checked={sound} onChange={(event) => setSound(event.target.checked)} />
          Sound
        </label>
        <label className="field">
          <input type="checkbox" checked={early} onChange={(event) => setEarly(event.target.checked)} />
          Show early
        </label>
        <div className="field">
          <label>
            Retention
            <input value={retention} onChange={(event) => setRetention(event.target.value)} />
          </label>
        </div>
        <div className="field">
          <label>
            Frame curve
            <select value={frameCurve.direction} onChange={(event) => setFrameCurve({ ...frameCurve, direction: event.target.value })}>
              {directions.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label>
            Shape
            <select value={frameCurve.shape} onChange={(event) => setFrameCurve({ ...frameCurve, shape: event.target.value })}>
              {shapes.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label>
            Amount
            <input value={frameCurve.amount} onChange={(event) => setFrameCurve({ ...frameCurve, amount: event.target.value })} />
          </label>
        </div>
        <label className="field">
          <input type="checkbox" checked={stepOn} onChange={(event) => setStepOn(event.target.checked)} />
          Step curve
        </label>
        <div className="field">
          <label>
            Step curve
            <select value={stepCurve.direction} onChange={(event) => setStepCurve({ ...stepCurve, direction: event.target.value })}>
              {directions.map((item) => <option key={`s-${item}`} value={item}>{item}</option>)}
            </select>
          </label>
          <label>
            Shape
            <select value={stepCurve.shape} onChange={(event) => setStepCurve({ ...stepCurve, shape: event.target.value })}>
              {shapes.map((item) => <option key={`ss-${item}`} value={item}>{item}</option>)}
            </select>
          </label>
          <label>
            Amount
            <input value={stepCurve.amount} onChange={(event) => setStepCurve({ ...stepCurve, amount: event.target.value })} />
          </label>
        </div>
        <label className="field">
          <input type="checkbox" checked={numbered} onChange={(event) => setNumbered(event.target.checked)} />
          Numbered
        </label>
        <div className="field">
          <label>
            Compare
            <select value={compare} onChange={(event) => setCompare(event.target.value)}>
              {compares.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
        {rows.map((row, index) => (
          <div className="field" key={index}>
            <label>
              <input type="checkbox" checked={row.on} onChange={(event) => patchRow(index, { on: event.target.checked })} />
              On
            </label>
            <label>
              Mod
              <input value={row.mod} list="refmod-mods" onChange={(event) => patchRow(index, { mod: event.target.value })} />
            </label>
            <label>
              Value
              <input value={row.value} onChange={(event) => patchRow(index, { value: event.target.value })} />
            </label>
            <label>
              Copies
              <input value={row.copies} onChange={(event) => patchRow(index, { copies: event.target.value })} />
            </label>
            <button type="button" onClick={() => setRows((current) => {
              const next = current.filter((_, i) => i !== index);
              return next.length ? next : [{ ...BLANK }];
            })}
            >
              Remove
            </button>
          </div>
        ))}
        <datalist id="refmod-mods">
          {mods.map((item) => <option key={item.path || item.name} value={item.name} />)}
        </datalist>
        <div className="controls">
          <button type="button" onClick={() => setRows((current) => [...current, { ...BLANK }])}>Add mod</button>
          <button type="button" onClick={() => void loadEngine()}>Load base</button>
          <button type="button" className="start" onClick={() => void render()}>Render</button>
          <button type="button" onClick={() => void unload()}>Unload</button>
        </div>
        <div className="field">
          <label>
            Preset
            <select value={presetName} onChange={(event) => void loadPreset(event.target.value)}>
              <option value=""> </option>
              {presets.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>
            Preset name
            <input value={presetName} onChange={(event) => setPresetName(event.target.value)} />
          </label>
          <button type="button" onClick={() => void savePreset()}>Save</button>
          <button type="button" onClick={() => void loadPreset(presetName)}>Load</button>
        </div>
        {error ? <p className="error">{error}</p> : null}
        {status ? <p className="status">{status}</p> : null}
      </section>
      <section>
        <h2>Preview</h2>
        <div className="pair">
          <figure>
            <figcaption>With mods</figcaption>
            {imageUrl ? <img src={imageUrl} alt="" /> : <p className="status">No render yet.</p>}
          </figure>
          <figure>
            <figcaption>Comparison</figcaption>
            {baselineUrl ? <img src={baselineUrl} alt="" /> : <p className="status">No comparison yet.</p>}
          </figure>
        </div>
      </section>
    </main>
  );
}
