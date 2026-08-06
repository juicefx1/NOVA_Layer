# NOVA Layer v1.0.0rc1

## Highlights

- PREVIEW / SOURCE / SCENE pixel contracts
- Project/workspace OCIO color settings
- Scene Linear OpenEXR streaming export
- Viewer QA tools
- Async cancellable export
- Path containment
- Safe shutdown

## Color Pipeline

- Raw / Preview / Source caches
- Exposure / display transform separation
- Processing and propagation use SOURCE
- Viewer uses PREVIEW

## Viewer QA Tools

- Diagnostics dialog
- Pixel Inspector
- Histogram
- False Color
- Performance HUD

## Scene Linear EXR

- EXR sequence + OpenImageIO required
- file-native scene float
- straight alpha
- streaming export
- `nova:*` header metadata
- manifest authoritative
- chromaticities intentionally omitted
- Current Render Look EXR is not scene-linear

## Reliability and Security

- cancellable background export jobs
- staging cleanup
- package path containment
- symlink escape prevention
- bounded shutdown wait

## Packaging

- version `1.0.0rc1`
- extras: `desktop`, `color`, `oiio`, `ai`, `dev`
- 25 console scripts
- clean wheel/sdist smoke verified

## Known Limitations

- no raster/video scene-linear fallback
- no multilayer/AOV/deep EXR
- no GPU display pipeline
- chromaticities omitted
- Scene Linear requires EXR + OIIO + OpenEXR writer

## Test Status

- 951 passed
- 26 skipped
- 0 failed
- skips: 25 PyOpenColorIO, 1 OpenImageIO in dev venv
- clean install with `desktop,color,oiio` verified on Python 3.12

## Upgrade / Compatibility

- Project schema 1.1
- Object Workflow schema 2.0 is separate
- Existing old tag `v1.0.0-rc1` is not this RC
- New tag is `v1.0.0rc1`
