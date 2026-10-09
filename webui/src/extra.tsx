import { useEffect, useState } from "react";

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
  ["4", "Samples", "Preview prompts. The full Samples tab is a later phase."],
  ["5", "Training", "Pick a preset and start."],
];

export function Phase2({
  tab,
  imageFolder,
  setImageFolder,
  queueCurrent,
}: {
  tab: string;
  imageFolder: string;
  setImageFolder: (path: string) => void;
  queueCurrent: (samples: Record<string, unknown>) => Promise<string>;
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

function QueuePanel({ queueCurrent }: { queueCurrent: (samples: Record<string, unknown>) => Promise<string> }) {
  const [items, setItems] = useState<Array<{ id: string; family: string; label: string }>>([]);
  const [error, setError] = useState("");
  const [prompts, setPrompts] = useState("A high quality photo");
  const [every, setEvery] = useState("");
  const [width, setWidth] = useState("768");
  const [height, setHeight] = useState("768");

  function reload() {
    fetch("/api/queue")
      .then((response) => response.json())
      .then((body) => setItems(body.items))
      .catch(() => setError("queue failed"));
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

  function move(index: number, delta: number) {
    const next = items.map((item) => item.id);
    const target = index + delta;
    if (target < 0 || target >= next.length) {
      return;
    }
    const [id] = next.splice(index, 1);
    next.splice(target, 0, id);
    void order(next);
  }

  const samples = {
    enabled: true,
    prompts: prompts.split("\n"),
    every,
    width,
    height,
  };

  return (
    <main>
      <section>
        <h2>Training queue</h2>
        <p className="help">One GPU job at a time. The next item starts when a training run finishes cleanly.</p>
        <div className="field">
          <label>
            Sample prompts
            <textarea value={prompts} onChange={(event) => setPrompts(event.target.value)} />
          </label>
        </div>
        <div className="field">
          <label>Every N epochs<input value={every} onChange={(event) => setEvery(event.target.value)} /></label>
        </div>
        <div className="controls">
          <label>Width<input value={width} onChange={(event) => setWidth(event.target.value)} /></label>
          <label>Height<input value={height} onChange={(event) => setHeight(event.target.value)} /></label>
        </div>
        <div className="controls">
          <button type="button" onClick={() => void queueCurrent(samples).then((message) => { setError(message); reload(); })}>Queue current training form</button>
          <button type="button" onClick={() => void fetch("/api/queue/import", { method: "POST" }).then(async (response) => {
            if (!response.ok) {
              setError(await readError(response));
              return;
            }
            const body = await response.json();
            setItems(body.items);
            setError(`Imported ${body.imported}, skipped ${body.skipped}.`);
          })}>Import desktop queue</button>
          <button type="button" onClick={() => void fetch("/api/queue/advance", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" }).then(async (response) => {
            if (!response.ok) {
              setError(await readError(response));
            }
            reload();
          })}>Start next</button>
        </div>
        {error ? <p className="error">{error}</p> : null}
        {items.map((item, index) => (
          <div key={item.id} className="controls">
            <span>{index + 1}. {item.label} · {item.family}</span>
            <button type="button" onClick={() => move(index, -1)}>Up</button>
            <button type="button" onClick={() => move(index, 1)}>Down</button>
            <button type="button" onClick={() => void fetch(`/api/queue/${item.id}`, { method: "DELETE" }).then(() => reload())}>Remove</button>
          </div>
        ))}
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
                {String(job.family)} {String(job.status)}{duration}{loss}
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
