# NOVA Browser Depth/Pose Provider Contract 1.0

A provider is an ES module served over loopback HTTP. It must export:

```js
export async function createDepthPoseRuntime() {
  return {
    async infer({ request, image }) {
      // Return a depth_pose_frame_v1 object.
    },
  };
}
```

`request` conforms to `depth_pose_request_v1.schema.json`. `image` is an `ImageData` decoded and
byte-length checked by the NOVA worker. The returned object must conform to
`depth_pose_frame_v1.schema.json`; its frame number and dimensions must match the request, and it
may contain only labels in `request.requested_labels`.

Provider code, transitive JavaScript packages, model weights, remote downloads, telemetry, and
commercial-use terms must be reviewed independently. NOVA does not treat a framework's license as
permission to use every model distributed through that framework.
