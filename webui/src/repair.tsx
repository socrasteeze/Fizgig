import { useEffect, useRef, useState } from "react";
import { BrowseButton } from "./extra";

const HANDOFF_KEY = "fizgig.repair.handoff";

interface BlockRow {
  primary_enabled: boolean;
  primary_strength: number;
  donor_enabled: boolean;
  donor_strength: number;
}

interface Group {
  label: string;
  blocks: Array<{ id: string; label: string }>;
}

interface RepairForm {
  family: string;
  families: Array<{ key: string; name: string; video: boolean }>;
  groups: Group[];
  resolutions: string[];
  video: boolean;
  follows_samples: boolean;
  dit_choices: Array<{ id: string; label: string }>;
  presets: string[];
  defaults: {
    seed: number;
    resolution: string;
    primary_scale: number;
    donor_scale: number;
    ref_megapixels: number;
    ref_strength: number;
    dit: string;
    blocks: Record<string, BlockRow>;
  };
  debounce_ms: number;
  debounce_force_ms: number;
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
  clip_url?: string;
  side?: string;
}

function readError(response: Response): Promise<string> {
  return response.json().then(
    (body) => body.detail || (body.problems || []).join(" ") || `request failed (${response.status})`,
    () => `request failed (${response.status})`,
  );
}

export function RepairPanel() {
  const [form, setForm] = useState<RepairForm | null>(null);
  const [family, setFamily] = useState("");
  const [dit, setDit] = useState("fast");
  const [primary, setPrimary] = useState("");
  const [donor, setDonor] = useState("");
  const [primaryScale, setPrimaryScale] = useState("1");
  const [donorScale, setDonorScale] = useState("1");
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [seed, setSeed] = useState("42");
  const [resolution, setResolution] = useState("768");
  const [reference, setReference] = useState("");
  const [refMp, setRefMp] = useState("1");
  const [refStrength, setRefStrength] = useState("1");
  const [blocks, setBlocks] = useState<Record<string, BlockRow>>({});
  const [preset, setPreset] = useState("");
  const [presetName, setPresetName] = useState("");
  const [early, setEarly] = useState(false);
  const [baselineUrl, setBaselineUrl] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [clipUrl, setClipUrl] = useState("");
  const [metrics, setMetrics] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [armed, setArmed] = useState(false);
  const gen = useRef(0);
  const timer = useRef<number | null>(null);
  const paths = useRef({ baseline: "", image: "" });
  const pending = useRef<{
    family?: string;
    lora?: string;
    prompt?: string;
    seed?: number;
    size?: number;
    blocks?: Record<string, { enabled: boolean; strength: number }>;
    message?: string;
  } | null>(null);

  function applyBlocks(next: Record<string, BlockRow>) {
    setBlocks(next);
  }

  function load(next: string) {
    fetch(`/api/repair/form?family=${encodeURIComponent(next)}`)
      .then((response) => response.json())
      .then((body: RepairForm) => {
        setForm(body);
        setFamily(body.family);
        setDit(body.defaults.dit);
        setSeed(String(body.defaults.seed));
        setResolution(body.defaults.resolution);
        setPrimaryScale(String(body.defaults.primary_scale));
        setDonorScale(String(body.defaults.donor_scale));
        setRefMp(String(body.defaults.ref_megapixels));
        setRefStrength(String(body.defaults.ref_strength));
        const handoff = pending.current;
        let nextBlocks = body.defaults.blocks;
        if (handoff && handoff.family === body.family) {
          pending.current = null;
          if (handoff.lora) {
            setPrimary(handoff.lora);
          }
          if (handoff.prompt) {
            setPrompt(handoff.prompt);
          }
          if (handoff.seed != null) {
            setSeed(String(handoff.seed));
          }
          if (handoff.size) {
            setResolution(String(handoff.size));
          }
          if (handoff.message) {
            setStatus(handoff.message);
          }
          nextBlocks = { ...nextBlocks };
          for (const [id, row] of Object.entries(handoff.blocks || {})) {
            if (nextBlocks[id]) {
              nextBlocks[id] = { ...nextBlocks[id], primary_enabled: row.enabled, primary_strength: row.strength };
            }
          }
        }
        setBlocks(nextBlocks);
        setPreset(body.presets[0] || "");
      })
      .catch(() => setError("repair form failed"));
  }

  useEffect(() => {
    const raw = sessionStorage.getItem(HANDOFF_KEY);
    if (!raw) {
      load("");
      return;
    }
    sessionStorage.removeItem(HANDOFF_KEY);
    const handoff = JSON.parse(raw) as { family?: string };
    pending.current = JSON.parse(raw);
    load(handoff.family || "");
  }, []);

  useEffect(() => {
    const source = new EventSource("/api/events");
    source.addEventListener("engine", (event) => {
      const body = JSON.parse((event as MessageEvent).data) as EngineEvent;
      if (body.event === "loading") {
        setStatus("Loading…");
      } else if (body.event === "frame" && body.file_url && body.side !== "baseline") {
        setImageUrl(body.file_url);
        setStatus(`Rendering, pass ${body.step} of ${body.total}`);
      } else if (body.event === "done") {
        if (body.baseline_url) {
          setBaselineUrl(body.baseline_url);
          paths.current.baseline = "";
        }
        if (body.image_url) {
          setImageUrl(body.image_url);
        }
        setClipUrl(body.clip_url || "");
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
    return () => source.close();
  }, []);

  function stateBody() {
    const size = Number(resolution) || 768;
    return {
      blocks,
      prompt,
      seed: Number(seed) || 42,
      preview_width: size,
      preview_height: size,
      ref_image_path: reference,
      ref_megapixels: Number(refMp) || 1,
      ref_strength: Number(refStrength) || 1,
      primary_scale: Number(primaryScale) || 1,
      donor_scale: Number(donorScale) || 1,
    };
  }

  async function render() {
    gen.current += 1;
    setError("");
    const response = await fetch("/api/repair/render", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        family,
        gen: gen.current,
        steps: 3,
        video: Boolean(form?.video),
        early_step: early ? 1 : 0,
        state: stateBody(),
        preview_settings: { negative, steps: "", cfg: "", turbo: "0" },
      }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    const body = await response.json();
    const done = await fetch("/api/repair/status").then((item) => item.json());
    const result = done.result;
    if (result && result.gen === body.gen) {
      paths.current = { baseline: result.baseline || "", image: result.image || "" };
    }
  }

  // _schedule_preview: 400 ms, or 100 ms when the edit is forced (Reset, preset).
  function schedule(force = false, live = armed) {
    if (!live) {
      return;
    }
    if (timer.current != null) {
      window.clearTimeout(timer.current);
    }
    const delay = force ? (form?.debounce_force_ms ?? 100) : (form?.debounce_ms ?? 400);
    timer.current = window.setTimeout(() => { void render(); }, delay);
  }

  async function loadEngine() {
    setError("");
    const response = await fetch("/api/repair/load", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ family, primary, donor, dit, primary_scale: Number(primaryScale), donor_scale: Number(donorScale) }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    setStatus("Loaded.");
    setArmed(true);
    schedule(true, true);
  }

  async function unload() {
    setArmed(false);
    await fetch("/api/repair/unload", { method: "POST" });
    setStatus("Unloaded.");
  }

  function resetSliders() {
    if (!form) {
      return;
    }
    applyBlocks(form.defaults.blocks);
    schedule(true);
  }

  async function savePreset() {
    setError("");
    const response = await fetch("/api/repair/presets", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ family, name: presetName, state: stateBody(), overwrite: true }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    load(family);
    setPreset(presetName);
  }

  async function loadPreset(name: string) {
    setPreset(name);
    const response = await fetch(`/api/repair/presets/file?family=${encodeURIComponent(family)}&name=${encodeURIComponent(name)}`);
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    const body = await response.json();
    setBlocks((current) => {
      const next = { ...current };
      for (const [id, row] of Object.entries(body.blocks || {}) as Array<[string, BlockRow]>) {
        if (next[id]) {
          next[id] = { ...next[id], ...row };
        }
      }
      return next;
    });
    schedule(true);
  }

  async function bake() {
    setError("");
    const response = await fetch("/api/repair/bake", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ family, primary, donor, state: stateBody() }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    const body = await response.json();
    setStatus(`Saved ${body.path}`);
  }

  async function compare() {
    setError("");
    const statusBody = await fetch("/api/repair/status").then((item) => item.json());
    const result = statusBody.result || {};
    const response = await fetch("/api/repair/metrics", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ family, baseline: result.baseline, tweaked: result.image }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    const body = await response.json();
    setMetrics(`Grid ${Number(body.grid_base).toFixed(2)} → ${Number(body.grid_tweak).toFixed(2)} · Detail ${Number(body.texture_base).toFixed(0)} → ${Number(body.texture_tweak).toFixed(0)} · Clipped ${Number(body.clip_base).toFixed(1)}% → ${Number(body.clip_tweak).toFixed(1)}%`);
  }

  function setRow(id: string, patch: Partial<BlockRow>) {
    setBlocks((current) => ({ ...current, [id]: { ...current[id], ...patch } }));
    schedule(false);
  }

  const families = form?.families || [];
  return (
    <main>
      <section>
        <h2>Repair Studio</h2>
        <div className="field">
          <label>
            Family
            <select value={family} onChange={(event) => { setFamily(event.target.value); load(event.target.value); }}>
              {families.map((item) => <option key={item.key} value={item.key}>{item.name}</option>)}
            </select>
          </label>
        </div>
        {form?.dit_choices?.length ? (
          <div className="field">
            <label>
              DiT
              <select value={dit} onChange={(event) => setDit(event.target.value)}>
                {form.dit_choices.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
            </label>
          </div>
        ) : null}
        <div className="field">
          <label>
            Primary LoRA
            <input value={primary} onChange={(event) => setPrimary(event.target.value)} />
          </label>
          <BrowseButton select="file" onPick={setPrimary} />
        </div>
        <div className="field">
          <label>
            Primary strength
            <input value={primaryScale} onChange={(event) => setPrimaryScale(event.target.value)} />
          </label>
        </div>
        <div className="field">
          <label>
            Donor LoRA
            <input value={donor} onChange={(event) => setDonor(event.target.value)} />
          </label>
          <BrowseButton select="file" onPick={setDonor} />
        </div>
        <div className="field">
          <label>
            Donor strength
            <input value={donorScale} onChange={(event) => setDonorScale(event.target.value)} />
          </label>
        </div>
        <div className="field">
          <label>
            Prompt
            <textarea value={prompt} onChange={(event) => { setPrompt(event.target.value); schedule(false); }} />
          </label>
        </div>
        <div className="field">
          <label>
            Negative
            <input value={negative} onChange={(event) => { setNegative(event.target.value); schedule(false); }} />
          </label>
        </div>
        <div className="field">
          <label>
            Seed
            <input value={seed} onChange={(event) => { setSeed(event.target.value); schedule(false); }} />
          </label>
        </div>
        <div className="field">
          <label>
            Resolution
            <select value={resolution} onChange={(event) => { setResolution(event.target.value); schedule(false); }}>
              {(form?.resolutions || []).map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>
            Reference
            <input value={reference} onChange={(event) => { setReference(event.target.value); schedule(false); }} />
          </label>
          <BrowseButton select="file" onPick={(path) => { setReference(path); schedule(false); }} />
        </div>
        <div className="field">
          <label>
            Reference MP
            <input value={refMp} onChange={(event) => setRefMp(event.target.value)} />
          </label>
          <label>
            Reference strength
            <input value={refStrength} onChange={(event) => setRefStrength(event.target.value)} />
          </label>
        </div>
        {form?.video ? (
          <label className="field">
            <input type="checkbox" checked={early} onChange={(event) => setEarly(event.target.checked)} />
            Show early
          </label>
        ) : null}
        <div className="controls">
          <button type="button" className="start" onClick={() => void loadEngine()}>Load</button>
          <button type="button" onClick={() => void unload()}>Unload</button>
          <button type="button" onClick={resetSliders}>Reset All Sliders</button>
          <button type="button" onClick={() => void bake()}>Save repaired LoRA</button>
        </div>
        <div className="field">
          <label>
            Preset
            <select value={preset} onChange={(event) => void loadPreset(event.target.value)}>
              <option value=""> </option>
              {(form?.presets || []).map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>
            Save preset as
            <input value={presetName} onChange={(event) => setPresetName(event.target.value)} />
          </label>
          <button type="button" onClick={() => void savePreset()}>Save preset</button>
        </div>
        {error ? <p className="error">{error}</p> : null}
        {status ? <p className="status">{status}</p> : null}
      </section>
      <section>
        <h2>Preview</h2>
        <div className="pair">
          <figure>
            <figcaption>Baseline</figcaption>
            {baselineUrl ? <img src={baselineUrl} alt="" /> : <p className="status">No baseline yet.</p>}
          </figure>
          <figure>
            <figcaption>Repaired</figcaption>
            {imageUrl ? <img src={imageUrl} alt="" /> : <p className="status">No render yet.</p>}
          </figure>
        </div>
        {clipUrl ? <video src={clipUrl} controls loop /> : null}
        <button type="button" onClick={() => void compare()}>Compare + Metrics</button>
        {metrics ? <p className="status">{metrics}</p> : null}
      </section>
      <section>
        <h2>Blocks</h2>
        {(form?.groups || []).map((group) => (
          <div key={group.label}>
            <h3>{group.label}</h3>
            {group.blocks.map((block) => {
              const row = blocks[block.id];
              if (!row) {
                return null;
              }
              return (
                <div className="slider-row" key={block.id}>
                  <label>
                    <input
                      type="checkbox"
                      checked={row.primary_enabled}
                      onChange={(event) => setRow(block.id, { primary_enabled: event.target.checked })}
                    />
                    {block.label}
                  </label>
                  <input
                    type="range"
                    min={-3}
                    max={3}
                    step={0.05}
                    value={row.primary_strength}
                    onChange={(event) => setRow(block.id, { primary_strength: Number(event.target.value) })}
                  />
                  <span>{row.primary_strength.toFixed(2)}</span>
                  {donor ? (
                    <input
                      type="range"
                      min={-3}
                      max={3}
                      step={0.05}
                      value={row.donor_strength}
                      onChange={(event) => setRow(block.id, { donor_strength: Number(event.target.value), donor_enabled: true })}
                    />
                  ) : null}
                </div>
              );
            })}
          </div>
        ))}
      </section>
    </main>
  );
}
