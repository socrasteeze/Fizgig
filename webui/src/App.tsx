import { useEffect, useState } from "react";
import type { components } from "./api";
import { BrowseButton, browserNotify, NotifyButton, Phase2, sampleContext } from "./extra";
import { ConvertPanel } from "./convert";
import { ExplorerPanel } from "./explorer";
import { GizmoPanel } from "./gizmo";
import { RefmodPanel } from "./refmod";
import { RepairPanel } from "./repair";
import { RoyalePanel } from "./royale";
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
  windows: Record<string, string[]> | null;
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
    windows: raw.windows && typeof raw.windows === "object" ? raw.windows as Record<string, string[]> : null,
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

function withCurrentChoice(choices: string[] | null, current: string): string[] {
  const list = choices ?? [];
  if (current && !list.includes(current)) {
    return [current, ...list];
  }
  return list;
}

function areaWindow(fields: Field[], area: string): [string, string] | null {
  if (!area || area === "Custom") {
    return null;
  }
  const field = fields.find((item) => item.key === "FAMILY_TRAIN_AREA");
  const windows = field?.windows;
  if (windows && Object.prototype.hasOwnProperty.call(windows, area)) {
    const pair = windows[area];
    return [String(pair?.[0] ?? ""), String(pair?.[1] ?? "")];
  }
  if (area === "Style") {
    return ["0", "400"];
  }
  return ["", ""];
}

function fillTimesteps(next: Record<string, unknown>, fields: Field[], area: string, keep: Record<string, unknown> | null) {
  const pair = areaWindow(fields, area);
  if (!pair) {
    return;
  }
  if (!keep || !("MIN_TIMESTEP" in keep)) {
    next.MIN_TIMESTEP = pair[0];
  }
  if (!keep || !("MAX_TIMESTEP" in keep)) {
    next.MAX_TIMESTEP = pair[1];
  }
}

function mergePreset(base: Record<string, unknown>, overlay: Record<string, unknown>, fields: Field[]) {
  const next = { ...base, ...overlay };
  if ("FAMILY_TRAIN_AREA" in overlay) {
    fillTimesteps(next, fields, String(overlay.FAMILY_TRAIN_AREA ?? ""), overlay);
  }
  return next;
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
  const [warnFor, setWarnFor] = useState<"start" | "pause" | "resume" | "stop">("start");
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
  const [tab, setTab] = useState("Training");
  const [devices, setDevices] = useState<number[]>([0]);
  const [device, setDevice] = useState(0);
  const [sampleForm, setSampleForm] = useState<{ fields: Array<Record<string, unknown>>; wording: Record<string, string>; gaps: string[] } | null>(null);
  const [sampleValues, setSampleValues] = useState<Record<string, unknown>>({});
  const tabs = ["Training", "Start", "Captions", "Image Prep", "Samples", "Queue", "History", "Profiler", "Repair Studio", "RefMod Studio", "LoRA the Explorer", "LoRA Royale", "Extract", "Metadata", "Gizmo", "Checkpoint to LoRA", "Preferences"];

  const fields = (form?.fields ?? []).map(asField);
  const models = (form?.models ?? []).map(asModel);
  const job = jobs.find((item) => item.id === selected) ?? null;

  useEffect(() => {
    let cancelled = false;
    setError("");
    setModelPaths({});
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
        const loaded = body.fields.map(asField);
        const next: Record<string, unknown> = {};
        for (const field of loaded) {
          next[field.key] = field.default;
        }
        const first = body.presets[0];
        const overlay = first && first.values && typeof first.values === "object"
          ? first.values as Record<string, unknown>
          : null;
        setValues(overlay ? mergePreset(next, overlay, loaded) : next);
        setProblems([]);
        setWarnings([]);
        fetch("/api/prefs")
          .then((response) => (response.ok ? response.json() : null))
          .then((prefs: { families?: Array<{ key?: string; files?: Array<{ key?: string; value?: unknown }> }> } | null) => {
            if (cancelled || !prefs) {
              return;
            }
            const section = (prefs.families || []).find((item) => item.key === family);
            const paths: Record<string, string> = {};
            for (const file of section?.files || []) {
              const key = String(file.key ?? "");
              const value = String(file.value ?? "").trim();
              if (key && value) {
                paths[key] = value;
              }
            }
            setModelPaths(paths);
          })
          .catch(() => undefined);
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
    let cancelled = false;
    fetch(`/api/samples/form?family=${encodeURIComponent(family)}`)
      .then((response) => response.json())
      .then((body) => {
        if (cancelled) {
          return;
        }
        const next: Record<string, unknown> = {};
        for (const field of body.fields || []) {
          next[String(field.key)] = field.default;
        }
        setSampleForm({ fields: body.fields || [], wording: body.wording || {}, gaps: body.gaps || [] });
        setSampleValues(next);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [family]);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/devices")
      .then((response) => {
        if (!response.ok) {
          throw new Error("devices failed");
        }
        return response.json() as Promise<{ devices?: unknown }>;
      })
      .then((body) => {
        if (cancelled) {
          return;
        }
        const raw = Array.isArray(body.devices) ? body.devices : [];
        const list = raw.filter((item): item is number => Number.isInteger(item));
        setDevices(list.length ? list : [0]);
      })
      .catch(() => {
        if (!cancelled) {
          setDevices([0]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
    fetch("/api/start")
      .then((response) => response.json())
      .then((body: { folder?: string }) => {
        if (body.folder) {
          setImageFolder(body.folder);
        }
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    let source: EventSource | null = null;
    let timer = 0;
    let stop = false;

    function applyJobs(body: { jobs: Job[] }) {
      setJobs(body.jobs);
      const live = body.jobs.find((item) => item.status === "running" || item.status === "queued");
      setSelected((current) => current || (live ?? body.jobs[0])?.id || "");
    }

    function open() {
      const next = new EventSource("/api/events");
      source = next;
      next.addEventListener("job", (event) => {
        const job = JSON.parse((event as MessageEvent).data) as Job;
        setJobs((current) => {
          const rest = current.filter((item) => item.id !== job.id);
          return [job, ...rest].sort((a, b) => (a.created < b.created ? 1 : -1));
        });
      });
      next.addEventListener("system", (event) => {
        setSystem(JSON.parse((event as MessageEvent).data) as System);
      });
      next.addEventListener("notice", (event) => {
        const notice = JSON.parse((event as MessageEvent).data) as Notice;
        setNotices((current) => [notice, ...current].slice(0, 6));
        browserNotify(notice);
      });
      next.onerror = () => {
        if (stop || next.readyState !== EventSource.CLOSED) {
          return;
        }
        next.onerror = null;
        next.close();
        if (source === next) {
          source = null;
        }
        timer = window.setTimeout(() => {
          if (stop) {
            return;
          }
          fetch("/api/jobs")
            .then((response) => response.json())
            .then((body: { jobs: Job[] }) => {
              if (!stop) {
                applyJobs(body);
              }
            })
            .catch(() => undefined);
          open();
        }, 2000);
      };
    }

    open();
    return () => {
      stop = true;
      window.clearTimeout(timer);
      if (source) {
        source.onerror = null;
        source.close();
      }
    };
  }, []);

  useEffect(() => {
    if (!selected) {
      return;
    }
    let offset = 0;
    let text = "";
    let stop = false;
    let timer = 0;
    async function tick() {
      try {
        const response = await fetch(`/api/jobs/${selected}/log?offset=${offset}`);
        if (response.ok) {
          const body = (await response.json()) as LogChunk;
          offset = body.next;
          if (body.text) {
            text = `${text}${body.text}`.split("\n").slice(-200).join("\n");
            if (!stop) {
              setLog(text);
            }
          }
        }
      } catch {
        // keep polling after one failed fetch
      }
      if (!stop) {
        timer = window.setTimeout(tick, 1000);
      }
    }
    setLog("");
    tick();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [selected]);

  useEffect(() => {
    if (!selected) {
      return;
    }
    let stop = false;
    let timer = 0;
    async function tick() {
      try {
        const response = await fetch(`/api/jobs/${selected}/samples`);
        if (response.ok) {
          const body = (await response.json()) as { samples: Sample[] };
          if (!stop) {
            setSamples((body.samples || []).slice(-48));
          }
        }
      } catch {
        // keep polling after one failed fetch
      }
      if (!stop) {
        timer = window.setTimeout(tick, 2000);
      }
    }
    tick();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [selected]);

  function setValue(key: string, value: unknown) {
    setValues((current) => {
      const next = { ...current, [key]: value };
      if (key === "FAMILY_TRAIN_AREA") {
        fillTimesteps(next, fields, String(value ?? ""), null);
      }
      return next;
    });
    if (key === "image_folder") {
      setImageFolder(String(value ?? ""));
    }
  }

  function rememberFolder(path: string) {
    setImageFolder(path);
    void fetch("/api/start", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ folder: path }),
    });
  }

  function samplePayload(): Record<string, unknown> {
    if (!sampleForm) {
      return { samples: { enabled: true, prompts: ["A high quality photo"] } };
    }
    return sampleContext(sampleValues);
  }

  async function queueCurrent(): Promise<string> {
    const hasFolder = fields.some((field) => field.key === "image_folder");
    const folder = String((hasFolder ? values.image_folder : "") || imageFolder || "");
    const response = await fetch("/api/queue", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        family,
        device,
        values: hasFolder ? { ...values, image_folder: folder } : values,
        context: { models: modelPaths, image_folder: folder, ...samplePayload() },
      }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({})) as { detail?: string; problems?: string[] };
      return body.problems?.join("\n") || body.detail || `queue failed (${response.status})`;
    }
    return "";
  }

  async function start(confirm: string[]) {
    setProblems([]);
    setWarnings([]);
    const hasFolder = fields.some((field) => field.key === "image_folder");
    const folder = String((hasFolder ? values.image_folder : "") || imageFolder || "");
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        family,
        device,
        values: hasFolder ? { ...values, image_folder: folder } : values,
        confirm,
        context: {
          models: modelPaths,
          image_folder: folder,
          ...samplePayload(),
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
        setWarnFor("start");
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

  async function control(action: "pause" | "resume" | "stop", confirm: string[] = []) {
    if (!selected) {
      return;
    }
    if (!confirm.length) {
      setProblems([]);
      setWarnings([]);
    }
    let response: Response;
    try {
      response = await fetch(`/api/jobs/${selected}/${action}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(action === "resume" ? { confirm } : {}),
      });
    } catch {
      setProblems([`${action} failed`]);
      return;
    }
    if (response.status === 422) {
      const body = (await response.json().catch(() => ({}))) as ProblemBody;
      setWarnings([]);
      setProblems(body.problems?.length ? body.problems : [`${action} was refused`]);
      return;
    }
    if (response.status === 409) {
      const body = (await response.json().catch(() => ({}))) as Conflict;
      if (body.warnings?.length) {
        setWarnFor(action);
        setProblems([]);
        setWarnings(body.warnings);
        return;
      }
      setWarnings([]);
      setProblems([body.detail || `${action} was refused`]);
      return;
    }
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { detail?: string; problems?: string[] };
      setProblems(body.problems?.length ? body.problems : [body.detail || `${action} failed (${response.status})`]);
      return;
    }
    setProblems([]);
    setWarnings([]);
  }

  function confirmWarnings() {
    const codes = warnings.map((item) => item.code);
    if (warnFor === "start") {
      void start(codes);
      return;
    }
    void control(warnFor, codes);
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
          <NotifyButton />
        </div>
      </header>
      <nav className="tabs">
        {tabs.map((name) => (
          <button key={name} type="button" className={tab === name ? "chip on" : "chip"} onClick={() => setTab(name)}>{name}</button>
        ))}
      </nav>
      {notices.length > 0 ? (
        <div className="notices">
          {notices.map((notice, index) => (
            <button key={`${notice.id}-${index}`} type="button" className="notice" onClick={() => setNotices((current) => current.filter((_, at) => at !== index))}>
              {notice.message}
            </button>
          ))}
        </div>
      ) : null}
      {tab === "Repair Studio" ? (
        <RepairPanel />
      ) : tab === "RefMod Studio" ? (
        <RefmodPanel />
      ) : tab === "LoRA the Explorer" ? (
        <ExplorerPanel />
      ) : tab === "LoRA Royale" ? (
        <RoyalePanel />
      ) : tab === "Gizmo" ? (
        <GizmoPanel />
      ) : tab === "Checkpoint to LoRA" ? (
        <ConvertPanel />
      ) : tab !== "Training" ? (
        <Phase2 tab={tab} imageFolder={imageFolder} setImageFolder={rememberFolder} queueCurrent={queueCurrent} sampleForm={sampleForm} sampleValues={sampleValues} setSampleValues={setSampleValues} onTab={setTab} />
      ) : (
      <main>
        <label>
          Family
          <select value={family} onChange={(event) => setFamily(event.target.value)}>
            {FAMILIES.map((item) => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </select>
        </label>
        <label>
          GPU
          <select value={device} onChange={(event) => setDevice(Number(event.target.value))}>
            {devices.map((item) => (
              <option key={item} value={item}>{item}</option>
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
                      const overlay = preset.values;
                      if (overlay && typeof overlay === "object") {
                        setValues((current) => mergePreset(current, overlay as Record<string, unknown>, fields));
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
                            {withCurrentChoice(field.choices, String(values[field.key] ?? "")).map((choice) => (
                              <option key={choice} value={choice}>{choice}</option>
                            ))}
                          </select>
                        ) : (
                          <input
                            value={values[field.key] == null ? "" : String(values[field.key])}
                            onChange={(event) => setValue(field.key, event.target.value)}
                            onBlur={() => {
                              if (field.key === "image_folder") {
                                rememberFolder(String(values[field.key] ?? ""));
                              }
                            }}
                          />
                        )}
                        {field.kind === "folder" || field.kind === "path" ? (
                          <BrowseButton
                            select={field.kind === "path" ? "file" : "folder"}
                            onPick={(path) => {
                              setValue(field.key, path);
                              if (field.key === "image_folder") {
                                rememberFolder(path);
                              }
                            }}
                          />
                        ) : null}
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
                    <input value={imageFolder} onChange={(event) => setImageFolder(event.target.value)} onBlur={() => rememberFolder(imageFolder)} />
                  </label>
                  <BrowseButton select="folder" onPick={(path) => rememberFolder(path)} />
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
                    <BrowseButton select="file" onPick={(path) => setModelPaths((current) => ({ ...current, [model.key]: path }))} />
                  </div>
                ))}
              </section>
            ) : null}
            <details className="advanced">
              <summary>Advanced</summary>
              <p className="help">Reference only. These are not sent.</p>
              {form.advanced.map((item) => {
                const dest = String(item.dest ?? "");
                const flags = Array.isArray(item.flags) ? item.flags.map(String).join(" ") : dest;
                const choices = Array.isArray(item.choices) ? item.choices.map(String) : null;
                const shown = item.default == null ? "" : String(item.default);
                return (
                  <div key={dest || flags} className="field">
                    <label>
                      {flags || dest}
                      {choices ? (
                        <select value={shown} disabled>
                          {withCurrentChoice(choices, shown).map((choice) => (
                            <option key={choice} value={choice}>{choice}</option>
                          ))}
                        </select>
                      ) : (
                        <input value={shown} disabled readOnly />
                      )}
                    </label>
                  </div>
                );
              })}
            </details>
            {problems.map((line) => <p key={line} className="error">{line}</p>)}
            {warnFor === "start" && warnings.length > 0 ? (
              <div className="warn">
                {warnings.map((item) => <p key={item.code}>{item.message}</p>)}
                <button type="button" onClick={confirmWarnings}>Start anyway</button>
              </div>
            ) : null}
            <div className="controls">
              <button type="button" className="start" onClick={() => start([])}>Start training</button>
              <button type="button" onClick={() => void queueCurrent().then((message) => { if (message) setProblems([message]); })}>Add to queue</button>
            </div>
          </>
        ) : null}

        <section className="monitor">
          <h2>Monitor</h2>
          {job ? (
            <>
              <p className="status">{job.status}{job.stage ? ` · ${job.stage}` : ""} · {job.step}/{job.total}{job.loss == null ? "" : ` · loss ${job.loss}`}{job.device == null ? "" : ` · GPU ${job.device}`}</p>
              <div className="progress"><div style={{ width: `${fraction * 100}%` }} /></div>
              <div className="controls">
                <button type="button" onClick={() => void control("pause")} disabled={job.status !== "running"}>Pause</button>
                <button type="button" onClick={() => void control("resume")} disabled={job.status !== "paused"}>Resume</button>
                <button type="button" onClick={() => void control("stop")} disabled={job.status !== "running" && job.status !== "queued"}>Stop</button>
              </div>
              {problems.map((line) => <p key={line} className="error">{line}</p>)}
              {warnFor !== "start" && warnings.length > 0 ? (
                <div className="warn">
                  {warnings.map((item) => <p key={item.code}>{item.message}</p>)}
                  <button type="button" onClick={confirmWarnings}>{warnFor === "resume" ? "Resume anyway" : "Continue anyway"}</button>
                </div>
              ) : null}
              <pre className="log">{log || "Waiting for log lines."}</pre>
              <div className="gallery">
                {samples.slice(-48).map((sample) => (
                  <img key={sample.name} src={sample.url} alt={sample.name} loading="lazy" />
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
      )}
    </>
  );
}
