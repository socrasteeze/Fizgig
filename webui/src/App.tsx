import { useEffect, useState } from "react";
import type { components } from "./api";
import { fieldVisible } from "./visibility";

const FAMILIES: { id: string; name: string }[] = [
  { id: "klein", name: "Klein 9B" },
  { id: "minimax", name: "MiniMax H3" },
  { id: "krea2", name: "Krea 2" },
  { id: "qwen_image21", name: "Qwen Image 2.1" },
  { id: "sdxl", name: "SDXL" },
  { id: "anima", name: "Anima" },
  { id: "zimage", name: "Z-Image Turbo" },
];

type Job = components["schemas"]["JobOut"];
type FormBody = components["schemas"]["FormOut"];
type System = components["schemas"]["SystemOut"];
type Memory = components["schemas"]["MemoryOut"];
type LogChunk = components["schemas"]["LogOut"];
type Sample = components["schemas"]["SampleItem"];
type Warning = components["schemas"]["WarningItem"];
type ProblemBody = components["schemas"]["ProblemsOut"];
type Conflict = components["schemas"]["ConflictOut"];

interface Field {
  key: string;
  label: string;
  help: string;
  kind: string;
  default: unknown;
  choices: string[] | null;
  section: string;
  when: string;
}

interface ModelRow {
  key: string;
  label: string;
  required: boolean;
}

interface Notice {
  id: string;
  kind: string;
  message: string;
}

function asField(raw: { [key: string]: unknown }): Field {
  return {
    key: String(raw.key ?? ""),
    label: String(raw.label ?? raw.key ?? ""),
    help: String(raw.help ?? ""),
    kind: String(raw.kind ?? "text"),
    default: raw.default,
    choices: Array.isArray(raw.choices) ? raw.choices.map((item) => String(item)) : null,
    section: String(raw.section ?? ""),
    when: String(raw.when ?? "always"),
  };
}

function asModel(raw: { [key: string]: unknown }): ModelRow {
  return {
    key: String(raw.key ?? ""),
    label: String(raw.label ?? raw.key ?? ""),
    required: Boolean(raw.required),
  };
}

function groups(fields: Field[]): { section: string; fields: Field[] }[] {
  const out: { section: string; fields: Field[] }[] = [];
  for (const field of fields) {
    const last = out[out.length - 1];
    if (!last || last.section !== field.section) {
      out.push({ section: field.section, fields: [field] });
    } else {
      last.fields.push(field);
    }
  }
  return out;
}

function gb(bytes: number): string {
  return (bytes / 1073741824).toFixed(1);
}

function Bar({ label, pair, from, to }: { label: string; pair?: Memory | null; from: string; to: string }) {
  if (!pair?.total) {
    return <div className="bar"><span>{label} unavailable</span></div>;
  }
  const frac = Math.max(0, Math.min(1, pair.used / pair.total));
  return (
    <div className="bar">
      <div className="bar-fill" style={{ width: `${frac * 100}%`, background: `linear-gradient(90deg, ${from}, ${to})` }} />
      <span>{label} {gb(pair.used)} / {gb(pair.total)} GB</span>
    </div>
  );
}

export function App() {
  const [family, setFamily] = useState("qwen_image21");
  const [form, setForm] = useState<FormBody | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [modelPaths, setModelPaths] = useState<Record<string, string>>({});
  const [imageFolder, setImageFolder] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<Warning[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState("");
  const [log, setLog] = useState("");
  const [samples, setSamples] = useState<Sample[]>([]);
  const [system, setSystem] = useState<System>({});
  const [notices, setNotices] = useState<Notice[]>([]);
  const [error, setError] = useState("");
  const [overrideOn, setOverrideOn] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [seed, setSeed] = useState("1234");
  const [width, setWidth] = useState("768");
  const [height, setHeight] = useState("768");

  const fields = (form?.fields ?? []).map(asField);
  const models = (form?.models ?? []).map(asModel);
  const job = jobs.find((item) => item.id === selected) ?? null;

  useEffect(() => {
    let cancelled = false;
    setError("");
    fetch(`/api/form?family=${encodeURIComponent(family)}`)
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`form request failed (${response.status})`);
        }
        return response.json() as Promise<FormBody>;
      })
      .then((body) => {
        if (cancelled) {
          return;
        }
        setForm(body);
        const next: Record<string, unknown> = {};
        for (const field of body.fields.map(asField)) {
          next[field.key] = field.default;
        }
        setValues(next);
        setModelPaths({});
        setImageFolder("");
        setProblems([]);
        setWarnings([]);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "form request failed");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [family]);

  useEffect(() => {
    fetch("/api/jobs")
      .then((response) => response.json())
      .then((body: { jobs: Job[] }) => {
        setJobs(body.jobs);
        const live = body.jobs.find((item) => item.status === "running" || item.status === "queued");
        setSelected((current) => current || (live ?? body.jobs[0])?.id || "");
      })
      .catch(() => undefined);
    fetch("/api/system")
      .then((response) => response.json())
      .then((body: System) => setSystem(body))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const source = new EventSource("/api/events");
    source.addEventListener("job", (event) => {
      const next = JSON.parse((event as MessageEvent).data) as Job;
      setJobs((current) => {
        const rest = current.filter((item) => item.id !== next.id);
        return [next, ...rest].sort((a, b) => (a.created < b.created ? 1 : -1));
      });
    });
    source.addEventListener("system", (event) => {
      setSystem(JSON.parse((event as MessageEvent).data) as System);
    });
    source.addEventListener("notice", (event) => {
      const notice = JSON.parse((event as MessageEvent).data) as Notice;
      setNotices((current) => [notice, ...current].slice(0, 6));
    });
    return () => source.close();
  }, []);

  useEffect(() => {
    if (!selected) {
      return;
    }
    let offset = 0;
    let text = "";
    let stop = false;
    async function tick() {
      const response = await fetch(`/api/jobs/${selected}/log?offset=${offset}`);
      if (response.ok) {
        const body = (await response.json()) as LogChunk;
        offset = body.next;
        if (body.text) {
          text = `${text}${body.text}`.split("\n").slice(-200).join("\n");
          setLog(text);
        }
      }
      if (!stop) {
        window.setTimeout(tick, 1000);
      }
    }
    setLog("");
    tick();
    return () => {
      stop = true;
    };
  }, [selected]);

  useEffect(() => {
    if (!selected) {
      return;
    }
    let stop = false;
    async function tick() {
      const response = await fetch(`/api/jobs/${selected}/samples`);
      if (response.ok) {
        const body = (await response.json()) as { samples: Sample[] };
        if (!stop) {
          setSamples(body.samples);
        }
      }
      if (!stop) {
        window.setTimeout(tick, 2000);
      }
    }
    tick();
    return () => {
      stop = true;
    };
  }, [selected]);

  function setValue(key: string, value: unknown) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  async function start(confirm: string[]) {
    setProblems([]);
    setWarnings([]);
    const hasFolder = fields.some((field) => field.key === "image_folder");
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        family,
        values,
        confirm,
        context: {
          models: modelPaths,
          image_folder: hasFolder ? values.image_folder : imageFolder,
        },
      }),
    });
    if (response.status === 422) {
      const body = (await response.json()) as ProblemBody;
      setProblems(body.problems);
      return;
    }
    if (response.status === 409) {
      const body = (await response.json()) as Conflict;
      if (body.warnings?.length) {
        setWarnings(body.warnings);
        return;
      }
      setProblems([body.detail || "the run was not started"]);
      return;
    }
    if (!response.ok) {
      setProblems([`start failed (${response.status})`]);
      return;
    }
    const created = (await response.json()) as Job;
    setJobs((current) => [created, ...current.filter((item) => item.id !== created.id)]);
    setSelected(created.id);
  }

  async function control(action: "pause" | "resume" | "stop") {
    if (!selected) {
      return;
    }
    await fetch(`/api/jobs/${selected}/${action}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    });
  }

  async function sendOverride(active: boolean) {
    if (!selected) {
      return;
    }
    await fetch(`/api/jobs/${selected}/override`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(active ? { prompt, seed, width, height } : { prompt: "" }),
    });
  }

  const fraction = job && job.total > 0 ? Math.max(0, Math.min(1, job.step / job.total)) : 0;

  return (
    <>
      <header className="top">
        <div className="top-title">
          <h1>Fizgig</h1>
          <div className="jobs">
            {jobs.map((item) => (
              <button
                key={item.id}
                type="button"
                className={item.id === selected ? "chip on" : "chip"}
                onClick={() => setSelected(item.id)}
              >
                {item.family} {item.status}
              </button>
            ))}
            {jobs.length === 0 ? <span className="meta">No jobs</span> : null}
          </div>
        </div>
        <div className="bars">
          <Bar label="VRAM" pair={system.vram} from="#3FB950" to="#E5534B" />
          <Bar label="RAM" pair={system.ram} from="#3B82F6" to="#EAC54F" />
        </div>
      </header>
      {notices.length > 0 ? (
        <div className="notices">
          {notices.map((notice, index) => (
            <button key={`${notice.id}-${index}`} type="button" className="notice" onClick={() => setNotices((current) => current.filter((_, at) => at !== index))}>
              {notice.message}
            </button>
          ))}
        </div>
      ) : null}
      <main>
        <label>
          Family
          <select value={family} onChange={(event) => setFamily(event.target.value)}>
            {FAMILIES.map((item) => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </select>
        </label>
        {error ? <p className="error">{error}</p> : null}
        {form ? (
          <>
            <p className="status">{form.display_name}</p>
            <div className="chips">
              {form.presets.map((preset) => {
                const name = String(preset.name ?? "");
                return (
                  <button
                    key={name}
                    type="button"
                    className="chip"
                    onClick={() => {
                      const next = preset.values;
                      if (next && typeof next === "object") {
                        setValues(next as Record<string, unknown>);
                      }
                    }}
                  >
                    {name}
                  </button>
                );
              })}
            </div>
            {groups(fields.filter((field) => fieldVisible(field.when, values))).map((group) => (
              <section key={group.section}>
                <h2>{group.section}</h2>
                {group.fields.map((field) => (
                  <div key={field.key} className="field">
                    {field.kind === "bool" ? (
                      <label>
                        <input
                          type="checkbox"
                          checked={Boolean(values[field.key])}
                          onChange={(event) => setValue(field.key, event.target.checked)}
                        />
                        {field.label}
                      </label>
                    ) : (
                      <label>
                        {field.label}
                        {field.kind === "choice" && field.choices ? (
                          <select value={String(values[field.key] ?? "")} onChange={(event) => setValue(field.key, event.target.value)}>
                            {field.choices.map((choice) => (
                              <option key={choice} value={choice}>{choice}</option>
                            ))}
                          </select>
                        ) : (
                          <input
                            value={values[field.key] == null ? "" : String(values[field.key])}
                            onChange={(event) => setValue(field.key, event.target.value)}
                          />
                        )}
                      </label>
                    )}
                    {field.help ? <p className="help">{field.help}</p> : null}
                  </div>
                ))}
              </section>
            ))}
            {!fields.some((field) => field.key === "image_folder") ? (
              <section>
                <h2>Dataset</h2>
                <div className="field">
                  <label>
                    Training image folder
                    <input value={imageFolder} onChange={(event) => setImageFolder(event.target.value)} />
                  </label>
                </div>
              </section>
            ) : null}
            {models.length > 0 ? (
              <section>
                <h2>Model files</h2>
                {models.map((model) => (
                  <div key={model.key} className="field">
                    <label>
                      {model.label}{model.required ? "" : " (optional)"}
                      <input
                        value={modelPaths[model.key] ?? ""}
                        onChange={(event) => setModelPaths((current) => ({ ...current, [model.key]: event.target.value }))}
                      />
                    </label>
                  </div>
                ))}
              </section>
            ) : null}
            <details className="advanced">
              <summary>Advanced</summary>
              {form.advanced.map((item) => {
                const dest = String(item.dest ?? "");
                const flags = Array.isArray(item.flags) ? item.flags.map(String).join(" ") : dest;
                const choices = Array.isArray(item.choices) ? item.choices.map(String) : null;
                return (
                  <div key={dest || flags} className="field">
                    <label>
                      {flags || dest}
                      {choices ? (
                        <select value={String(values[dest] ?? item.default ?? "")} onChange={(event) => setValue(dest, event.target.value)}>
                          {choices.map((choice) => (
                            <option key={choice} value={choice}>{choice}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          value={values[dest] == null ? String(item.default ?? "") : String(values[dest])}
                          onChange={(event) => setValue(dest, event.target.value)}
                        />
                      )}
                    </label>
                  </div>
                );
              })}
            </details>
            {problems.map((line) => <p key={line} className="error">{line}</p>)}
            {warnings.length > 0 ? (
              <div className="warn">
                {warnings.map((item) => <p key={item.code}>{item.message}</p>)}
                <button type="button" onClick={() => start(warnings.map((item) => item.code))}>Start anyway</button>
              </div>
            ) : null}
            <button type="button" className="start" onClick={() => start([])}>Start training</button>
          </>
        ) : null}

        <section className="monitor">
          <h2>Monitor</h2>
          {job ? (
            <>
              <p className="status">{job.status}{job.stage ? ` · ${job.stage}` : ""} · {job.step}/{job.total}{job.loss == null ? "" : ` · loss ${job.loss}`}</p>
              <div className="progress"><div style={{ width: `${fraction * 100}%` }} /></div>
              <div className="controls">
                <button type="button" onClick={() => control("pause")} disabled={job.status !== "running"}>Pause</button>
                <button type="button" onClick={() => control("resume")} disabled={job.status !== "paused"}>Resume</button>
                <button type="button" onClick={() => control("stop")} disabled={job.status !== "running" && job.status !== "queued"}>Stop</button>
              </div>
              <pre className="log">{log || "Waiting for log lines."}</pre>
              <div className="gallery">
                {samples.map((sample) => (
                  <img key={sample.name} src={sample.url} alt={sample.name} />
                ))}
              </div>
              <div className="field">
                <label>
                  <input
                    type="checkbox"
                    checked={overrideOn}
                    onChange={(event) => {
                      setOverrideOn(event.target.checked);
                      void sendOverride(event.target.checked && prompt.trim().length > 0);
                    }}
                  />
                  Override next sample
                </label>
                <label>
                  Prompt
                  <input value={prompt} onChange={(event) => setPrompt(event.target.value)} />
                </label>
                <label>
                  Seed
                  <input value={seed} onChange={(event) => setSeed(event.target.value)} />
                </label>
                <label>
                  Width
                  <input value={width} onChange={(event) => setWidth(event.target.value)} />
                </label>
                <label>
                  Height
                  <input value={height} onChange={(event) => setHeight(event.target.value)} />
                </label>
                <button type="button" onClick={() => void sendOverride(overrideOn)}>Apply override</button>
              </div>
            </>
          ) : (
            <p className="status">No job selected. A running job shows here after you reopen the page.</p>
          )}
        </section>
      </main>
    </>
  );
}
