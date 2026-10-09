import { useEffect, useState } from "react";
import { BrowseButton } from "./extra";

interface ConvertForm {
  ranks?: number[];
  default_ranks?: number[];
  name?: string;
  output_dir?: string;
}

function readError(response: Response): Promise<string> {
  return response.json().then(
    (body: { detail?: string; problems?: string[] }) =>
      body.detail || (body.problems || []).join("\n") || `request failed (${response.status})`,
    () => `request failed (${response.status})`,
  );
}

export function ConvertPanel() {
  const [ranks, setRanks] = useState<number[]>([8, 16, 32, 64, 128, 256]);
  const [picked, setPicked] = useState<number[]>([32, 64]);
  const [base, setBase] = useState("");
  const [tuned, setTuned] = useState("");
  const [name, setName] = useState("extracted");
  const [outputDir, setOutputDir] = useState("");
  const [error, setError] = useState("");
  const [jobId, setJobId] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetch("/api/convert/form")
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(await readError(response));
        }
        return response.json() as Promise<ConvertForm>;
      })
      .then((body) => {
        if (cancelled) {
          return;
        }
        if (body.ranks?.length) {
          setRanks(body.ranks);
        }
        if (body.default_ranks?.length) {
          setPicked(body.default_ranks);
        }
        setName(body.name || "extracted");
        setOutputDir(body.output_dir || "");
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "convert form failed");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!jobId) {
      return;
    }
    let stop = false;
    async function poll() {
      while (!stop) {
        const response = await fetch(`/api/jobs/${jobId}`);
        if (stop) {
          return;
        }
        if (!response.ok) {
          setError(await readError(response));
          return;
        }
        const body = await response.json() as { status?: string };
        const next = String(body.status || "");
        setStatus(next);
        if (next === "done" || next === "failed" || next === "stopped") {
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, 400));
      }
    }
    void poll();
    return () => {
      stop = true;
    };
  }, [jobId]);

  function toggle(rank: number) {
    setPicked((current) => (
      current.includes(rank) ? current.filter((item) => item !== rank) : [...current, rank]
    ));
  }

  async function run() {
    setError("");
    const response = await fetch("/api/convert/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ base, tuned, ranks: picked, name }),
    });
    if (!response.ok) {
      setError(await readError(response));
      return;
    }
    const body = await response.json() as { id?: string; status?: string };
    setJobId(String(body.id || ""));
    setStatus(String(body.status || ""));
  }

  return (
    <main>
      <section>
        <h2>Checkpoint to LoRA</h2>
        <div className="field">
          <label>
            Base checkpoint
            <input value={base} onChange={(event) => setBase(event.target.value)} />
          </label>
          <BrowseButton select="file" onPick={setBase} />
        </div>
        <div className="field">
          <label>
            Trained checkpoint
            <input value={tuned} onChange={(event) => setTuned(event.target.value)} />
          </label>
          <BrowseButton select="file" onPick={setTuned} />
        </div>
        <div className="controls">
          {ranks.map((rank) => (
            <label key={rank}>
              <input type="checkbox" checked={picked.includes(rank)} onChange={() => toggle(rank)} />
              {rank}
            </label>
          ))}
        </div>
        <div className="field">
          <label>
            Name
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </label>
        </div>
        <p className="meta">{outputDir || "Set the LoRA output folder in Preferences."}</p>
        <button type="button" className="start" onClick={() => void run()}>Extract LoRAs</button>
        {error ? <p className="error">{error}</p> : null}
        {jobId ? <p className="status">{jobId} {status}</p> : null}
      </section>
    </main>
  );
}
