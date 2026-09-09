# Resolution Normalization Design

Date: 2026-09-08
Status: Approved design, pending implementation plan

## Problem

The application assumes a 1136x640 game client. Under Windows display scaling and some emulator windows, Win32 reports a client buffer such as 1129x636 while BitBlt contains only a 753x424 game image plus black padding. Templates remain at the canonical scale, so matching fails even when the correct scene is visible. In the reproduced BaiGuiYeXing case, the unmodified title template scored 0.3791 against a 0.7 threshold; resizing it to two thirds scored 0.9705.

Recognition coordinates, hard-coded task coordinates, foreground screen coordinates, and backend WM_MOUSE coordinates currently share the same Point type without an explicit transform. Fixing only template matching would leave clicks and drags misaligned.

## Goals

- Keep 1136x640 as the only coordinate system visible to recognition and task packages.
- Normalize supported 16:9 game content from different DPI settings and window sizes.
- Remove capture padding before recognition, preview, OCR, and saved screenshots.
- Map standard coordinates to foreground screen coordinates and backend native client coordinates.
- Isolate transform state by window handle and invalidate it when window geometry changes.
- Preserve existing template assets and hard-coded task coordinates.
- Stop safely with a clear message when a trustworthy 16:9 viewport cannot be established.

## Non-goals

- Running multiple task state machines concurrently.
- Supporting arbitrary non-16:9 game layouts.
- Replacing OpenCV template matching or PaddleOCR.
- Silently stretching distorted or ambiguous content.
- Solving input behavior intended to evade detection.

## Canonical Coordinate Space

The canonical client size is 1136x640. Point, Rectangle, asset region, OCR result, task constants, random click bounds, and generated motion paths remain canonical unless an API explicitly states otherwise.

A new viewport module owns conversions. Callers do not manually multiply coordinates.

```python
CANONICAL_SIZE = (1136, 640)

class ViewportTransform:
    handle: int
    capture_size: tuple[int, int]
    active_capture_rect: tuple[int, int, int, int]
    screen_client_rect: tuple[int, int, int, int]

    def canonical_to_backend(self, point): ...  # legacy active-capture helper
    def backend_to_canonical(self, point): ...  # legacy active-capture helper
    def canonical_to_input(self, point): ...
    def input_to_canonical(self, point): ...
    def canonical_to_screen(self, point): ...
    def normalize(self, image): ...
    def canonical_region_to_capture(self, rect): ...
```

Conversions round only at the platform boundary. A canonical-to-native-to-canonical round trip may differ by at most one pixel per axis.

## Viewport Detection

A raw full-window capture is analyzed before normalization:

1. Detect contiguous near-black padding from all four edges using row and column occupancy, not a single pixel.
2. Keep the largest plausible content rectangle after padding removal.
3. Require positive dimensions, a minimum useful size, and aspect ratio within 2% of 16:9.
4. Reject transforms that would retain a large, clearly empty strip or crop a meaningful populated strip.
5. Cache the last valid transform per window.

The detector treats a fully black loading frame as inconclusive. If a valid cached transform exists for the same unchanged geometry, the cache is reused. Otherwise ScreenShot retries through its existing bounded retry path and then raises ViewportDetectionError.

The known failure fixture must resolve a 753x424 active image from a 1129x636 padded capture.

## Capture Pipeline

ScreenShot remains the public capture API, but its returned image is canonical:

1. Resolve the target GameWindow from the explicit handle or current selection.
2. Obtain or calibrate that handle's ViewportTransform.
3. Capture the raw backend buffer or foreground screen client.
4. Crop the active content rectangle.
5. Resize with a high-quality deterministic filter to 1136x640.
6. If a canonical region was requested, return that region at its canonical width and height.

For correctness, the first implementation captures and normalizes the full frame before applying a canonical region. Region-level native capture is excluded until profiling demonstrates a need.

Window preview, OCR, template matching, and task screenshots receive normalized images. Raw images are not user-facing and may only be emitted as explicitly named diagnostic artifacts.

## Input Mapping

### Foreground

Point.to_screen and Point.from_screen delegate to the selected window's transform. Canonical coordinates map to the physical on-screen client area. The mapping uses the real client screen rectangle, not the dimensions of a DPI-virtualized capture buffer.

### Backend

Mouse keeps its logical position in canonical coordinates. Each generated path point is mapped to the target window's Win32 client input rectangle immediately before `MAKELONG` and `WM_MOUSEMOVE`/`WM_LBUTTON` messages. The input rectangle uses the client width and height from `screen_client_rect`; it is independent from `active_capture_rect`, which only describes pixels retained from a raw screenshot. This distinction is required when a DPI-scaled capture buffer is `1129x636` while the detected game content is only `753x427`. Handle changes reset logical position and select the matching per-handle transform.

### Click Bounds And Dragging

Recognition click_bounds remain canonical, so centered sampling is unaffected. Motion paths are generated canonically and transformed point by point. Drag offsets supplied by task packages are canonical distances.

## Cache And Multi-window Isolation

ViewportRegistry is keyed by HWND. A cache entry records:

- window handle;
- capture method;
- raw capture dimensions;
- window/client geometry used for foreground mapping;
- active capture rectangle;
- last validation time or generation.

An entry is invalidated when the handle disappears, capture method changes, raw dimensions change, or current geometry changes. Selecting another window never overwrites another handle's transform. This prepares the coordinate layer for multi-window scheduling without adding concurrent task execution in this design.

## Error Handling And Diagnostics

Introduce specific errors derived from the project's CustomException where appropriate:

- CaptureUnavailableError: no image was produced after retries.
- ViewportDetectionError: no trustworthy active 16:9 content was found.

User-facing errors include the handle, raw size, detected candidate rectangle, and reason, without flooding the log on every recognition loop. A successful calibration logs one structured summary whenever a transform is created or changes.

OpenCV and OCR must never receive None from ScreenShot.

BaiGuiYeXing's completion message should only claim that screenshots were saved when at least one file was actually written. This removes the misleading directory message seen after a zero-run manual stop.

## Compatibility

- Existing Point, Rectangle, RuleImage, RuleOcr, Mouse, and ScreenShot call sites retain canonical arguments.
- Existing assets.json regions remain unchanged.
- Existing 1136x640 installations produce an identity transform.
- input_motion_enabled only controls motion/click randomization; normalization remains mandatory for correctness.
- PrintWindow and BitBlt both feed the same normalization layer.
- Non-16:9 active content fails closed instead of being stretched or cropped.

## Test Strategy

### Pure Unit Tests

- Identity transform at 1136x640.
- 753x424 to 1136x640 scaling.
- Canonical/active-capture and canonical/screen round trips within one pixel.
- Canonical/Win32-input-client round trips within one pixel when the active capture rect differs from client size.
- Black padding on right/bottom and symmetric letterboxing.
- Near-black compression noise around padding edges.
- Rejection of 4:3 or degenerate content.
- Per-handle registry isolation and geometry invalidation.
- Cached transform reuse for a fully black loading frame.

### Integration Tests

- ScreenShot returns 1136x640 for full captures and canonical dimensions for regions.
- RuleImage match_result remains canonical after a scaled capture.
- OCR region offsets remain canonical.
- Backend `WM_MOUSE` lParam uses the Win32 input-client transform, independent of active capture cropping.
- Foreground clicks use transformed screen coordinates.
- input motion paths preserve their canonical endpoint after mapping.
- BaiGuiYeXing does not report a screenshot directory when zero files were saved.

### Captured Regression Replay

Use the reproduced BaiGuiYeXing capture pattern: a 753x424 game image in a 1129x636 black-padded buffer. The normalized title match must exceed the configured 0.7 threshold. The original unnormalized comparison remains below threshold to prove the regression test covers the reported failure.

### Final Verification

- Run the complete pytest suite.
- Run compileall over src and tests.
- Replay the captured DPI failure.
- Capture the live MuMu window in backend mode and verify normalized size, title recognition, and mapped coordinates without sending a click.
- Manually run one BaiGuiYeXing cycle only when the user has the game in a safe test state; automated completion does not depend on a live click test.

## Rollout

Normalization is enabled as correctness infrastructure rather than a user toggle. On unsupported geometry, the task stops before input. Logs provide enough transform data to diagnose unexpected emulator behavior. No existing templates or per-task coordinates are migrated during this change.
