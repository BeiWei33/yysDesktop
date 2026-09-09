# 分辨率归一化实施计划

> **面向 Agent 执行者：** 必需子技能：使用 superpower-subagent-driven-development（推荐）或 superpower-executing-plans 按任务逐项执行本计划。步骤使用复选框（`- [ ]`）语法进行跟踪。

**目标：** 把不同 DPI、窗口尺寸和模拟器黑边缓冲区统一为 1136×640 标准画布，并将所有前后台输入准确映射回目标窗口。

**架构：** 新建无平台依赖的 `ViewportTransform` 和按 HWND 隔离的 `ViewportRegistry`，由截图层校准有效游戏区域、输出标准画布；识别和业务代码继续使用标准坐标，输入适配器仅在 Win32/PyAutoGUI 边界转换坐标。异常画面按 16:9 约束失败关闭，截图失败以明确异常中止，不把 `None` 传给 OpenCV/OCR。

**技术栈：** Python 3.12、Pillow、NumPy、OpenCV、PyWin32、PyAutoGUI、PySide6、pytest

**规格：** `docs/superpowers/specs/2026-09-08-resolution-normalization-design.md`

## 全局约束

- 标准坐标系固定为 1136×640。
- `Point`、`Rectangle`、素材区域、OCR 结果、业务硬编码坐标、点击边界和轨迹均保持标准坐标。
- 有效游戏画面必须接近 16:9，宽高比误差不超过 2%；不拉伸非 16:9 布局。
- 窗口预览、识别、OCR 和任务保存截图统一输出标准画面。
- 变换缓存按 HWND 隔离，并在截图方式、原始尺寸或窗口几何变化时失效。
- `input_motion_enabled` 只控制输入随机化，不关闭归一化。
- 本计划不并行运行多个任务状态机。
- 不新增第三方依赖。
- 当前工作区没有 `.git` 元数据；每项“提交”步骤仅在 `.git` 恢复后执行，否则记录跳过，不创建替代仓库。

---

### Task 1：纯视口变换与有效画面检测

**文件：**
- 新建：`src/utils/viewport.py`
- 新建：`tests/test_viewport.py`
- 测试素材：测试内生成合成图；隐私安全的故障回放 fixture 由任务 5 生成

**接口：**
- 依赖输入：Pillow `Image.Image`、整数 HWND、原始截图尺寸和屏幕客户区矩形。
- 对外产出：
  - `CANONICAL_SIZE: tuple[int, int] = (1136, 640)`
  - `ViewportDetectionError`（从 `src.utils.exception` 导入；步骤 3 同时在 `exception.py` 定义）
  - `detect_active_rect(image: Image.Image) -> tuple[int, int, int, int]`
  - `ViewportTransform(handle, capture_size, active_capture_rect, screen_client_rect)`
  - `normalize(image) -> Image.Image`
  - `canonical_to_backend(point) -> tuple[int, int]`（兼容：active capture 坐标）
  - `backend_to_canonical(point) -> tuple[int, int]`（兼容：active capture 坐标）
  - `canonical_to_input(point) -> tuple[int, int]`
  - `input_to_canonical(point) -> tuple[int, int]`
  - `canonical_to_screen(point) -> tuple[int, int]`
  - `screen_to_canonical(point) -> tuple[int, int]`
  - `canonical_region_to_capture(rect) -> tuple[int, int, int, int]`
  - `ViewportRegistry.get/set/invalidate/clear`

- [ ] **步骤 1：编写有效画面检测失败测试**

在 `tests/test_viewport.py` 创建合成图：1136×640 彩色内容嵌在 1704×960 黑底的左上、居中，以及带 RGB 0–8 噪声黑边。断言 `detect_active_rect()` 返回内容包围框；创建 4:3 内容、全黑图和 100×50 小图，断言抛出 `ViewportDetectionError`。

```python
from PIL import Image
import pytest

from src.utils.viewport import ViewportDetectionError, detect_active_rect


def content(size=(753, 424)):
    image = Image.new("RGB", size, (40, 30, 20))
    for x in range(0, size[0], 20):
        image.putpixel((x, size[1] // 2), (200, 120, 60))
    return image


def test_detects_right_and_bottom_padding():
    raw = Image.new("RGB", (1129, 636), "black")
    raw.paste(content(), (0, 0))
    assert detect_active_rect(raw) == (0, 0, 753, 424)


def test_rejects_non_widescreen_content():
    raw = Image.new("RGB", (800, 600), (30, 30, 30))
    with pytest.raises(ViewportDetectionError):
        detect_active_rect(raw)
```

检测定义必须具体：像素任一通道大于 12 视为活跃；行或列活跃占比大于 2% 视为内容；对初始包围框分别尝试 `bottom` 的 ±4 行和 `right` 的 ±4 列，选择宽高比最接近 16:9 且误差不超过 2%的最大候选；候选宽高至少 384×216。此小范围修正覆盖真实图中 y=424–426 的窗口装饰线。

- [ ] **步骤 2：运行检测测试并确认失败**

运行：`.venv\Scripts\python.exe -m pytest tests\test_viewport.py -q`

预期：FAIL，提示 `ModuleNotFoundError: src.utils.viewport`。

- [ ] **步骤 3：实现最小检测算法**

先在 `src/utils/exception.py` 定义 `ViewportDetectionError(CustomException)`；构造参数为 `raw_size`、`candidate_rect`、`reason`，`str(error)` 输出三者。`viewport.py` 导入该异常，并使用 `numpy.asarray(image.convert("RGB"))` 建立活跃掩码；只从四周裁连续低占用区域，不在内部做连通域裁剪。

- [ ] **步骤 4：编写变换与归一化失败测试**

覆盖：

```python
def test_normalizes_active_rect_to_canonical_size():
    transform = ViewportTransform(
        handle=7,
        capture_size=(1129, 636),
        active_capture_rect=(0, 0, 753, 424),
        screen_client_rect=(1286, 276, 753, 424),
    )
    assert transform.normalize(raw).size == (1136, 640)

@pytest.mark.parametrize("point", [(0, 0), (568, 320), (1135, 639)])
def test_backend_round_trip_within_one_pixel(point):
    native = transform.canonical_to_backend(point)
    restored = transform.backend_to_canonical(native)
    assert abs(restored[0] - point[0]) <= 1
    assert abs(restored[1] - point[1]) <= 1
```

屏幕映射断言在 `(client_left, client_top)` 基础上使用实际屏幕客户区宽高；输入映射另测 `screen_client_rect` 的客户区宽高与 active capture rect 不同时仍正确；区域映射断言标准 `(100, 50, 200, 100)` 得到位于 active capture rect 内的 `(left, top, width, height)`。

- [ ] **步骤 5：实现 ViewportTransform**

`active_capture_rect` 采用 Pillow `(left, top, right, bottom)`，仅用于 raw capture 裁剪及兼容的 capture-space 映射。Win32 input 映射使用 `screen_client_rect=(left, top, width, height)` 的客户区宽高：

```python
x = canonical_x * (client_width - 1) / 1135
y = canonical_y * (client_height - 1) / 639
```

foreground 映射到 `screen_client_rect=(left, top, width, height)`。`normalize()` 先 crop，再用 `Image.Resampling.LANCZOS` resize。所有输入坐标在转换前钳制到标准或原生边界，最终平台坐标用 `round()`。

- [ ] **步骤 6：编写注册表隔离与失效测试**

创建 handle 1/2 的不同 transform；断言读取互不覆盖。实现 `geometry_key=(capture_method, capture_size, screen_client_rect)`；同 key 可复用，不同 key 返回 None 并删除旧项。全黑图的缓存复用只在 key 相同时允许。

- [ ] **步骤 7：实现 ViewportRegistry 并运行任务测试**

运行：`.venv\Scripts\python.exe -m pytest tests\test_viewport.py -q`

预期：全部 PASS。

- [ ] **步骤 8：提交**

```bash
git add src/utils/viewport.py tests/test_viewport.py
git commit -m "feat: add canonical viewport transforms"
```

无 `.git` 时记录“跳过：工作区无 Git 元数据”。

---

### Task 2：截图层输出标准画布并明确失败

**文件：**
- 修改：`src/utils/viewport.py`（新增供截图、输入和窗口生命周期共享的模块级 `viewport_registry`）
- 修改：`src/utils/exception.py`（增加 `CaptureUnavailableError`；`ViewportDetectionError` 已由任务 1 定义）
- 修改：`src/utils/screenshot.py`
- 修改：`src/utils/window.py`
- 新建：`tests/test_screenshot_normalization.py`

**接口：**
- 依赖输入：任务 1 的 `detect_active_rect`、`ViewportTransform`、`ViewportRegistry`、`CANONICAL_SIZE`。
- 对外产出：
  - `CaptureUnavailableError(CustomException)`
  - `ViewportDetectionError(CustomException)`（沿用任务 1 已定义的异常）
  - `ScreenShot.get_transform() -> ViewportTransform`
  - `ScreenShot.get_raw_image() -> Image.Image`
  - `ScreenShot.get_image() -> Image.Image` 始终返回标准全图或标准区域，永不返回 None
  - `GameWindow.screen_client_rect -> tuple[int, int, int, int]`

- [ ] **步骤 1：编写截图归一化失败测试**

用 monkeypatch 替换 `_capture_raw_backend()` 返回合成的 1129×636 黑底 + 753×424 内容。断言：

```python
shot = ScreenShot(rect=None, handle=fake_window)
assert shot.get_raw_image().size == (1129, 636)
assert shot.get_image().size == (1136, 640)
assert shot.get_transform().active_capture_rect == (0, 0, 753, 424)
```

对 `rect=(100, 50, 200, 100)` 断言返回 `(200, 100)`；对连续十次 None 断言 `CaptureUnavailableError`；对连续全黑且无缓存断言 `ViewportDetectionError`；先校准后全黑且几何未变，断言复用缓存并返回标准黑图。

- [ ] **步骤 2：运行测试确认失败**

运行：`.venv\Scripts\python.exe -m pytest tests\test_screenshot_normalization.py -q`

预期：FAIL，缺少新异常或 ScreenShot 返回原始尺寸。

- [ ] **步骤 3：拆分原始抓图与归一化**

新增 `_capture_raw_front`、`_capture_raw_backend` 作为只负责返回 PIL 图像和更新时间的底层方法；保留 `_screenshot_front`、`_screenshot_backend` 作为兼容包装器，供现有调用和测试继续使用。构造函数每次先抓完整客户区，不再直接原生裁自定义 region；校准/取缓存后 `transform.normalize(raw)`，最后按标准 `rect` crop。

保存以下字段：

```python
self._raw_image: Image.Image
self._image: Image.Image
self._transform: ViewportTransform
```

`save()` 保存 `_image`。重试 10 次，每次 0.1 秒；捕获普通抓图异常继续重试；第 10 次以 `CaptureUnavailableError` 链接最后异常；检测失败若无有效缓存则在最后抛 `ViewportDetectionError`。

- [ ] **步骤 4：补充 GameWindow 屏幕客户区几何**

在 `GameWindow.__init__` 用 `ClientToScreen(handle, (0,0))` 和客户区宽高生成 `screen_client_rect=(left, top, width, height)`。不要用带 `+9/-9` 经验值的 window_rect。

- [ ] **步骤 5：运行截图测试和现有截图调用测试**

运行：`.venv\Scripts\python.exe -m pytest tests\test_screenshot_normalization.py tests\test_input_adapter.py tests\test_ocr_coordinates.py -q`

预期：全部 PASS。

- [ ] **步骤 6：提交**

```bash
git add src/utils/exception.py src/utils/screenshot.py src/utils/window.py tests/test_screenshot_normalization.py
git commit -m "feat: normalize captured game viewport"
```

---

### Task 3：识别与 OCR 保持标准坐标

**文件：**
- 修改：`src/utils/image.py`
- 修改：`src/utils/paddleocr.py`
- 修改：`tests/test_ocr_coordinates.py`
- 新建：`tests/test_recognition_normalization.py`

**接口：**
- 依赖输入：任务 2 的 `ScreenShot` 标准输出。
- 对外产出：`RuleImage.match_result` 和 `OcrData` 坐标全部为标准坐标；所有 assets.json 无需迁移。

- [ ] **步骤 1：编写模板识别标准坐标测试**

生成标准 1136×640 图和 60×40 模板，把模板放在 `(200,100)`；将标准图缩为 753×424 后放入 1129×636 黑底，让 ScreenShot 测试替身返回归一化标准图。断言 `RuleImage.match()` 成功且 `match_result` 在 `(200,100,260,140)` 各轴误差不超过 1。

同时测试 `RuleImage` 全窗口默认 region 必须是 `(0,0,1136,640)`，不再取 `window_manager.current.client_width/client_height`。

- [ ] **步骤 2：运行模板测试确认失败**

运行：`.venv\Scripts\python.exe -m pytest tests\test_recognition_normalization.py -q`

预期：FAIL，默认 region 仍为原生窗口大小或匹配坐标偏移。

- [ ] **步骤 3：修改 RuleImage**

从 viewport 导入 `CANONICAL_SIZE`。空 region 设置为 `(0,0,1136,640)`；当传入 `ScreenShot` 时，其图像可能是全标准图，而当前 RuleImage 有子 region，必须从标准图裁 `self.region` 再匹配。`max_loc` 加回标准 region 左上角一次且仅一次。

- [ ] **步骤 4：补 OCR 标准 region 测试**

`OcrDetector(region=(100,50,200,100))` 收到的标准截图尺寸应为 200×100；OCR 返回 `[10,20,30,40]` 后 `OcrData` 为 `(110,70,130,90)`。全窗口空 region 使用 `(0,0,1136,640)`。

- [ ] **步骤 5：修改 OCR 并运行识别测试**

保留现有 `get_ocrdata_from_result(raw_result, offset=self.region[:2])`，仅把全窗口 region 改成标准尺寸。运行：

`.venv\Scripts\python.exe -m pytest tests\test_recognition_normalization.py tests\test_ocr_coordinates.py -q`

预期：全部 PASS。

- [ ] **步骤 6：提交**

```bash
git add src/utils/image.py src/utils/paddleocr.py tests/test_recognition_normalization.py tests/test_ocr_coordinates.py
git commit -m "fix: keep recognition in canonical coordinates"
```

---

### Task 4：前后台输入反向映射

**文件：**
- 修改：`src/utils/point.py`
- 修改：`src/utils/adapter.py`
- 修改：`src/utils/function.py`
- 修改：`tests/test_input_adapter.py`
- 新建：`tests/test_point_transform.py`

**接口：**
- 依赖输入：任务 1 的 Registry/Transform；任务 2 在窗口截图后已建立 transform。
- 对外产出：
  - `Point.to_screen(handle: int | None = None)` 从标准坐标映射到屏幕坐标。
  - `Point.from_screen(..., handle: int | None = None)` 反向映射到标准坐标。
  - 后台 Win32 消息坐标统一由标准坐标映射。
  - `Mouse.position()` 始终返回标准坐标。

- [ ] **步骤 1：编写 Point 前台映射失败测试**

注册 handle 7 的 transform：active 753×424，screen client `(1286,276,753,424)`。令 current handle=7；断言 `Point(568,320).to_screen()` 接近 `(1663,488)`，再用 `Point.from_screen()` 往返误差不超过 1。无 transform 时断言抛 `ViewportDetectionError`，不悄悄按原坐标点击。

- [ ] **步骤 2：运行 Point 测试确认失败**

运行：`.venv\Scripts\python.exe -m pytest tests\test_point_transform.py -q`

预期：FAIL，现有实现直接调用 ClientToScreen。

- [ ] **步骤 3：实现 Point 映射**

`Point` 仍存 canonical client_x/client_y。`to_screen/from_screen` 通过 Registry 获取当前或显式 handle 的 transform。显式 handle 为多窗口预留，不更改现有无参调用。

- [ ] **步骤 4：编写后台消息映射失败测试**

扩充 `test_input_adapter.py`：标准 `Point(1135,639)` 在截图 active rect 为 753×424、Win32 客户区为 1129×636 时必须发送接近 `(1128,635)` 的 MAKELONG；另测 active rect 与客户区相同的 identity/缩放情况。路径中每个点都在输入客户区边界；点击边界只采样一次且采样发生在标准坐标。

前台测试断言 PyAutoGUI 收到 screen 映射结果，不是标准值。`Mouse.position()` 前后台均反向返回标准坐标。

- [ ] **步骤 5：实现 Mouse 平台边界映射**

后台 `_backend_move_to` 和 `_drag_backend` 保持 `_back_click_point` 为标准 Point；发送每个消息前调用当前 handle 的 `canonical_to_input`。`_win_left_click`、scroll lParam 同样使用 Win32 客户区点。前台继续由 Point.to_screen 映射。不得在轨迹生成前映射，否则不同横纵缩放会改变标准路径语义。

- [ ] **步骤 6：消除业务层原生尺寸依赖**

把 `baiguiyexing.py` 中 `window_manager.current.client_width/client_height` 改为 `CANONICAL_SIZE`，并 grep 全项目确保业务包不再读取 client dimensions。`finish_random_left_right()` 继续使用标准 Rectangle 和标准 `Mouse.position()`。

- [ ] **步骤 7：运行输入测试**

运行：`.venv\Scripts\python.exe -m pytest tests\test_point_transform.py tests\test_input_adapter.py tests\test_input_motion.py -q`

预期：全部 PASS。

- [ ] **步骤 8：提交**

```bash
git add src/utils/point.py src/utils/adapter.py src/utils/function.py src/package/baiguiyexing.py tests/test_point_transform.py tests/test_input_adapter.py
git commit -m "feat: map canonical input to target windows"
```

---

### Task 5：真实百鬼夜行故障回放与截图提示

**文件：**
- 新建：`tests/fixtures/baigui_dpi_padded.png`
- 新建：`tests/test_baigui_viewport_regression.py`
- 修改：`src/package/baiguiyexing.py`
- 修改：`src/package/base_package.py`（只在需要通用截图计数时）

**接口：**
- 依赖输入：任务 2 标准 ScreenShot，任务 3 标准识别。
- 对外产出：隐私安全的 DPI 故障几何回放；任务只在实际保存至少一张图后显示目录。

- [ ] **步骤 1：固化真实故障 fixture**

当前抓图含角色昵称等信息，不能原样进入测试库。创建 1129×636 黑底合成图：从 `src/resource/baiguiyexing/title.png` 缩放至 2/3 后贴到 753×424 彩色渐变有效区的标准比例位置，并在 y=424–426 加入与真实故障相同的浅色装饰线；保存为 `tests/fixtures/baigui_dpi_padded.png`。该 fixture 保留尺寸、黑边和模板比例故障，不包含用户数据。

- [ ] **步骤 2：编写回放失败测试**

```python
def test_baigui_title_matches_after_viewport_normalization():
    raw = Image.open(FIXTURE)
    template = cv2.imread(str(TITLE))
    raw_score = match_score(raw, template)
    normalized = transform_for(raw).normalize(raw)
    normalized_score = match_score(normalized, template)
    assert raw_score < 0.7
    assert normalized_score >= 0.7
    assert normalized.size == (1136, 640)
```

同时断言 active rect 接近 `(0,0,753,424)`（bottom 可允许到 427），归一化后的模板位置落在标准客户区。

- [ ] **步骤 3：运行回放确认修复前失败**

运行：`.venv\Scripts\python.exe -m pytest tests\test_baigui_viewport_regression.py -q`

预期：在任务 1–4 完成前 FAIL；完成后 PASS。记录 raw 与 normalized 分数到断言失败信息。

- [ ] **步骤 4：修复误导截图提示并测试**

在 BaiGuiYeXing 实例记录 `saved_screenshot_count=0`；`finish()` 中 `self.screenshot()` 成功后加一；`task_finish_info()` 仅在 count>0 时打印目录。测试 `flag_screenshot=True, count=0` 不调用 `logger.ui`，count=1 时调用一次。

- [ ] **步骤 5：运行回放与包测试**

运行：`.venv\Scripts\python.exe -m pytest tests\test_baigui_viewport_regression.py tests\package\test_baiguiyexing.py -q`

预期：全部 PASS，fixture 的 normalized score 至少 0.7。

- [ ] **步骤 6：提交**

```bash
git add tests/fixtures/baigui_dpi_padded.png tests/test_baigui_viewport_regression.py src/package/baiguiyexing.py
git commit -m "test: cover DPI-padded BaiGui viewport"
```

---

### Task 6：预览、多窗口缓存和最终验证

**文件：**
- 修改：`src/utils/gui.py`
- 修改：`src/utils/window.py`
- 修改：`tests/test_viewport.py`
- 修改：`README.md` 或 `CHANGELOG.MD`（选择项目现有变更记录惯例对应文件）

**接口：**
- 依赖输入：全部前置任务。
- 对外产出：预览显示标准画面和标准尺寸；窗口变化时缓存准确失效；用户文档说明支持范围。

- [ ] **步骤 1：编写显式 handle 预览/缓存测试**

为 handle 1/2 构造不同原始尺寸和 active rect；分别 `ScreenShot(handle=...)`，断言 registry 保留两项且结果都为 1136×640。改变 handle 1 raw size 后仅 handle 1 重新检测；handle 2 transform 对象保持相同。

- [ ] **步骤 2：实现 GUI 预览语义**

`preview_window()` 继续调用 `ScreenShot(handle=handle).get_image()`；标签明确显示 `标准画面 1136 X 640`。若抛 `ViewportDetectionError/CaptureUnavailableError`，显示一次明确错误并保持上次 pixmap，不对 None 构造 ImageQt。

- [ ] **步骤 3：接入窗口生命周期失效**

在 `GameWindowManager.update_window_task()` 中，窗口消失时调用 registry.invalidate(handle)；窗口几何变化无需无条件删除，ScreenShot 用 geometry key 自动重校准。关闭全部窗口时清除已消失 handles，不能清除仍存在但未选中的窗口缓存。

- [ ] **步骤 4：更新用户说明**

记录：支持 Windows 100/125/150% 等缩放与可变 16:9 窗口；非 16:9 内容会停止并提示；不再要求通过全局 Windows 缩放修复识别；任务截图和预览为 1136×640 标准画面。

- [ ] **步骤 5：运行完整自动验证**

运行：

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe -m compileall -q src tests
```

预期：pytest 0 failures，compileall 退出码 0。

- [ ] **步骤 6：运行只读实时 MuMu 验证**

使用当前选中 HWND：抓取 BitBlt 原图但不发送输入；输出 raw size、active rect、normalized size、title match score、标准中心 `(568,320)` 映射到 backend/screen 后的坐标。验收条件：

- normalized size 为 1136×640；
- active ratio 在 16:9 的 2% 内；
- 当前百鬼入口页 title score ≥0.7；
- backend/screen 坐标落在对应窗口有效客户区内；
- 不调用 Mouse.click/drag 或任何发送输入的 API。

- [ ] **步骤 7：清理诊断产物**

删除临时 `data/baigui_diagnostic.png`、`data/baigui_printwindow.png`；保留脱敏后的 `tests/fixtures/baigui_dpi_padded.png`。grep `[DEBUG-`，确保无临时调试日志。

- [ ] **步骤 8：最终评审与提交**

请求代码评审，修复所有 Critical/Important 问题，重跑步骤 5–6。若 Git 可用：

```bash
git add src tests docs README.md CHANGELOG.MD
git commit -m "feat: normalize game viewport across DPI scales"
```

只添加实际修改的文档文件，不覆盖用户无关变更。
