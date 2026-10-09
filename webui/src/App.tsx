import { useEffect, useState } from "react";

const FAMILIES: { id: string; name: string }[] = [
  { id: "klein", name: "Klein 9B" },
  { id: "minimax", name: "MiniMax H3" },
  { id: "krea2", name: "Krea 2" },
  { id: "qwen_image21", name: "Qwen Image 2.1" },
  { id: "sdxl", name: "SDXL" },
  { id: "anima", name: "Anima" },
  { id: "zimage", name: "Z-Image Turbo" },
];

type ModelFile = { label?: string; role?: string; required?: boolean };
type Option = { key?: string; label?: string; kind?: string };
type Advanced = { dest?: string; flags?: string[] };

type Schema = {
  key: string;
  display_name?: string;
  model_files?: ModelFile[];
  presets?: unknown[];
  options?: Option[];
  lr_hint?: unknown;
  advanced?: Advanced[];
};

function presetName(preset: unknown): string {
  if (Array.isArray(preset) && typeof preset[0] === "string") {
    return preset[0];
  }
  return "";
}

function hintText(value: unknown): string {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join(", ");
  }
  if (value == null) {
    return "none";
  }
  return String(value);
}

export function App() {
  const [family, setFamily] = useState("qwen_image21");
  const [schema, setSchema] = useState<Schema | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setError("");
    setSchema(null);
    fetch(`/api/schema?family=${encodeURIComponent(family)}`)
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`schema request failed (${response.status})`);
        }
        return response.json() as Promise<Schema>;
      })
      .then((body) => {
        if (!cancelled) {
          setSchema(body);
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "schema request failed");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [family]);

  return (
    <main>
      <h1>Fizgig</h1>
      <label>
        Family
        <select value={family} onChange={(event) => setFamily(event.target.value)}>
          {FAMILIES.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      {error ? <p className="error">{error}</p> : null}
      {!error && !schema ? <p className="status">Loading schema…</p> : null}
      {schema ? (
        <>
          <p className="status">
            {schema.display_name ?? schema.key} ({schema.key})
          </p>
          <section>
            <h2>Model files</h2>
            <ul>
              {(schema.model_files ?? []).map((file) => (
                <li key={`${file.role ?? ""}-${file.label ?? ""}`}>
                  {file.label || file.role || "file"}
                  {file.required ? "" : <span className="meta"> optional</span>}
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h2>Presets</h2>
            <ul>
              {(schema.presets ?? []).map((preset) => (
                <li key={presetName(preset)}>{presetName(preset)}</li>
              ))}
            </ul>
          </section>
          <section>
            <h2>Options</h2>
            <ul>
              {(schema.options ?? []).map((option) => (
                <li key={option.key ?? option.label}>
                  {option.label || option.key}
                  {option.kind ? <span className="meta"> {option.kind}</span> : null}
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h2>Learning-rate hint</h2>
            <ul>
              <li>{hintText(schema.lr_hint)}</li>
            </ul>
          </section>
          <section>
            <h2>Advanced</h2>
            <ul>
              {(schema.advanced ?? []).map((option) => (
                <li key={option.dest ?? option.flags?.join(",")}>
                  {(option.flags ?? []).join(", ") || option.dest}
                </li>
              ))}
            </ul>
          </section>
        </>
      ) : null}
    </main>
  );
}
