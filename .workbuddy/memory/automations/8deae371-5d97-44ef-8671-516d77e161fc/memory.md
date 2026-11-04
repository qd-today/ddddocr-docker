# 发布 run 检查（ddddocr-docker）

## 2026-11-04 02:10
- 检查 run 41669197254（tag 1.6.1，2026-11-03 23:57 触发）：completed / success，20 个 job 全绿，总耗时约 100 分钟（15:57→17:37 UTC）。
- 耗时分布：wheel 侧 ppc64le 96min、loong64 90min、riscv64 51min 为瓶颈；原生平台 arm64/amd64/armv7 均 <15min。
- 产物校验（arm64 wheelhouse）：/wheels 内为 opencv_python_headless-5.0.0.93-cp314-cp314-musllinux_1_2_aarch64.whl，无 4.14.0 残留；arm64 无 simple index 版本混用，SHA256SUMS 与 index.html 的 sha256 一致。
- registry 一致性：docker.io 与 ghcr.io 的 1.6.1-wheelhouse 及 1.6.1 的 manifest digest 完全相同（index 层一致，平台子 manifest digest 亦一致）。
- runtime 冒烟：python 3.14.10 / cv2 5.0.0(包元数据 5.0.0.93) / pillow 13.0.0 / ddddocr 1.6.1 / onnxruntime 1.24.4。
- 坑记录：本地若已有旧的 a76yyyy/ddddocr:1.6.1（10-28 构建，cv2 4.14.0），`docker run` 不会自动 pull，会得到错误的版本结论。校验 tag 前必须显式 `docker pull --platform`。wheelhouse 镜像是 scratch，无 shell，只能用 `docker create` + `docker export | tar` 读取文件。
- qd 侧：qd 默认分支是 master（无 main），其 Dockerfile 仍基于 a76yyyy/pycurl:1.5.0 且未引用该 wheelhouse，产物已就绪但消费方改动尚未合入。
- 结论：无需修复，本轮无改动、无新增资料库文档。
