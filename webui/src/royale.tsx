import { useEffect, useRef, useState } from "react";
import { BrowseButton } from "./extra";

interface Family {
  key: string;
  name: string;
}

interface RoyaleForm {
  family: string;
  families: Family[];
  seed: string;
  width: string;
  height: string;
  max_renders: string;
  max_renders_choices: string[];
  speeds: string[];
  formats: string[];
}

interface Item {
  label: string | number;
  path: string;
}

interface Frame {
  url: string;
  path: string;
  step: number;
}

interface EngineEvent {
  event?: string;
  message?: string;
  gen?: number;
  step?: number;
  file?: string;
  file_url?: string;
  side?: string;
}

function readError(response: Response): Promise<string> {
  return response.json().then(
    (body) => body.detail || (body.problems || []).join(" ") || `request failed (${response.status})`,
    () => `request failed (${response.status})`,
  );
}

function upsert(current: Frame[], frame: Frame): Frame[] {
  const next = current.filter((item) => item.step !== frame.step);
  next.push(frame);
  next.sort((a, b) => a.step - b.step);
  return next;
}

export function RoyalePanel() {
  const [families, setFamilies] = useState<Family[]>([]);
  const [family, setFamily] = useState("");
  const [source, setSource] = useState<"folder" | "lora">("folder");
  const [folder, setFolder] = useState("");
  const [lora, setLora] = useState("");
  const [items, setItems] = useState<Item[]>([]);
  const [prompt, setPrompt] = useState("");
  const [seed, setSeed] = useState("42");
  const [size, setSize] = useState("512");
  const [reference, setReference] = useState("");
  const [maxRenders, setMaxRenders] = useState("12");
  const [choices, setChoices] = useState<string[]>(["All", "6", "8", "10", "12", "16", "20"]);
  const [speeds, setSpeeds] = useState<string[]>(["Slow", "Normal", "Fast"]);
  const [formats, setFormats] = useState<string[]>(["MP4", "GIF"]);
  const [format, setFormat] = useState("MP4");
  const [speed, setSpeed] = useState("Normal");
  const [pingpong, setPingpong] = useState(true);
  const [brand, setBrand] = useState(true);
  const [showEpoch, setShowEpoch] = useState(true);
  const [epochs, setEpochs] = useState<Item[]>([]);
  const [epochFrames, setEpochFrames] = useState<Frame[]>([]);
  const [pos, setPos] = useState(0);
  const [travelMode, setTravelMode] = useState("seed");
  const [seedA, setSeedA] = useState("42");
  const [seedB, setSeedB] = useState("4242");
  const [waypoints, setWaypoints] = useState("2");
  const [frames, setFrames] = useState("24");
  const [sStart, setSStart] = useState("0");
  const [sEnd, setSEnd] = useState("1");
  const [base, setBase] = useState("");
  const [words, setWords] = useState("");
  const [travelFrames, setTravelFrames] = useState<Frame[]>([]);
  const [travelIndex, setTravelIndex] = useState(0);
  const [shown, setShown] = useState<"epoch" | "travel">("epoch");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const gen = useRef(0);
  const epochGen = useRef(0);
  const travelGen = useRef(0);

  function loadForm(next: string) {
    fetch(`/api/royale/form?family=${encodeURIComponent(next)}`)
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(await readError(response));
        }
        return response.json() as Promise<RoyaleForm>;
      })
      .then((body) => {
        setFamilies(body.families || []);
        setFamily(body.family || "");
        setSeed(body.seed || "42");
        setSize(body.width || "512");
        setMaxRenders(body.max_renders || "12");
        setChoices(body.max_renders_choices || ["All", "6", "8", "10", "12", "16", "20"]);
        setSpeeds(body.speeds || ["Slow", "Normal", "Fast"]);
        setFormats(body.formats || ["MP4", "GIF"]);
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "royale form failed"));
  }

  useEffect(() => {
    loadForm("");
  }, []);

  useEffect(() => {
    const sourceEvents = new EventSource("/api/events");
    sourceEvents.addEventListener("engine", (event) => {
      const body = JSON.parse((event as MessageEvent).data) as EngineEvent;
      if (body.event === "frame" && body.file_url && body.side === "epoch") {
        const seen = body.gen || 0;
        if (seen < epochGen.current) {
          return;
        }
        const fresh = seen !== epochGen.current;
        epochGen.current = seen;
        const frame = { url: body.file_url, path: body.file || "", step: body.step || 0 };
        setEpochFrames((current) => upsert(fresh ? [] : current, frame));
        setStatus(`Epoch ${body.step || ""}`);
      } else if (body.event === "frame" && body.file_url && body.side === "travel") {
        const seen = body.gen || 0;
        if (seen < travelGen.current) {
          return;
        }
        const fresh = seen !== travelGen.current;
        travelGen.current = seen;
        const frame = { url: body.file_url, path: body.file || "", step: body.step || 0 };
        setTravelFrames((current) => upsert(fresh ? [] : current, frame));
        setStatus(`Frame ${body.step || ""}`);
      } else if (body.event === "loading") {
        setStatus("Loading…");
      } else if (body.event === "done") {
        setStatus("Ready.");
      } else if (body.event === "cancelled") {
        setStatus("Restarting with your latest change…");
      } else if (body.event === "error") {
        setError(body.message || "The engine failed.");
      } else if (body.event === "unloaded") {
        setStatus("Unloaded.");
      }
    });
    return () => sourceEvents.close();
  }, []);

  async function scan() {
    setError("");
    const response = await fetch("/api/royale/scan", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(source === "lora" ? { lora } : { folder }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    const body = await response.json() as { items?: Item[] };
    setItems(body.items || []);
    setStatus(`${(body.items || []).length} found`);
  }

  async function loadEngine() {
    setError("");
    const response = await fetch("/api/royale/load", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        family,
        lora: source === "lora" ? lora : "",
        folder: source === "folder" ? folder : "",
      }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    setStatus("Loaded.");
  }

  async function unload() {
    setError("");
    await fetch("/api/engine/unload", { method: "POST" });
    setStatus("Unloaded.");
  }

  async function renderEpochs() {
    setError("");
    gen.current += 1;
    epochGen.current = gen.current;
    setShown("epoch");
    setEpochFrames([]);
    setEpochs([]);
    setPos(0);
    const response = await fetch("/api/royale/render", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        family,
        gen: gen.current,
        prompt,
        seed: Number(seed) || 42,
        width: Number(size) || 512,
        height: Number(size) || 512,
        reference,
        max_renders: maxRenders,
        epochs: items,
      }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    const body = await response.json() as { gen?: number; epochs?: Item[] };
    if (body.gen) {
      gen.current = body.gen;
      epochGen.current = body.gen;
    }
    setEpochs(body.epochs || []);
    setStatus("Rendering epochs…");
  }

  async function renderTravel() {
    setError("");
    gen.current += 1;
    travelGen.current = gen.current;
    setShown("travel");
    setTravelFrames([]);
    setTravelIndex(0);
    const parked = source === "lora" ? lora : (epochs[lo]?.path || items[lo]?.path || items[0]?.path || "");
    const payload: Record<string, unknown> = {
      family,
      gen: gen.current,
      mode: travelMode,
      path: parked,
      prompt,
      seed: Number(seed) || 42,
      width: Number(size) || 512,
      height: Number(size) || 512,
      reference,
      frames: Number(frames) || 2,
    };
    if (travelMode === "seed") {
      payload.seed_a = Number(seedA) || 0;
      payload.seed_b = Number(seedB) || 0;
      payload.waypoints = Number(waypoints) || 2;
    } else if (travelMode === "strength") {
      payload.s_start = Number(sStart);
      payload.s_end = Number(sEnd);
    } else {
      payload.base = base || prompt;
      payload.words = words.split(",").map((word) => word.trim()).filter(Boolean);
    }
    const response = await fetch("/api/royale/travel", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    const body = await response.json() as { gen?: number };
    if (body.gen) {
      gen.current = body.gen;
      travelGen.current = body.gen;
    }
    setStatus("Rendering travel…");
  }

  async function exportClip() {
    setError("");
    const paths = (shown === "travel" ? travelFrames : epochFrames).map((frame) => frame.path).filter(Boolean);
    const response = await fetch("/api/royale/export", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        family,
        folder,
        images: paths,
        format,
        speed,
        pingpong,
        brand,
        show_epoch: showEpoch,
        width: Number(size) || 512,
        height: Number(size) || 512,
      }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    const body = await response.json() as { id?: string };
    setStatus(body.id ? `Export ${body.id}` : "Export started.");
  }

  const n = epochFrames.length;
  const p = n ? Math.min(Math.max(pos, 0), n - 1) : 0;
  const lo = n ? Math.min(Math.floor(p), n - 1) : 0;
  const hi = n ? Math.min(lo + 1, n - 1) : 0;
  const alpha = lo === hi ? 0 : p - lo;
  const loLabel = epochs[lo]?.label ?? "";
  const hiLabel = epochs[hi]?.label ?? "";
  const travelAt = travelFrames.length ? Math.min(travelIndex, travelFrames.length - 1) : 0;

  return (
    <main>
      <section>
        <h2>LoRA Royale</h2>
        <div className="field">
          <label>
            Family
            <select value={family} onChange={(event) => loadForm(event.target.value)}>
              {families.map((item) => <option key={item.key} value={item.key}>{item.name}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>
            Source
            <select value={source} onChange={(event) => setSource(event.target.value as "folder" | "lora")}>
              <option value="folder">Folder</option>
              <option value="lora">One LoRA</option>
            </select>
          </label>
        </div>
        {source === "folder" ? (
          <div className="field">
            <label>
              Folder
              <input value={folder} onChange={(event) => setFolder(event.target.value)} />
            </label>
            <BrowseButton select="folder" onPick={setFolder} />
          </div>
        ) : (
          <div className="field">
            <label>
              LoRA
              <input value={lora} onChange={(event) => setLora(event.target.value)} />
            </label>
            <BrowseButton select="file" onPick={setLora} />
          </div>
        )}
        <div className="controls">
          <button type="button" onClick={() => void scan()}>Scan</button>
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
            Size
            <input value={size} onChange={(event) => setSize(event.target.value)} />
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
            Max renders
            <select value={maxRenders} onChange={(event) => setMaxRenders(event.target.value)}>
              {choices.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
        <div className="controls">
          <button type="button" className="start" onClick={() => void loadEngine()}>Load</button>
          <button type="button" onClick={() => void unload()}>Unload</button>
          <button type="button" onClick={() => void renderEpochs()}>Render</button>
        </div>
        {error ? <p className="error">{error}</p> : null}
        {status ? <p className="status">{status}</p> : null}
      </section>
      <section>
        <h2>Crossfade</h2>
        {n > 0 ? (
          <>
            {/* _royale_scrub: two images in the browser. Moving the range must not fetch. */}
            <div className="pair" style={{ display: "block", position: "relative" }}>
              <img src={epochFrames[lo].url} alt="" />
              <img
                src={epochFrames[hi].url}
                alt=""
                style={{ position: "absolute", left: 0, top: 0, opacity: alpha }}
              />
            </div>
            <div className="slider-row">
              <span>Crossfade</span>
              <input
                type="range"
                min={0}
                max={n - 1}
                step={0.01}
                value={p}
                onChange={(event) => setPos(Number(event.target.value))}
              />
              <span>{Math.round(alpha * 100)}</span>
            </div>
            <p className="status">{String(loLabel)} → {String(hiLabel)}</p>
          </>
        ) : <p className="status">No epoch frames yet.</p>}
      </section>
      <section>
        <h2>Travel</h2>
        <div className="field">
          <label>
            Mode
            <select value={travelMode} onChange={(event) => setTravelMode(event.target.value)}>
              <option value="seed">Seed</option>
              <option value="strength">Strength</option>
              <option value="prompt">Prompt</option>
            </select>
          </label>
        </div>
        {travelMode === "seed" ? (
          <>
            <div className="field">
              <label>
                Seed A
                <input value={seedA} onChange={(event) => setSeedA(event.target.value)} />
              </label>
            </div>
            <div className="field">
              <label>
                Seed B
                <input value={seedB} onChange={(event) => setSeedB(event.target.value)} />
              </label>
            </div>
            <div className="field">
              <label>
                Waypoints
                <input value={waypoints} onChange={(event) => setWaypoints(event.target.value)} />
              </label>
            </div>
          </>
        ) : null}
        {travelMode === "strength" ? (
          <>
            <div className="field">
              <label>
                Start strength
                <input value={sStart} onChange={(event) => setSStart(event.target.value)} />
              </label>
            </div>
            <div className="field">
              <label>
                End strength
                <input value={sEnd} onChange={(event) => setSEnd(event.target.value)} />
              </label>
            </div>
          </>
        ) : null}
        {travelMode === "prompt" ? (
          <>
            <div className="field">
              <label>
                Base prompt
                <textarea value={base} onChange={(event) => setBase(event.target.value)} />
              </label>
            </div>
            <div className="field">
              <label>
                Words
                <input value={words} onChange={(event) => setWords(event.target.value)} />
              </label>
            </div>
          </>
        ) : null}
        <div className="field">
          <label>
            Frames
            <input value={frames} onChange={(event) => setFrames(event.target.value)} />
          </label>
        </div>
        <div className="controls">
          <button type="button" className="start" onClick={() => void renderTravel()}>Render travel</button>
        </div>
        {travelFrames.length > 0 ? (
          <>
            {/* _royale_sc_scrub: one frame by index. Moving the range must not fetch. */}
            <div className="field">
              <img src={travelFrames[travelAt].url} alt="" />
            </div>
            <div className="slider-row">
              <span>Frame</span>
              <input
                type="range"
                min={0}
                max={travelFrames.length - 1}
                step={1}
                value={travelAt}
                onChange={(event) => setTravelIndex(Number(event.target.value))}
              />
              <span>{travelAt + 1}</span>
            </div>
          </>
        ) : <p className="status">No travel frames yet.</p>}
      </section>
      <section>
        <h2>Export</h2>
        <div className="field">
          <label>
            Format
            <select value={format} onChange={(event) => setFormat(event.target.value)}>
              {formats.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>
            Speed
            <select value={speed} onChange={(event) => setSpeed(event.target.value)}>
              {speeds.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
        <label className="field">
          <input type="checkbox" checked={pingpong} onChange={(event) => setPingpong(event.target.checked)} />
          Ping-pong
        </label>
        <label className="field">
          <input type="checkbox" checked={brand} onChange={(event) => setBrand(event.target.checked)} />
          Brand
        </label>
        <label className="field">
          <input type="checkbox" checked={showEpoch} onChange={(event) => setShowEpoch(event.target.checked)} />
          Show epoch
        </label>
        <div className="controls">
          <button type="button" className="start" onClick={() => void exportClip()}>Export</button>
        </div>
      </section>
    </main>
  );
}
