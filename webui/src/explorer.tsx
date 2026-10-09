import { useEffect, useRef, useState } from "react";
import { BrowseButton } from "./extra";

interface ExplorerForm {
  family: string;
  display_name: string;
  families: Array<{ key: string; name: string }>;
  resolutions: string[];
  mutations: string[];
  anchor: string;
  defaults: {
    seed: string;
    resolution: string;
    intensity: number;
    mutations: string;
    structure: number;
  };
  debounce_ms: number;
}

interface EngineEvent {
  event?: string;
  message?: string;
  gen?: number;
  step?: number;
  file_url?: string;
  baseline_url?: string;
  side?: string;
}

interface Fields {
  family: string;
  lora: string;
  prompt: string;
  reference: string;
  seed: string;
  resolution: string;
  intensity: string;
  mutations: string;
  structure: string;
}

function readError(response: Response): Promise<string> {
  return response.json().then(
    (body) => body.detail || (body.problems || []).join(" ") || `request failed (${response.status})`,
    () => `request failed (${response.status})`,
  );
}

function num(value: string, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function ExplorerPanel() {
  const [form, setForm] = useState<ExplorerForm | null>(null);
  const [family, setFamily] = useState("");
  const [lora, setLora] = useState("");
  const [prompt, setPrompt] = useState("");
  const [reference, setReference] = useState("");
  const [seed, setSeed] = useState("42");
  const [resolution, setResolution] = useState("512");
  const [intensity, setIntensity] = useState("0.964");
  const [mutations, setMutations] = useState("8");
  const [structure, setStructure] = useState("1");
  const [baselineUrl, setBaselineUrl] = useState("");
  const [variantUrls, setVariantUrls] = useState<string[]>(["", "", "", ""]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const gen = useRef(0);
  const timer = useRef<number | null>(null);
  const armed = useRef(false);
  const delay = useRef(750);
  const fields = useRef<Fields>({
    family: "",
    lora: "",
    prompt: "",
    reference: "",
    seed: "42",
    resolution: "512",
    intensity: "0.964",
    mutations: "8",
    structure: "1",
  });

  fields.current = { family, lora, prompt, reference, seed, resolution, intensity, mutations, structure };

  function loadForm(next: string) {
    fetch(`/api/explorer/form?family=${encodeURIComponent(next)}`)
      .then((response) => response.json())
      .then((body: ExplorerForm) => {
        setForm(body);
        setFamily(body.family);
        setSeed(String(body.defaults.seed));
        setResolution(String(body.defaults.resolution));
        setIntensity(String(body.defaults.intensity));
        setMutations(String(body.defaults.mutations));
        setStructure(String(body.defaults.structure));
        delay.current = body.debounce_ms || 750;
      })
      .catch(() => setError("explorer form failed"));
  }

  useEffect(() => {
    loadForm("");
    const source = new EventSource("/api/events");
    source.addEventListener("engine", (event) => {
      const body = JSON.parse((event as MessageEvent).data) as EngineEvent;
      if (body.gen != null && body.gen !== gen.current) {
        return;
      }
      if (body.event === "frame" && body.file_url) {
        if (body.side === "baseline") {
          setBaselineUrl(body.file_url);
          setStatus("Baseline ready.");
        } else if (body.side === "variant") {
          const index = (body.step || 1) - 2;
          if (index >= 0 && index < 4) {
            setVariantUrls((current) => {
              const next = current.slice();
              next[index] = body.file_url || "";
              return next;
            });
            setStatus(`Variant ${index + 1} ready.`);
          }
        }
      } else if (body.event === "done") {
        if (body.baseline_url) {
          setBaselineUrl(body.baseline_url);
        }
        setStatus("Ready.");
      } else if (body.event === "cancelled") {
        setStatus("Restarting with your latest change…");
      } else if (body.event === "error") {
        setError(body.message || "The engine failed.");
      } else if (body.event === "loading") {
        setStatus("Loading…");
      }
    });
    return () => {
      source.close();
      if (timer.current != null) {
        window.clearTimeout(timer.current);
      }
    };
  }, []);

  function payload(nextGen: number) {
    const current = fields.current;
    return {
      family: current.family,
      lora: current.lora,
      prompt: current.prompt,
      reference: current.reference,
      seed: num(current.seed, 42),
      resolution: num(current.resolution, 512),
      intensity: num(current.intensity, 0.964),
      mutations: num(current.mutations, 8),
      structure: num(current.structure, 1),
      gen: nextGen,
    };
  }

  function bump(): number {
    gen.current += 1;
    setVariantUrls(["", "", "", ""]);
    return gen.current;
  }

  async function post(path: string, body: object): Promise<Record<string, unknown> | null> {
    setError("");
    const response = await fetch(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      setError(await readError(response));
      return null;
    }
    return response.json();
  }

  async function roll() {
    const next = bump();
    const body = await post("/api/explorer/roll", payload(next));
    if (body) {
      setStatus("Rolling…");
    }
  }

  function schedule() {
    if (!armed.current) {
      return;
    }
    if (timer.current != null) {
      window.clearTimeout(timer.current);
    }
    timer.current = window.setTimeout(() => {
      timer.current = null;
      void roll();
    }, delay.current || 750);
  }

  async function start() {
    const body = await post("/api/explorer/load", {
      family: fields.current.family,
      lora: fields.current.lora,
      prompt: fields.current.prompt,
      reference: fields.current.reference,
      seed: num(fields.current.seed, 42),
      resolution: num(fields.current.resolution, 512),
    });
    if (!body) {
      return;
    }
    armed.current = true;
    setStatus("Loaded.");
    await roll();
  }

  async function pick(index: number) {
    const next = bump();
    const body = await post("/api/explorer/pick", { ...payload(next), index });
    if (body) {
      setStatus(`Variant ${index + 1} picked.`);
    }
  }

  async function postFreeze(choice: string) {
    const body = await post("/api/explorer/freeze", { choice });
    if (!body || choice === "cancel") {
      return;
    }
    const locked = Array.isArray(body.locked) ? body.locked.length : 0;
    setStatus(choice === "unlock" ? "Unlocked." : `${locked} frozen.`);
    await roll();
  }

  async function postUndo() {
    const body = await post("/api/explorer/undo", {});
    if (!body) {
      return;
    }
    setVariantUrls(["", "", "", ""]);
    setStatus("Undone.");
    await roll();
  }

  async function postReset(mode: string) {
    if (mode === "full") {
      if (timer.current != null) {
        window.clearTimeout(timer.current);
      }
      armed.current = false;
      setBaselineUrl("");
      setVariantUrls(["", "", "", ""]);
    }
    const body = await post("/api/explorer/reset", { mode });
    if (!body) {
      return;
    }
    setStatus(mode === "full" ? "Reset." : "Restarted.");
    if (mode !== "full") {
      await roll();
    }
  }

  async function save() {
    const body = await post("/api/explorer/save", {});
    if (body) {
      setStatus(`Saved ${String(body.path ?? "")}`);
    }
  }

  const families = form?.families || [];
  return (
    <main>
      <section>
        <h2>LoRA the Explorer</h2>
        <div className="field">
          <label>
            Family
            <select
              value={family}
              onChange={(event) => {
                if (timer.current != null) {
                  window.clearTimeout(timer.current);
                }
                armed.current = false;
                setFamily(event.target.value);
                loadForm(event.target.value);
              }}
            >
              {families.map((item) => <option key={item.key} value={item.key}>{item.name}</option>)}
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
            Reference
            <input value={reference} onChange={(event) => setReference(event.target.value)} />
          </label>
          <BrowseButton select="file" onPick={setReference} />
        </div>
        <div className="field">
          <label>
            Seed
            <input value={seed} onChange={(event) => setSeed(event.target.value)} />
          </label>
        </div>
        <div className="field">
          <label>
            Resolution
            <select value={resolution} onChange={(event) => setResolution(event.target.value)}>
              {(form?.resolutions || ["256", "384", "512", "768"]).map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>
            {`Intensity (${intensity})`}
            <input
              type="range"
              min={0}
              max={1}
              step={0.001}
              value={intensity}
              onChange={(event) => {
                fields.current.intensity = event.target.value;
                setIntensity(event.target.value);
                schedule();
              }}
            />
          </label>
        </div>
        <div className="field">
          <label>
            Mutations
            <select value={mutations} onChange={(event) => setMutations(event.target.value)}>
              {(form?.mutations || ["8"]).map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>
            {`Structure (${structure})`}
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={structure}
              onChange={(event) => {
                fields.current.structure = event.target.value;
                setStructure(event.target.value);
                schedule();
              }}
            />
          </label>
        </div>
        <div className="controls">
          <button type="button" className="start" onClick={() => void start()}>Start</button>
          <button type="button" onClick={() => void postFreeze("freeze")}>Freeze</button>
          <button type="button" onClick={() => void postFreeze("unlock")}>Unlock</button>
          <button type="button" onClick={() => void postFreeze("undo")}>Undo freeze</button>
          <button type="button" onClick={() => void postUndo()}>Undo</button>
          <button type="button" onClick={() => void postReset("defaults")}>Reset defaults</button>
          <button type="button" onClick={() => void postReset("baseline")}>Reset keep baseline</button>
          <button type="button" onClick={() => void postReset("full")}>Full reset</button>
          <button type="button" onClick={() => void save()}>Save</button>
        </div>
        {error ? <p className="error">{error}</p> : null}
        {status ? <p className="status">{status}</p> : null}
      </section>
      <section>
        <h2>Baseline</h2>
        <div className="pair">
          <figure>
            <figcaption>Baseline</figcaption>
            {baselineUrl ? <img src={baselineUrl} alt="" /> : <p className="status">No baseline yet.</p>}
          </figure>
        </div>
        <div className="gallery">
          {variantUrls.map((url, index) => (
            <button key={index} type="button" onClick={() => void pick(index)}>
              {url ? <img src={url} alt="" /> : <span className="status">{`Variant ${index + 1}`}</span>}
            </button>
          ))}
        </div>
      </section>
    </main>
  );
}
