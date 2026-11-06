#!/bin/sh
# 把构建产物里的 CycloneDX SBOM 上传到 FOSSA。
#
# 由 CI 在 wheel 构建之后调用；本地不设 FOSSA_API_KEY 时静默跳过，所以不会挡住本地构建。
#
# 为什么不用 FOSSA 自己扫仓库：它的 pip 策略读的是 uv.lock / lockfile，看不到 wheel 里
# auditwheel 收进 <dist>.libs/ 的原生依赖。本仓库分发的 opencv / pillow / pycurl 都是自编
# 产物，与 PyPI 上同名包的许可证足迹完全不同（PyPI 的 opencv 带 FFmpeg+Qt，我们这份不带），
# 让 FOSSA 按 lockfile 分析会得出一堆与现实无关的结论。上传构建时实测的 SBOM 才是真相。
#
# 项目/版本号的映射：
#   每个 wheel 一条 revision   <FOSSA_REVISION>-<发行名>-<版本>
#   wheelhouse 汇总一条        <FOSSA_REVISION>
# 这样同一个项目下既有汇总视角，也能单独看某个 wheel 的依赖，revision 之间不会互相覆盖
# （FOSSA 的 (project, revision) 是唯一键，同一 revision 反复上传只会保留最后一次）。
#
# 环境变量：
#   FOSSA_API_KEY   必填；缺省则跳过（PR 来自 fork 时拿不到 secret，属于正常情况）
#   FOSSA_PROJECT   项目名，默认取 SBOM 里的发行名（wheelhouse 汇总时取仓库目录名）
#   FOSSA_REVISION  版本前缀，建议 "<tag>+<arch>"，默认 git sha
#   SBOM_GLOB       SBOM 搜索路径，默认 dist/wheels/sbom/*.cdx.json
#
# 注意：SBOM import 是 FOSSA 的 Enterprise 特性。企业版之外的 token 会返回 403，本脚本
# 把这当作「未启用」处理，不让 CI 失败。
set -eu

if [ -z "${FOSSA_API_KEY:-}" ]; then
    echo "未设置 FOSSA_API_KEY，跳过 SBOM 上传"
    exit 0
fi

sbom_glob="${SBOM_GLOB:-dist/wheels/sbom/*.cdx.json}"
set -- $sbom_glob
found=0
for f in "$@"; do
    [ -f "$f" ] && found=$((found + 1))
done
if [ "$found" -eq 0 ]; then
    echo "警告: $sbom_glob 里没有 SBOM，说明 --compliance 没跑到？" >&2
    exit 1
fi
echo "待上传 SBOM: ${found} 个（${sbom_glob}）"

# 从 SBOM 的 metadata.component 取 name/version。读不出来就退回文件名，绝不让脚本挂掉。
sbom_field() {
    python3 -c '
import json, sys
try:
    c = json.load(open(sys.argv[1]))["metadata"]["component"]
except Exception:
    print("")
else:
    print(c.get(sys.argv[2]) or "")
' "$1" "$2" 2>/dev/null || echo ""
}

if ! command -v fossa >/dev/null 2>&1; then
    echo "安装 fossa-cli"
    curl -sSL -H 'Cache-Control: no-cache' \
        https://raw.githubusercontent.com/fossas/fossa-cli/master/install-latest.sh | bash
    PATH="$HOME/.local/bin:$PATH"
    export PATH
fi
fossa --version || true

base_revision="${FOSSA_REVISION:-$(git rev-parse --short HEAD 2>/dev/null || echo unknown)}"
failed=0
for f in "$@"; do
    [ -f "$f" ] || continue
    name=$(sbom_field "$f" name)
    version=$(sbom_field "$f" version)
    if [ -z "$name" ]; then
        name=$(basename "$f" .cdx.json)
        version=""
    fi
    if [ "$name" = "wheelhouse" ]; then
        project="${FOSSA_PROJECT:-$name}"
        revision="$base_revision"
    else
        project="${FOSSA_PROJECT:-$name}"
        revision="$base_revision-$name${version:+-$version}"
    fi
    echo "→ $(basename "$f")  project=$project  revision=$revision"
    if ! fossa sbom analyze "$f" --project "$project" --revision "$revision" --force-rescan; then
        echo "::warning::FOSSA 拒绝了 $(basename "$f")（多为未开 SBOM import 的 Enterprise 特性），不阻断构建" >&2
        failed=$((failed + 1))
    fi
done

if [ "$failed" -gt 0 ]; then
    echo "::warning::$failed 个 SBOM 未上传成功，其余已完成"
fi
echo "SBOM 上传结束"
