/** Hide a field from the `when` text the form serves. Dataset-content rules stay visible. */
export function fieldVisible(when: string, values: Record<string, unknown>): boolean {
  if (!when || when === "always") {
    return true;
  }
  const kind = String(values.kind ?? "");
  const network = String(values.NETWORK_TYPE ?? "");
  const source = String(values.FAMILY_SLIDER_SOURCE ?? "");
  return when.split(";").every((part) => one(part.trim(), kind, network, source, values));
}

function one(part: string, kind: string, network: string, source: string, values: Record<string, unknown>): boolean {
  if (!part || part === "always" || part.startsWith("shown even") || part.startsWith("sent ") || part.startsWith("while ")) {
    return true;
  }
  if (part === "Adaptive LR is on") {
    return Boolean(values.ADAPTIVE_LR);
  }
  if (part === "Network Type is LoRA") {
    return network.startsWith("LoRA");
  }
  if (part === "Network Type is LoKR") {
    return network.startsWith("LoKR");
  }
  if (part === "Kind of training is not Fine-tune") {
    return !kind.startsWith("Fine-tune");
  }
  if (part === "Kind of training is Fine-tune") {
    return kind.startsWith("Fine-tune");
  }
  if (part === "Kind of training is Edit") {
    return kind.startsWith("Edit");
  }
  if (part === "Kind of training is Slider") {
    return kind.startsWith("Slider");
  }
  if (part === "Kind of training is Standard LoRA") {
    return kind.startsWith("Standard");
  }
  if (part === "Kind of training is Edit, or Slider with photo pairs") {
    return kind.startsWith("Edit") || (kind.startsWith("Slider") && source.startsWith("Photo"));
  }
  if (part === "Kind of training is Slider and the source is Photo pairs") {
    return kind.startsWith("Slider") && source.startsWith("Photo");
  }
  if (part === "Kind of training is Slider and the source is Prompts") {
    return kind.startsWith("Slider") && source.startsWith("Prompt");
  }
  if (part === "Multi Concept is on") {
    return Boolean(values.FAMILY_MULTICONCEPT);
  }
  if (part === "Model Area to Train is Custom") {
    return values.FAMILY_TRAIN_AREA === "Custom";
  }
  if (part.startsWith("the dataset contains") || part.startsWith("the dataset mixes")) {
    return true;
  }
  if (part.includes("Batch Size is 1")) {
    if (part.includes("automagic3") && String(values.OPTIMIZER_TYPE ?? "") === "automagic3") {
      return false;
    }
    return String(values.batch_size ?? "1") === "1";
  }
  return true;
}
