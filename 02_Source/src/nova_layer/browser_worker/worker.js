const providerInput = document.querySelector("#provider");
const startButton = document.querySelector("#start");
const status = document.querySelector("#status");
const token = new URLSearchParams(location.search).get("token") || "";
let stopped = false;

providerInput.value = localStorage.getItem("nova.depthPoseProvider") ||
  "/providers/movenet-depth-anything-v2.js";

function setStatus(message, error = false) {
  status.textContent = message;
  status.style.color = error ? "#ff9a9a" : "#a9d6b5";
}

function assertLoopbackModule(url) {
  const parsed = new URL(url, location.href);
  if (parsed.protocol !== "http:" || !["127.0.0.1", "localhost", "::1"].includes(parsed.hostname)) {
    throw new Error("Provider module must use HTTP on a loopback host.");
  }
  return parsed.href;
}

function decodeRgb(request) {
  const binary = atob(request.image.data);
  const expected = request.width * request.height * 3;
  if (binary.length !== expected) throw new Error("RGB byte length mismatch");
  const rgba = new Uint8ClampedArray(request.width * request.height * 4);
  for (let source = 0, target = 0; source < binary.length; source += 3, target += 4) {
    rgba[target] = binary.charCodeAt(source);
    rgba[target + 1] = binary.charCodeAt(source + 1);
    rgba[target + 2] = binary.charCodeAt(source + 2);
    rgba[target + 3] = 255;
  }
  return new ImageData(rgba, request.width, request.height);
}

async function poll(runtime) {
  while (!stopped) {
    const response = await fetch("/api/worker/jobs/next", {
      headers: { "X-NOVA-Bridge-Token": token },
      cache: "no-store",
    });
    if (response.status === 204) continue;
    if (!response.ok) throw new Error(`Job poll failed: HTTP ${response.status}`);
    const job = await response.json();
    setStatus(`Processing frame ${job.request.frame_number}…`);
    const image = decodeRgb(job.request);
    const result = await runtime.infer({ request: job.request, image });
    const completion = await fetch(`/api/worker/jobs/${job.job_id}/result`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-NOVA-Bridge-Token": token },
      body: JSON.stringify(result),
    });
    if (!completion.ok) {
      const detail = await completion.text();
      throw new Error(`Result rejected: HTTP ${completion.status} ${detail}`);
    }
    setStatus(`Frame ${job.request.frame_number} completed. Waiting for NOVA…`);
  }
}

startButton.addEventListener("click", async () => {
  try {
    if (!token) throw new Error("Open the worker with the token URL printed by the broker.");
    const moduleUrl = assertLoopbackModule(providerInput.value.trim());
    startButton.disabled = true;
    setStatus("Loading licensed provider…");
    const provider = await import(moduleUrl);
    if (typeof provider.createDepthPoseRuntime !== "function") {
      throw new Error("Provider must export createDepthPoseRuntime().");
    }
    const runtime = await provider.createDepthPoseRuntime();
    if (!runtime || typeof runtime.infer !== "function") {
      throw new Error("Provider runtime must implement infer({ request, image }).");
    }
    localStorage.setItem("nova.depthPoseProvider", moduleUrl);
    setStatus("Provider ready. Waiting for NOVA…");
    await poll(runtime);
  } catch (error) {
    startButton.disabled = false;
    setStatus(error instanceof Error ? error.message : String(error), true);
  }
});
