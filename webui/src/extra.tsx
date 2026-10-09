import { useEffect, useRef, useState } from "react";

interface Notice {
  kind: string;
  message: string;
}

interface Entry {
  name: string;
  path: string;
  kind: string;
}

export function browserNotify(notice: Notice) {
  if (notice.kind !== "finished" && notice.kind !== "failed" && notice.kind !== "paused") {
    return;
  }
  if (typeof Notification === "undefined" || Notification.permission !== "granted") {
    return;
  }
  new Notification("Fizgig", { body: notice.message });
}

export function NotifyButton() {
  const supported = typeof Notification !== "undefined";
  const [permission, setPermission] = useState(supported ? Notification.permission : "denied");
  if (!supported) {
    return null;
  }
  if (permission === "granted") {
    return <span className="meta">Browser notifications on</span>;
  }
  return (
    <button
      type="button"
      onClick={() => {
        void Notification.requestPermission().then((next) => setPermission(next));
      }}
    >
      Enable browser notifications
    </button>
  );
}

export function BrowseButton({ select, onPick }: { select: "folder" | "file"; onPick: (path: string) => void }) {
  const [open, setOpen] = useState(false);
  const [path, setPath] = useState("");
  const [parent, setParent] = useState<string | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [error, setError] = useState("");

  function load(next: string) {
    setError("");
    const query = next ? `?path=${encodeURIComponent(next)}` : "";
    fetch(`/api/fs${query}`)
      .then(async (response) => {
        if (!response.ok) {
          throw new Error("That folder is outside the configured roots.");
        }
        return response.json() as Promise<{ path: string; parent: string | null; entries: Entry[] }>;
      })
      .then((body) => {
        setPath(body.path);
        setParent(body.parent);
        setEntries(body.entries);
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "browse failed"));
  }

  return (
    <>
      <button type="button" onClick={() => { setOpen(true); load(""); }}>Browse</button>
      {open ? (
        <div className="modal">
          <div className="sheet">
            <div className="controls">
              <button type="button" onClick={() => load(parent || "")} disabled={parent === null && path === ""}>Up</button>
              {select === "folder" && path ? (
                <button type="button" onClick={() => { onPick(path); setOpen(false); }}>Use this folder</button>
              ) : null}
              <button type="button" onClick={() => setOpen(false)}>Close</button>
            </div>
            <p className="status">{path || "Roots"}</p>
            {error ? <p className="error">{error}</p> : null}
            <ul className="listing">
              {entries.map((entry) => (
                <li key={entry.path}>
                  <button
                    type="button"
                    onClick={() => {
                      if (entry.kind === "dir") {
                        load(entry.path);
                      } else if (select === "file") {
                        onPick(entry.path);
                        setOpen(false);
                      }
                    }}
                  >
                    {entry.kind === "dir" ? "Folder" : entry.kind === "image" ? "Image" : "File"} · {entry.name}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}
    </>
  );
}

async function readError(response: Response): Promise<string> {
  const body = await response.json().catch(() => ({})) as { detail?: string; problems?: string[]; conflicts?: string[] };
  if (body.conflicts?.length) {
    return `already exists: ${body.conflicts.join(", ")}`;
  }
  if (body.problems?.length) {
    return body.problems.join("\n");
  }
  return body.detail || `request failed (${response.status})`;
}

const STEPS = [
  ["1", "Start", "Choose the training image folder."],
  ["2", "Image Prep", "Resize, convert to PNG, or face-crop. Optional."],
  ["3", "Captions", "Write a trigger word or generate captions."],
  ["4", "Samples", "Preview prompts, size, and how often they render."],
  ["5", "Training", "Pick a preset and start."],
];

export function sampleContext(values: Record<string, unknown>): Record<string, unknown> {
  const prompts = String(values.prompts ?? "");
  const samples: Record<string, unknown> = {
    enabled: values.enabled === undefined ? true : Boolean(values.enabled),
    prompts: prompts.split(/\r?\n/),
    every: String(values.every ?? ""),
    width: String(values.width ?? ""),
    height: String(values.height ?? ""),
    steps: String(values.steps ?? ""),
    cfg: String(values.cfg ?? ""),
    negative: String(values.negative ?? ""),
    seed: String(values.seed ?? ""),
    at_first: Boolean(values.at_first),
  };
  if ("checkpoint" in values) {
    samples.checkpoint = Boolean(values.checkpoint);
    const cache = String(values.checkpoint_cache ?? "auto");
    samples.checkpoint_cache = cache === "on" || cache === "off" ? cache : "auto";
  }
  const context: Record<string, unknown> = { samples };
  for (const key of ["FAMILY_TURBO_STRENGTH", "FAMILY_TURBO_STEPS", "FAMILY_TURBO_PACE"]) {
    if (key in values && String(values[key] ?? "").trim()) {
      context[key] = String(values[key]).trim();
    }
  }
  return context;
}

interface SampleForm {
  fields: Array<Record<string, unknown>>;
  wording: Record<string, string>;
  gaps: string[];
}

export function Phase2({
  tab,
  imageFolder,
  setImageFolder,
  queueCurrent,
  sampleForm,
  sampleValues,
  setSampleValues,
  onTab,
}: {
  tab: string;
  imageFolder: string;
  setImageFolder: (path: string) => void;
  queueCurrent: () => Promise<string>;
  sampleForm: SampleForm | null;
  sampleValues: Record<string, unknown>;
  setSampleValues: (values: Record<string, unknown>) => void;
  onTab: (name: string) => void;
}) {
  if (tab === "Start") {
    return <StartPanel imageFolder={imageFolder} setImageFolder={setImageFolder} />;
  }
  if (tab === "Captions") {
    return <CaptionsPanel folder={imageFolder} />;
  }
  if (tab === "Image Prep") {
    return <PrepPanel folder={imageFolder} />;
  }
  if (tab === "Samples") {
    return <SamplesPanel form={sampleForm} values={sampleValues} setValues={setSampleValues} />;
  }
  if (tab === "Profiler") {
    return <ProfilerPanel onRepair={() => onTab("Repair Studio")} />;
  }
  if (tab === "Extract") {
    return <ExtractPanel />;
  }
  if (tab === "Metadata") {
    return <MetadataPanel />;
  }
  if (tab === "Queue") {
    return <QueuePanel queueCurrent={queueCurrent} />;
  }
  if (tab === "History") {
    return <HistoryPanel />;
  }
  return <PrefsPanel />;
}

function StartPanel({ imageFolder, setImageFolder }: { imageFolder: string; setImageFolder: (path: string) => void }) {
  const [summary, setSummary] = useState({ images: 0, captions: 0, missing: 0, ready: false });
  const [error, setError] = useState("");
  const [drag, setDrag] = useState(false);

  function refresh(folder: string) {
    fetch(`/api/start`)
      .then((response) => response.json())
      .then((body) => {
        if (body.folder === folder || !folder) {
          setSummary(body);
        }
      })
      .catch(() => undefined);
  }

  useEffect(() => {
    refresh(imageFolder);
  }, [imageFolder]);

  async function choose(path: string) {
    setError("");
    const response = await fetch("/api/start", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ folder: path }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    const body = await response.json();
    setImageFolder(body.folder);
    setSummary(body);
  }

  async function send(files: FileList | File[], overwrite: boolean) {
    if (!imageFolder) {
      setError("Pick a training image folder first.");
      return;
    }
    const data = new FormData();
    data.set("dest", imageFolder);
    if (overwrite) {
      data.set("overwrite", "1");
    }
    for (const file of Array.from(files)) {
      if (file.name.toLowerCase().endsWith(".zip")) {
        data.set("archive", file);
      } else {
        data.append("files", file);
      }
    }
    const response = await fetch("/api/upload", { method: "POST", body: data });
    if (response.status === 409) {
      const body = await response.json() as { conflicts?: string[] };
      const names = (body.conflicts || []).join(", ");
      if (window.confirm(`Replace existing files?\n${names}`)) {
        await send(files, true);
      }
      return;
    }
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    setError("");
    refresh(imageFolder);
  }

  return (
    <main>
      <section>
        <h2>Training workflow</h2>
        {STEPS.map(([num, name, text]) => (
          <p key={num} className="status">{num}. {name} — {text}</p>
        ))}
      </section>
      <section>
        <h2>Training image folder</h2>
        <p className="help">Image Prep, Captions, and Training read this folder.</p>
        <div className="field">
          <label>
            Folder
            <input value={imageFolder} onChange={(event) => setImageFolder(event.target.value)} onBlur={() => void choose(imageFolder)} />
          </label>
          <BrowseButton select="folder" onPick={(path) => void choose(path)} />
        </div>
        {summary.ready ? (
          <p className="status">{summary.images} images, {summary.captions} captions, {summary.missing} missing captions</p>
        ) : <p className="status">No folder selected.</p>}
        {error ? <p className="error">{error}</p> : null}
        <div
          className={drag ? "drop on" : "drop"}
          onDragOver={(event) => { event.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDrag(false);
            void send(event.dataTransfer.files, false);
          }}
        >
          Drop images or a zip here
        </div>
      </section>
    </main>
  );
}

function CaptionsPanel({ folder }: { folder: string }) {
  const [fields, setFields] = useState<Array<Record<string, unknown>>>([]);
  const [gaps, setGaps] = useState<string[]>([]);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [items, setItems] = useState<Array<{ name: string; caption: string; url: string }>>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/captions/form")
      .then((response) => response.json())
      .then((body) => {
        setFields(body.fields);
        setGaps(body.gaps || []);
        const next: Record<string, unknown> = {};
        for (const field of body.fields) {
          next[String(field.key)] = field.default;
        }
        setValues(next);
      })
      .catch(() => setError("caption form failed"));
  }, []);

  function reload(q = query) {
    if (!folder) {
      setItems([]);
      return;
    }
    fetch(`/api/captions?folder=${encodeURIComponent(folder)}&q=${encodeURIComponent(q)}`)
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(await readError(response));
        }
        return response.json();
      })
      .then((body) => setItems(body.items))
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "list failed"));
  }

  useEffect(() => { reload(""); }, [folder]);

  async function run(staticCaption: boolean) {
    setError("");
    const response = await fetch(staticCaption ? "/api/captions/static" : "/api/captions/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...values, folder }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    if (staticCaption) {
      reload(query);
    }
  }

  async function save(name: string, text: string) {
    const response = await fetch("/api/captions", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ folder, name, text }),
    });
    if (!response.ok) {
      setError(await readError(response));
    }
  }

  return (
    <main>
      <section>
        <h2>Captioning settings</h2>
        <p className="status">Folder: {folder || "(set on the Start tab)"}</p>
        {fields.map((field) => {
          const key = String(field.key);
          const kind = String(field.kind);
          return (
            <div key={key} className="field">
              {kind === "bool" ? (
                <label>
                  <input type="checkbox" checked={Boolean(values[key])} onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.checked }))} />
                  {String(field.label)}
                </label>
              ) : (
                <label>
                  {String(field.label)}
                  {kind === "choice" && Array.isArray(field.choices) ? (
                    <select value={String(values[key] ?? "")} onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.value }))}>
                      {field.choices.map((choice) => <option key={String(choice)} value={String(choice)}>{String(choice)}</option>)}
                    </select>
                  ) : (
                    <input value={values[key] == null ? "" : String(values[key])} onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.value }))} />
                  )}
                </label>
              )}
              {field.help ? <p className="help">{String(field.help)}</p> : null}
            </div>
          );
        })}
        <div className="controls">
          <button type="button" onClick={() => void run(false)}>Caption all</button>
          <button type="button" onClick={() => void run(true)}>Static caption</button>
        </div>
        {gaps.length ? <p className="help">Desktop only for now: {gaps.join(", ")}.</p> : null}
        {error ? <p className="error">{error}</p> : null}
      </section>
      <section>
        <h2>Captions</h2>
        <div className="field">
          <label>
            Search
            <input value={query} onChange={(event) => { setQuery(event.target.value); reload(event.target.value); }} />
          </label>
        </div>
        {items.map((item) => (
          <div key={item.name} className="field">
            <img src={item.url} alt={item.name} />
            <label>
              {item.name}
              <textarea defaultValue={item.caption} onBlur={(event) => void save(item.name, event.target.value)} />
            </label>
          </div>
        ))}
      </section>
    </main>
  );
}

function PrepPanel({ folder }: { folder: string }) {
  const [form, setForm] = useState<{ modes: string[]; megapixels: string[]; faces: string[]; defaults: Record<string, unknown>; gaps: string[] } | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/prep/form")
      .then((response) => response.json())
      .then((body) => {
        setForm(body);
        setValues(body.defaults);
      })
      .catch(() => setError("prep form failed"));
  }, []);

  async function run() {
    setError("");
    const response = await fetch("/api/prep/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...values, folder }),
    });
    if (!response.ok) {
      setError(await readError(response));
    }
  }

  if (!form) {
    return <main>{error ? <p className="error">{error}</p> : <p className="status">Loading.</p>}</main>;
  }
  return (
    <main>
      <section>
        <h2>Image prep</h2>
        <p className="status">Folder: {folder || "(set on the Start tab)"}</p>
        <div className="field">
          <label>
            What to do
            <select value={String(values.mode ?? "")} onChange={(event) => setValues((current) => ({ ...current, mode: event.target.value }))}>
              {form.modes.map((mode) => <option key={mode} value={mode}>{mode}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>
            Target megapixels
            <select value={String(values.megapixels ?? "")} onChange={(event) => setValues((current) => ({ ...current, megapixels: event.target.value }))}>
              {form.megapixels.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>
            Face
            <select value={String(values.face ?? "")} onChange={(event) => setValues((current) => ({ ...current, face: event.target.value }))}>
              {form.faces.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>
            Padding %
            <input value={String(values.padding ?? "")} onChange={(event) => setValues((current) => ({ ...current, padding: event.target.value }))} />
          </label>
        </div>
        <div className="field">
          <label>
            <input type="checkbox" checked={Boolean(values.replace_originals)} onChange={(event) => setValues((current) => ({ ...current, replace_originals: event.target.checked }))} />
            Replace originals
          </label>
        </div>
        <button type="button" className="start" onClick={() => void run()}>Prepare images</button>
        {form.gaps.length ? <p className="help">Desktop only for now: {form.gaps.join(", ")}.</p> : null}
        {error ? <p className="error">{error}</p> : null}
      </section>
    </main>
  );
}

function QueuePanel({ queueCurrent }: { queueCurrent: () => Promise<string> }) {
  const [items, setItems] = useState<Array<{ id: string; family: string; label: string; device?: number }>>([]);
  const [devices, setDevices] = useState<number[]>([0]);
  const [error, setError] = useState("");

  function reload() {
    fetch("/api/queue")
      .then((response) => response.json())
      .then((body) => setItems(body.items))
      .catch(() => setError("queue failed"));
    fetch("/api/devices")
      .then((response) => response.json())
      .then((body) => {
        const raw = Array.isArray(body.devices) ? body.devices : [];
        const list = raw.filter((item: number) => Number.isInteger(item));
        setDevices(list.length ? list : [0]);
      })
      .catch(() => setDevices([0]));
  }

  useEffect(() => { reload(); }, []);

  async function order(ids: string[]) {
    const response = await fetch("/api/queue/order", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ids }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    setItems((await response.json()).items);
  }

  function move(device: number, index: number, delta: number) {
    const group = items.filter((item) => (item.device ?? 0) === device);
    const target = index + delta;
    if (target < 0 || target >= group.length) {
      return;
    }
    const nextGroup = group.slice();
    const [picked] = nextGroup.splice(index, 1);
    nextGroup.splice(target, 0, picked);
    let cursor = 0;
    const ids = items.map((item) => {
      if ((item.device ?? 0) !== device) {
        return item.id;
      }
      const id = nextGroup[cursor].id;
      cursor += 1;
      return id;
    });
    void order(ids);
  }

  const shown = new Set(devices);
  for (const item of items) {
    shown.add(item.device ?? 0);
  }
  const gpus = Array.from(shown).sort((left, right) => left - right);

  return (
    <main>
      <section>
        <h2>Training queue</h2>
        <p className="help">Each GPU has its own queue. A run on one GPU does not wait for another. The next item on a GPU starts when a training run on that GPU finishes cleanly. Sample settings come from the Samples tab.</p>
        <div className="controls">
          <button type="button" onClick={() => void queueCurrent().then((message) => { setError(message); reload(); })}>Queue current training form</button>
          <button type="button" onClick={() => void fetch("/api/queue/import", { method: "POST" }).then(async (response) => {
            if (!response.ok) {
              setError(await readError(response));
              return;
            }
            const body = await response.json();
            setItems(body.items);
            setError(`Imported ${body.imported}, skipped ${body.skipped}.`);
          })}>Import desktop queue</button>
        </div>
        {error ? <p className="error">{error}</p> : null}
        {gpus.map((gpu) => {
          const group = items.filter((item) => (item.device ?? 0) === gpu);
          return (
            <div key={gpu}>
              <h3>GPU {gpu}</h3>
              <div className="controls">
                <button type="button" onClick={() => void fetch("/api/queue/advance", {
                  method: "POST",
                  headers: { "content-type": "application/json" },
                  body: JSON.stringify({ device: gpu }),
                }).then(async (response) => {
                  if (!response.ok) {
                    setError(await readError(response));
                  }
                  reload();
                })}>Start next</button>
              </div>
              {group.map((item, index) => (
                <div key={item.id} className="controls">
                  <span>{index + 1}. {item.label} · {item.family}</span>
                  <button type="button" onClick={() => move(gpu, index, -1)}>Up</button>
                  <button type="button" onClick={() => move(gpu, index, 1)}>Down</button>
                  <button type="button" onClick={() => void fetch(`/api/queue/${item.id}`, { method: "DELETE" }).then(() => reload())}>Remove</button>
                </div>
              ))}
            </div>
          );
        })}
        {items.length === 0 ? <p className="status">The queue is empty.</p> : null}
      </section>
    </main>
  );
}

function HistoryPanel() {
  const [jobs, setJobs] = useState<Array<Record<string, unknown>>>([]);
  const [open, setOpen] = useState("");
  const [log, setLog] = useState("");
  const [samples, setSamples] = useState<Array<{ name: string; url: string }>>([]);

  useEffect(() => {
    fetch("/api/history").then((response) => response.json()).then((body) => setJobs(body.jobs)).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    fetch(`/api/jobs/${open}/log?offset=0`).then((response) => response.json()).then((body) => setLog(body.text || "")).catch(() => undefined);
    fetch(`/api/jobs/${open}/samples`).then((response) => response.json()).then((body) => setSamples(body.samples || [])).catch(() => setSamples([]));
  }, [open]);

  return (
    <main>
      <section>
        <h2>Job history</h2>
        <p className="help">Deleting a record removes the log. Training files stay in the output folder.</p>
        {jobs.map((job) => {
          const id = String(job.id);
          const loss = job.loss == null ? "" : ` · loss ${job.loss}`;
          const duration = job.duration == null ? "" : ` · ${job.duration}s`;
          return (
            <div key={id} className="controls">
              <button type="button" className={id === open ? "chip on" : "chip"} onClick={() => setOpen(id)}>
                {String(job.kind || "train")} · {String(job.family)} {String(job.status)}{duration}{loss}
              </button>
              <button type="button" onClick={() => void fetch(`/api/jobs/${id}`, { method: "DELETE" }).then(() => {
                setJobs((current) => current.filter((item) => item.id !== id));
                if (open === id) {
                  setOpen("");
                }
              })}>Delete record</button>
            </div>
          );
        })}
        {open ? (
          <>
            <pre className="log">{log || "No log."}</pre>
            <div className="gallery">
              {samples.map((sample) => <img key={sample.name} src={sample.url} alt={sample.name} />)}
            </div>
          </>
        ) : null}
      </section>
    </main>
  );
}

function PrefsPanel() {
  const [directories, setDirectories] = useState<Array<{ key: string; label: string; value: string }>>([]);
  const [families, setFamilies] = useState<Array<{ key: string; name: string; files: Array<Record<string, unknown>> }>>([]);
  const [secrets, setSecrets] = useState<Array<{ key: string; set: boolean }>>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState("");

  function load() {
    fetch("/api/prefs")
      .then((response) => response.json())
      .then((body) => {
        setDirectories(body.directories);
        setFamilies(body.families);
        setSecrets(body.secrets);
        const next: Record<string, string> = {};
        for (const row of body.directories) {
          next[row.key] = row.value;
        }
        for (const family of body.families) {
          for (const file of family.files) {
            next[String(file.key)] = String(file.value ?? "");
          }
        }
        setValues(next);
      })
      .catch(() => setError("preferences failed"));
  }

  useEffect(() => { load(); }, []);

  async function save() {
    setError("");
    const response = await fetch("/api/prefs", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ values }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    load();
  }

  return (
    <main>
      <section>
        <h2>Preferences</h2>
        <p className="help">Model paths and directories. Secrets stay on this machine.</p>
        {secrets.map((item) => (
          <p key={item.key} className="status">{item.key}: {item.set ? "set" : "not set"}</p>
        ))}
        {directories.map((row) => (
          <div key={row.key} className="field">
            <label>
              {row.label}
              <input value={values[row.key] ?? ""} onChange={(event) => setValues((current) => ({ ...current, [row.key]: event.target.value }))} />
            </label>
            <BrowseButton select="folder" onPick={(path) => setValues((current) => ({ ...current, [row.key]: path }))} />
          </div>
        ))}
        {families.map((family) => (
          <div key={family.key}>
            <h2>{family.name}</h2>
            {family.files.map((file) => {
              const key = String(file.key);
              return (
                <div key={key} className="field">
                  <label>
                    {String(file.label)}{file.required ? "" : " (optional)"}
                    <input value={values[key] ?? ""} onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.value }))} />
                  </label>
                  <BrowseButton select="file" onPick={(path) => setValues((current) => ({ ...current, [key]: path }))} />
                  {file.hint ? <p className="help">{String(file.hint)}</p> : null}
                  {file.download ? <p className="help"><a href={String(file.download)}>Download</a></p> : null}
                </div>
              );
            })}
          </div>
        ))}
        <button type="button" className="start" onClick={() => void save()}>Save preferences</button>
        {error ? <p className="error">{error}</p> : null}
      </section>
    </main>
  );
}

function fieldOff(field: Record<string, unknown>, values: Record<string, unknown>): boolean {
  if (field.disabled) {
    return true;
  }
  const gate = String(field.disabled_when || "");
  return Boolean(gate && values[gate]);
}

function SamplesPanel({
  form,
  values,
  setValues,
}: {
  form: SampleForm | null;
  values: Record<string, unknown>;
  setValues: (values: Record<string, unknown>) => void;
}) {
  if (!form) {
    return <main><p className="status">Loading.</p></main>;
  }
  return (
    <main>
      <section>
        <h2>Samples</h2>
        {form.wording.banner ? <p className="help">{form.wording.banner}</p> : null}
        {form.wording.advanced ? <p className="help">{form.wording.advanced}</p> : null}
        {form.fields.map((field) => {
          const key = String(field.key);
          const kind = String(field.kind);
          const off = fieldOff(field, values);
          return (
            <div key={key} className="field">
              {kind === "bool" ? (
                <label>
                  <input type="checkbox" checked={Boolean(values[key])} disabled={off} onChange={(event) => setValues({ ...values, [key]: event.target.checked })} />
                  {String(field.label)}
                </label>
              ) : (
                <label>
                  {String(field.label)}
                  {kind === "lines" ? (
                    <textarea value={String(values[key] ?? "")} disabled={off} onChange={(event) => setValues({ ...values, [key]: event.target.value })} />
                  ) : kind === "choice" && Array.isArray(field.choices) ? (
                    <select value={String(values[key] ?? "")} disabled={off} onChange={(event) => setValues({ ...values, [key]: event.target.value })}>
                      {field.choices.map((choice) => <option key={String(choice)} value={String(choice)}>{String(choice)}</option>)}
                    </select>
                  ) : (
                    <input value={String(values[key] ?? "")} disabled={off} onChange={(event) => setValues({ ...values, [key]: event.target.value })} />
                  )}
                </label>
              )}
              {field.help ? <p className="help">{String(field.help)}</p> : null}
            </div>
          );
        })}
        {form.gaps.length ? <p className="help">Desktop only for now: {form.gaps.join(", ")}.</p> : null}
      </section>
    </main>
  );
}

function ProfilerPanel({ onRepair }: { onRepair: () => void }) {
  const [form, setForm] = useState<Record<string, unknown> | null>(null);
  const [family, setFamily] = useState("");
  const [lora, setLora] = useState("");
  const [mode, setMode] = useState("quick");
  const [prompt, setPrompt] = useState("");
  const [classPrompt, setClassPrompt] = useState("");
  const [size, setSize] = useState("768");
  const [reports, setReports] = useState<Array<{ name: string; path: string; url: string }>>([]);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const poll = useRef<number | null>(null);

  useEffect(() => () => {
    if (poll.current != null) {
      window.clearInterval(poll.current);
    }
  }, []);

  function load(next: string) {
    fetch(`/api/profile/form?family=${encodeURIComponent(next)}`)
      .then((response) => response.json())
      .then((body) => {
        setForm(body);
        setFamily(String(body.family || ""));
        setMode(String(body.defaults?.mode || "quick"));
        setSize(String(body.defaults?.size || "768"));
      })
      .catch(() => setError("profiler form failed"));
  }

  useEffect(() => { load(""); }, []);

  useEffect(() => {
    let stop = false;
    async function tick() {
      const response = await fetch("/api/profiles");
      if (response.ok && !stop) {
        const body = await response.json();
        setReports(body.reports || []);
      }
      if (!stop) {
        window.setTimeout(tick, 2000);
      }
    }
    tick();
    return () => { stop = true; };
  }, []);

  async function run() {
    setError("");
    setReady(false);
    if (mode === "weights") {
      const response = await fetch("/api/profile/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ family, lora, mode }),
      });
      if (!response.ok) {
        setError(await readError(response));
      }
      return;
    }
    const response = await fetch("/api/profile/engine", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ family, lora, mode, prompt, class_prompt: classPrompt, size }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    const started = await response.json();
    if (poll.current != null) {
      window.clearInterval(poll.current);
    }
    poll.current = window.setInterval(async () => {
      const status = await fetch("/api/profile/engine");
      if (!status.ok) {
        return;
      }
      const body = await status.json();
      if (body.gen !== started.gen) {
        return;
      }
      if (body.status === "done") {
        if (poll.current != null) {
          window.clearInterval(poll.current);
        }
        setReady(true);
      }
    }, 500);
  }

  async function openRepair() {
    setError("");
    const response = await fetch("/api/profile/repair", { method: "POST" });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    sessionStorage.setItem("fizgig.repair.handoff", JSON.stringify(await response.json()));
    onRepair();
  }

  const families = (form?.families as Array<{ key: string; name: string }> | undefined) || [];
  const modes = (form?.modes as Array<{ id: string; label: string }> | undefined) || [];
  return (
    <main>
      <section>
        <h2>Profiler</h2>
        <p className="help">Weights reads the file. Quick and Thorough render on the engine.</p>
        <div className="field">
          <label>
            Family
            <select value={family} onChange={(event) => { setFamily(event.target.value); load(event.target.value); }}>
              {families.map((item) => <option key={item.key} value={item.key}>{item.name}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>
            LoRA file
            <input value={lora} onChange={(event) => setLora(event.target.value)} />
          </label>
          <BrowseButton select="file" onPick={setLora} />
        </div>
        <div className="field">
          <label>
            What to measure
            <select value={mode} onChange={(event) => setMode(event.target.value)}>
              {modes.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>
            Prompt
            <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} />
          </label>
        </div>
        <div className="field">
          <label>
            Bleed-check prompt
            <input value={classPrompt} onChange={(event) => setClassPrompt(event.target.value)} />
          </label>
        </div>
        <div className="field">
          <label>
            Size
            <select value={size} onChange={(event) => setSize(event.target.value)}>
              {((form?.sizes as string[] | undefined) || []).map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
        <button type="button" className="start" onClick={() => void run()}>Profile LoRA</button>
        <button type="button" disabled={!ready} onClick={() => void openRepair()}>Open in Repair Studio</button>
        {error ? <p className="error">{error}</p> : null}
      </section>
      <section>
        <h2>Reports</h2>
        {reports.map((report) => (
          <p key={report.path}><a href={report.url}>{report.name}</a></p>
        ))}
        {reports.length === 0 ? <p className="status">No reports yet.</p> : null}
      </section>
    </main>
  );
}

function ExtractPanel() {
  const [form, setForm] = useState<Record<string, unknown> | null>(null);
  const [family, setFamily] = useState("");
  const [source, setSource] = useState("");
  const [outputName, setOutputName] = useState("");
  const [preset, setPreset] = useState("");
  const [rank, setRank] = useState("4");
  const [blocks, setBlocks] = useState<Record<string, boolean>>({});
  const [error, setError] = useState("");

  function load(next: string) {
    fetch(`/api/extract/form?family=${encodeURIComponent(next)}`)
      .then((response) => response.json())
      .then((body) => {
        setForm(body);
        setFamily(String(body.family || ""));
        setRank(String(body.rank || "4"));
        const names = (body.presets as string[] | undefined) || [];
        setPreset(names[0] || "");
        setBlocks({});
      })
      .catch(() => setError("extract form failed"));
  }

  useEffect(() => { load(""); }, []);

  function suggest(nextSource: string, nextPreset: string, nextRank: string) {
    const base = nextSource.split(/[/\\]/).pop()?.replace(/\.safetensors$/i, "") || "";
    if (!base) {
      return;
    }
    const slug = nextPreset.toLowerCase().replaceAll("+", "_").replaceAll(" ", "_");
    setOutputName(`${base}_${slug}_r${nextRank}.safetensors`);
  }

  async function run() {
    setError("");
    const chosen = Object.entries(blocks).filter(([, on]) => on).map(([id]) => id);
    const response = await fetch("/api/extract/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ family, source, output_name: outputName, preset, blocks: chosen, rank }),
    });
    if (!response.ok) {
      setError(await readError(response));
    }
  }

  const families = (form?.families as Array<{ key: string; name: string }> | undefined) || [];
  const presets = (form?.presets as string[] | undefined) || [];
  const ranks = (form?.ranks as string[] | undefined) || [];
  const groups = (form?.groups as Array<{ label: string; blocks: Array<{ id: string; label: string }> }> | undefined) || [];
  return (
    <main>
      <section>
        <h2>Extract</h2>
        <p className="help">{String(form?.time_note || "")}</p>
        <div className="field">
          <label>
            Family
            <select value={family} onChange={(event) => { setFamily(event.target.value); load(event.target.value); }}>
              {families.map((item) => <option key={item.key} value={item.key}>{item.name}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>
            Source LoRA
            <input value={source} onChange={(event) => setSource(event.target.value)} />
          </label>
          <BrowseButton select="file" onPick={(path) => { setSource(path); suggest(path, preset, rank); }} />
        </div>
        <div className="field">
          <label>
            Output name
            <input value={outputName} onChange={(event) => setOutputName(event.target.value)} />
          </label>
        </div>
        {presets.length ? (
          <div className="field">
            <label>
              Preset
              <select value={preset} onChange={(event) => { setPreset(event.target.value); suggest(source, event.target.value, rank); }}>
                {presets.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            </label>
          </div>
        ) : null}
        {preset === "Custom" ? groups.map((group) => (
          <div key={group.label}>
            <p className="status">{group.label}</p>
            {group.blocks.map((block) => (
              <label key={block.id}>
                <input type="checkbox" checked={Boolean(blocks[block.id])} onChange={(event) => setBlocks({ ...blocks, [block.id]: event.target.checked })} />
                {block.label}
              </label>
            ))}
          </div>
        )) : null}
        <div className="field">
          <label>
            Target rank
            <select value={rank} onChange={(event) => { setRank(event.target.value); suggest(source, preset, event.target.value); }}>
              {ranks.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
        <button type="button" className="start" onClick={() => void run()}>Extract LoRA</button>
        {error ? <p className="error">{error}</p> : null}
      </section>
    </main>
  );
}

function MetadataPanel() {
  const [path, setPath] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({
    title: "", author: "", license: "", tags: "", trigger: "", usage_hint: "", description: "", thumbnail: "",
  });
  const [extra, setExtra] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  function take(body: Record<string, unknown>) {
    setPath(String(body.path || path));
    setFields({
      title: String(body.title || ""),
      author: String(body.author || ""),
      license: String(body.license || ""),
      tags: String(body.tags || ""),
      trigger: String(body.trigger || ""),
      usage_hint: String(body.usage_hint || ""),
      description: String(body.description || ""),
      thumbnail: String(body.thumbnail || ""),
    });
    setExtra((body.extra as Record<string, string>) || {});
  }

  async function load(next = path) {
    setError("");
    const response = await fetch(`/api/metadata?path=${encodeURIComponent(next)}`);
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    take(await response.json());
    setStatus("Loaded.");
  }

  async function save() {
    setError("");
    const response = await fetch("/api/metadata", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ path, ...fields, extra }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    take(await response.json());
    setStatus("Saved.");
  }

  const rows: Array<[string, string]> = [
    ["title", "Title"],
    ["author", "Author"],
    ["license", "License"],
    ["tags", "Tags"],
    ["trigger", "Trigger phrase"],
    ["usage_hint", "Usage hint"],
  ];
  return (
    <main>
      <section>
        <h2>Metadata</h2>
        <div className="field">
          <label>
            File
            <input value={path} onChange={(event) => setPath(event.target.value)} />
          </label>
          <BrowseButton select="file" onPick={(picked) => { setPath(picked); void load(picked); }} />
          <button type="button" onClick={() => void load()}>Load</button>
        </div>
        {rows.map(([key, label]) => (
          <div key={key} className="field">
            <label>
              {label}
              <input value={fields[key] || ""} onChange={(event) => setFields({ ...fields, [key]: event.target.value })} />
            </label>
          </div>
        ))}
        <div className="field">
          <label>
            Description
            <textarea value={fields.description || ""} onChange={(event) => setFields({ ...fields, description: event.target.value })} />
          </label>
        </div>
        <div className="field">
          <p className="status">Thumbnail</p>
          {fields.thumbnail.startsWith("data:image") ? <img src={fields.thumbnail} alt="" /> : <p className="help">(no thumbnail)</p>}
          <BrowseButton select="file" onPick={(picked) => setFields({ ...fields, thumbnail: picked })} />
          <button type="button" onClick={() => setFields({ ...fields, thumbnail: "" })}>Clear</button>
        </div>
        <p className="help">Other keys in the file are kept.</p>
        <button type="button" className="start" onClick={() => void save()}>Save</button>
        {status ? <p className="status">{status}</p> : null}
        {error ? <p className="error">{error}</p> : null}
      </section>
    </main>
  );
}
