# ddddocr Docker 镜像（Alpine）

ddddocr 运行栈的 musllinux wheel 分发，另附装好的可运行镜像。三个包在本仓库自编或自打包：
`ddddocr`（纯 python + 模型文件）、`opencv`（最小化）、`Pillow`；onnxruntime 与 numpy 取自
[onnxruntime-docker](https://github.com/qd-today/onnxruntime-docker) 的 wheelhouse。

- Docker Hub：<https://hub.docker.com/r/a76yyyy/ddddocr>
- 源码：[qd-today/ddddocr-docker](https://github.com/qd-today/ddddocr-docker)

## 快速开始

直接用镜像：

```bash
docker run --rm -v "$PWD/captcha.png:/c.png" a76yyyy/ddddocr:latest \
  python3 -c "import ddddocr; print(ddddocr.DdddOcr(show_ad=False).classification(open('/c.png','rb').read()))"
```

以两个 wheelhouse 作为依赖来源：

```dockerfile
# syntax=docker/dockerfile:1.7
FROM alpine:3.24
RUN --mount=type=bind,from=a76yyyy/ddddocr:wheelhouse,source=/wheels,target=/w1 \
    --mount=type=bind,from=a76yyyy/onnxruntime:wheelhouse,source=/wheels,target=/w2 \
    apk add --no-cache $(cat /w1/system-packages.txt) uv && \
    uv pip install --system --break-system-packages --no-cache \
        --index-url https://pypi.org/simple \
        --extra-index-url file:///w1/simple \
        --extra-index-url file:///w2/simple \
        "ddddocr==1.6.1" "opencv-python-headless==5.0.0" "pillow==13.0.0" \
        "onnxruntime==1.24.4" "numpy==2.4.6"
```

| 写法 | 原因 |
|---|---|
| `apk add $(cat /w1/system-packages.txt)` | 清单是 wheelhouse 的运行时前置条件（解释器与 `libz`），写错会在这里构建失败 |
| `--index-url https://pypi.org/simple` | 默认索引是**最低**优先级，只用于兜底纯 Python 依赖（flatbuffers / packaging / protobuf / sympy） |
| `--extra-index-url file:///wN/simple` | 每个 wheelhouse 一个，按定义顺序查询；first-index 策略下第一个含该包的索引胜出，因此本地那份一定被选中 |
| 发行名与 PyPI 同名 | wheel 用 PyPI 同名发行名（如 `opencv-python-headless`），换回 PyPI 版不用改任何配置；功能差异只在本仓库刻意裁剪的那部分 |

`/w1/simple` 是 PEP 503 索引，链接为相对路径，可与 wheel 目录一起挂到任意位置。

## 镜像内容

| 组件 | wheelhouse | runtime |
|---|---|---|
| 基础镜像 | `scratch` | `alpine:3.24`；loong64 为 `ghcr.io/loong64/alpine:3.24` |
| Python | — | 3.14 |
| ddddocr | 1.6.1（`py3-none-any`） | 同左 |
| OpenCV | 5.0.0（`musllinux_1_2`） | 同左 |
| Pillow | 13.0.0（`musllinux_1_2`） | 同左 |
| onnxruntime / numpy | —（在 onnxruntime 的 wheelhouse 里） | 1.24.4 / 2.4.6 |
| 额外系统包 | — | `bash`、`tzdata`、`ca-certificates`、`icu-data-en` |
| 内容位置 | `/wheels` | `/usr/lib/python3.14/site-packages` |

## 支持的平台

| 平台 | wheelhouse | runtime | wheel 架构名 |
|---|---|---|---|
| `linux/amd64` | ✓ | ✓ | `x86_64` |
| `linux/arm64` | ✓ | ✓ | `aarch64` |
| `linux/arm/v7` | ✓ | ✓ | `armv7l` |
| `linux/ppc64le` | ✓ | ✓ | `ppc64le` |
| `linux/riscv64` | ✓ | ✓ | `riscv64` |
| `linux/loong64` | ✓ | ✓ | `loongarch64` |

`linux/386`、`linux/arm/v6`、`linux/s390x` 不提供：onnxruntime 在这三个架构上没有可用的
Python 绑定（Alpine 配方 `arch="all !s390x !x86"`；armhf 被 `py3-flatbuffers` 挡住），
而 ddddocr 没有 onnxruntime 就跑不起来。

loong64 构建需 `--build-arg BASE_IMAGE=ghcr.io/loong64/alpine:3.24`（Docker Hub 官方
alpine 无此架构）。

## 标签

| 标签 | 内容 |
|---|---|
| `<ver>-wheelhouse` | `scratch` + `/wheels`：三个 wheel、`SHA256SUMS`、`system-packages.txt`、PEP 503 索引 |
| `<ver>` | `alpine:3.24` + Python 3.14 + 上述包（含 onnxruntime / numpy） |
| `wheelhouse` / `latest` | 上面两者的滚动标签 |

`<ver>` 只在 tag 推送时产出；workflow_dispatch 只更新滚动标签。

## 构建

wheel 的构建与镜像的组装分两步：第一步产出 wheel，第二步用这份产物组装镜像。两步之间可以用
不同的架构环境（CI 里 arm 系列在原生 arm64 上编，组装统一在 x86_64）。

```bash
# ① 编译产物：/wheels
docker buildx build --platform linux/arm64 --target artifacts \
    --output type=local,dest=./dist .

# ② 可运行镜像
docker buildx build --platform linux/arm64 --target runtime \
    --build-context wheelsrc=./dist -t ddddocr:1.6.1 .

# ③ wheelhouse 镜像（供上层 COPY --from / bind mount）
docker buildx build --platform linux/arm64 --target wheel-from-artifacts \
    --build-context wheelsrc=./dist -t ddddocr:wheelhouse .
```

`--target runtime` 不传 `--build-context wheelsrc` 会失败：镜像里必须有 ddddocr，宁可报错也不要
静默产出一个空基座。runtime 还需要 onnxruntime 的 wheelhouse（`ONNX_WHEELHOUSE`，默认指向
`a76yyyy/onnxruntime:<onnx_version>-wheelhouse`）。

| 参数 | 默认 | 说明 |
|---|---|---|
| `ALPINE_VERSION` | `3.24` | 决定 Python 版本与 wheel 的 `cpXX` tag |
| `BASE_IMAGE` | `alpine:${ALPINE_VERSION}` | loong64 传 `ghcr.io/loong64/alpine:3.24` |
| `ONNX_WHEELHOUSE` | `a76yyyy/onnxruntime:1.24.4-wheelhouse` | onnxruntime / numpy 的来源 |
| `ONNX_VERSION` / `NUMPY_VERSION` | `1.24.4` / `2.4.6` | 与上面的 wheelhouse 内容不一致时构建失败 |
| `OPENCV_VERSION` | `5.0.0` | 源码版本 |
| `OPENCV_CPU_BASELINE` | 空 | `NEON` 让 armv7 的 OpenCV 以 NEON 为基线 |
| `PILLOW_VERSION` | `13.0.0` | 源码版本 |
| `DDDDOCR_REF` | `master` | ddddocr 的 git ref（分支 / tag / SHA） |
| `DDDDOCR_VERSION` | 空 | 非空时断言产出的 wheel 版本，与镜像 tag 对齐 |
| `APK_MIRROR` | 空 | 如 `https://mirrors.tuna.tsinghua.edu.cn` |
| `PIP_MIRROR` | 空 | 如 `https://pypi.tuna.tsinghua.edu.cn/simple` |
| `GIT_DOMAIN` | `https://github.com` | 拉 ddddocr 源码的前缀 |

## 产物

```
/wheels/
  ddddocr-1.6.1-py3-none-any.whl                       # 纯 python + 模型文件，与架构无关
  opencv-5.0.0-cp314-cp314-musllinux_1_2_<arch>.whl
  pillow-13.0.0-cp314-cp314-musllinux_1_2_<arch>.whl
  SHA256SUMS
  system-packages.txt
  simple/
    index.html
    <project>/index.html
```

`system-packages.txt` 是上层需要 `apk add` 的包（一行一个，无注释）：`python3` 与 `zlib`。
前者是解释器；后者因为 musllinux 白名单只有 `libc` 与 `libz`，Pillow 与
`libopencv_imgcodecs` 都动态链接了 `libz.so.1`，它不会被收进 `.libs/`。

`simple/` 由 `src/pack_wheel.py --emit-index` 生成，链接为相对路径（`../../<wheel>#sha256=`），
构建期会回读校验每个链接与哈希。

| 标签 | 含义 | PyPI 接受 |
|---|---|---|
| `musllinux_1_2_<arch>` | 在 musl ≥ 1.2 上构建，除 musl 与 libz 外不依赖系统库 | 是 |
| `py3-none-any` | 纯 python，无原生产物 | 是 |
| `linux_<arch>` | 只说明 CPU 架构 | 否 |

## 已知限制

- `cv2` 是顶层扩展模块（`cv2.cpython-314-<arch>-linux-musl.so`），不是包：OpenCV 的绑定
  在初始化时用写死的 `cv2` 注册子模块，装成 `cv2/cv2.*.so` 会报
  `Bindings generation error`。因此没有 `cv2.data`（haarcascades 等数据文件），自编时也
  只开了 core / imgproc / imgcodecs，没有 video / photo / dnn。
  影响面：级联分类器（人脸、眼睛检测）不可用，`cv2.data` 属性不存在，`import cv2.cv2` 不可用；
  文字识别不依赖这些，ddddocr 自身代码未引用 `cv2.data` 或级联文件。
- 自编 OpenCV 沿用 `opencv-python-headless` 这个发行名：官方四个包（`opencv-python` /
  `opencv-contrib-python` / `opencv-python-headless` / `opencv-contrib-python-headless`）
  里，它是「无 GUI / 无后端」的那一个，正是容器场景要的。
  **但它不是官方版的等价物**：官方 headless 版是完整模块（video / photo / dnn 等俱全），
  本仓库只保留 core / imgproc / imgcodecs，也没有 `cv2.data` 的级联文件。
  发行名保持一致的意义是：用户改从 PyPI 安装同名包，就换回功能完整的官方版，配置不用动。
- wheel 的 `cp314` 与 `alpine:3.24` 的 Python 3.14 绑定；换 Python 小版本需要重新构建。

## 维护者

<details>
<summary>版本参数</summary>

上游发新版时，改这里或 dispatch 时传同名输入即可构建新版本；产物版本与传入版本不一致时
构建失败（`--expect-version` 断言）。

| 参数 | 作用 | 默认值 |
|---|---|---|
| `opencv_version` | OpenCV 源码版本（自编最小化 wheel） | 5.0.0 |
| `pillow_version` | Pillow 源码版本（自编 wheel，不链 libimagequant） | 13.0.0 |
| `ddddocr_version` | ddddocr 版本，同时是 runtime 镜像的 tag | 跟随 git ref |
| `ddddocr_ref` | ddddocr 的 git ref（分支 / tag / SHA） | 上游默认分支 |
| `onnx_version` | onnxruntime 版本，同时决定用哪个 wheelhouse 镜像 | 1.24.4 |
| `numpy_version` | numpy 版本（由 onnxruntime 的 wheelhouse 提供） | 2.4.6 |
| `alpine_version` | alpine 版本，决定 Python 小版本与 wheel 的 cpXX tag | 3.24 |

`onnxruntime` 与 `numpy` 来自 Alpine 的 apk 预编译包，版本受 apk 仓限制：参数只能钉住 apk
里已有的版本，apk 更新后再改这里（版本对不上时构建会在断言处失败，不会产出错标版本的 wheel）。

</details>

<details>
<summary>CI 结构</summary>

`Build Image.yml` 是调用方，共用 `.github/workflows/_image.yml`，四段：
plan → build-wheel → build → smoke → publish。

- 仅 `workflow_dispatch` 与 tag push 触发
- 每平台两个 job：`build-wheel` 编 wheel 并导出成 artifact，`build` 用这份产物组装两个出口并推
  digest。拆开是为了让 arm 系列在原生 arm64 runner 上编（`--output type=local` 不支持多平台，
  只能按平台拆）
- `build` 统一跑 x86_64：arm64 runner 走内核 compat 模式时 Python 自报 `linux-aarch64`，
  uv 在那装 wheel 会挂死
- wheel 的 platform tag 由 `_PYTHON_HOST_PLATFORM` 显式指定（按 `TARGETARCH`/`TARGETVARIANT`
  算，CI 经 build-arg 传入 Dockerfile 的 ENV）。不指定时 compat 模式下 Python 会把 arm32 的
  wheel 标成 `linux_aarch64`，auditwheel 随即因 `.so` 与标签不符失败
- 冒烟直接跑 runtime 镜像：`tests/smoke.py` 校验包版本、无 `/wheels` 残留、cv2/PIL 的
  `ldd`、Pillow 契约、protobuf 来源、原生 ELF 架构，并跑一次真实识别
- 闸门 fail-closed：build 与 smoke 均 `success` && 平台集合完整，才合并 manifest；
  子集构建禁止发布

</details>
