const TRANSFORMERS_URL = "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.7.2";
const TF_URL = "https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.22.0/dist/tf.min.js";
const POSE_URL = "https://cdn.jsdelivr.net/npm/@tensorflow-models/pose-detection@2.1.3/dist/pose-detection.min.js";
const DEPTH_MODEL = "onnx-community/depth-anything-v2-small";

function loadScript(url) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = url;
    script.crossOrigin = "anonymous";
    script.onload = resolve;
    script.onerror = () => reject(new Error(`Failed to load ${url}`));
    document.head.appendChild(script);
  });
}

async function createPoseDetector() {
  await loadScript(TF_URL);
  await loadScript(POSE_URL);
  const tf = globalThis.tf;
  const poseDetection = globalThis.poseDetection;
  if (!tf || !poseDetection) throw new Error("TensorFlow.js pose runtime did not initialize");
  try {
    await tf.setBackend("webgl");
  } catch {
    await tf.setBackend("cpu");
  }
  await tf.ready();
  return poseDetection.createDetector(poseDetection.SupportedModels.MoveNet, {
    modelType: poseDetection.movenet.modelType.SINGLEPOSE_LIGHTNING,
    enableSmoothing: false,
  });
}

async function createDepthEstimator() {
  const { pipeline, RawImage } = await import(TRANSFORMERS_URL);
  const preferred = "gpu" in navigator ? { device: "webgpu", dtype: "q4f16" } : {};
  try {
    return {
      estimator: await pipeline("depth-estimation", DEPTH_MODEL, preferred),
      RawImage,
      device: preferred.device || "wasm",
    };
  } catch (error) {
    if (!preferred.device) throw error;
    return {
      estimator: await pipeline("depth-estimation", DEPTH_MODEL, { dtype: "q8" }),
      RawImage,
      device: "wasm",
    };
  }
}

function sampleDepth(depthImage, x, y) {
  const px = Math.max(0, Math.min(depthImage.width - 1, Math.round(x * (depthImage.width - 1))));
  const py = Math.max(0, Math.min(depthImage.height - 1, Math.round(y * (depthImage.height - 1))));
  const channels = depthImage.channels || 1;
  const center = Number(depthImage.data[(py * depthImage.width + px) * channels]) / 255;
  const neighbors = [];
  for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
    for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
      const nx = Math.max(0, Math.min(depthImage.width - 1, px + offsetX));
      const ny = Math.max(0, Math.min(depthImage.height - 1, py + offsetY));
      neighbors.push(Number(depthImage.data[(ny * depthImage.width + nx) * channels]) / 255);
    }
  }
  const mean = neighbors.reduce((sum, value) => sum + value, 0) / neighbors.length;
  const variance = neighbors.reduce((sum, value) => sum + (value - mean) ** 2, 0) / neighbors.length;
  return { depth: center, confidence: Math.max(0, Math.min(1, 1 - Math.sqrt(variance) * 4)) };
}

export async function createDepthPoseRuntime() {
  const [poseDetector, depthRuntime] = await Promise.all([
    createPoseDetector(),
    createDepthEstimator(),
  ]);
  return {
    async infer({ request, image }) {
      const poses = await poseDetector.estimatePoses(image, { maxPoses: 1, flipHorizontal: false });
      const rawImage = new depthRuntime.RawImage(image.data, image.width, image.height, 4);
      const depthResult = await depthRuntime.estimator(rawImage);
      const depthImage = depthResult.depth;
      const requested = new Set(request.requested_labels);
      const keypoints = poses[0]?.keypoints || [];
      const joints = keypoints
        .filter((point) => point.name && requested.has(point.name))
        .map((point) => {
          const x = Math.max(0, Math.min(1, point.x / request.width));
          const y = Math.max(0, Math.min(1, point.y / request.height));
          const sampled = sampleDepth(depthImage, x, y);
          return {
            label: point.name,
            x,
            y,
            confidence: Math.max(0, Math.min(1, point.score || 0)),
            depth_confidence: sampled.confidence,
            depth: sampled.depth,
          };
        });
      return {
        schema_version: "1.0",
        frame_number: request.frame_number,
        width: request.width,
        height: request.height,
        pose_model: "MoveNet-SinglePose-Lightning",
        depth_model: "onnx-community/depth-anything-v2-small",
        runtime: `browser-${depthRuntime.device}+tfjs-${globalThis.tf.getBackend()}`,
        joints,
      };
    },
  };
}
