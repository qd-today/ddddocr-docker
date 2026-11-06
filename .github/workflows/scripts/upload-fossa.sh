#!/bin/sh
# 把构建产物里的随包原生依赖交给 FOSSA。
#
# 为什么不用 FOSSA 默认的 pip 策略扫仓库：它读的是 lockfile，看不到 auditwheel 收进
# <dist>.libs/ 的原生库。而这些库恰好是许可证风险的所在（LGPL-3.0 / LGPL-2.1），必须
# 显式告诉 FOSSA。直接传 SBOM 又需要 Enterprise 订阅，所以默认走 fossa-deps 这条路。
#
# 两种模式，默认 analyze：
#
#   FOSSA_MODE=analyze（默认）—— 不需要 Enterprise
#     compliance.py 在 wheelhouse 根目录生成的 fossa-deps.yml，跑 fossa analyze：
#       * referenced-dependencies(type: apk)：给 apk 包名 + 版本 + 架构，FOSSA 拿这个 ref
#         去**它自己的知识库**查许可证**和漏洞**。referenced 是唯一带漏洞数据的类型，
#         也就是说「这是什么许可证」是 FOSSA 自己得出的结论，不是我们喂给它的。
#       * custom-dependencies：curl / ngtcp2 / OpenBLAS 这类自编库没有 apk 出处，
#         只能给许可证（KNOWN 表核过的值）。这类没有漏洞数据。
#     整条链只用普通 token。
#
#   FOSSA_MODE=sbom —— 需要 Enterprise
#     直传 CycloneDX，粒度到每个 wheel。SBOM import 是 Enterprise 特性，普通订阅返回
#     403，所以只在显式设置时才走。
#
# 环境变量：
#   FOSSA_API_KEY   必填；缺省则跳过（fork PR 拿不到 secret，属正常情况）
#   FOSSA_MODE      analyze（默认）| sbom
#   FOSSA_PROJECT   项目 locator，CI 传 git+github.com/qd-today/<repo>
#   FOSSA_REVISION  版本前缀，建议 "<tag>+<arch>"；默认 git sha
#   WHEELHOUSE      wheelhouse 目录，默认 dist/wheels
#   SBOM_GLOB       sbom 模式的 SBOM 搜索路径，默认 $WHEELHOUSE/sbom/*.cdx.json
#
# 上传失败只告警不阻断：FOSSA 侧抖动不该拦发布，而合规证据本身已经随 wheelhouse 发出去
# 了（NOTICE / SOURCE-OFFER / licenses / sbom），FOSSA 只是让它在平台上可见。
set -eu

if [ -z "${FOSSA_API_KEY:-}" ]; then
    echo "未设置 FOSSA_API_KEY，跳过 FOSSA 上传"
    exit 0
fi

wheelhouse="${WHEELHOUSE:-dist/wheels}"
mode="${FOSSA_MODE:-analyze}"
project="${FOSSA_PROJECT:-}"
revision="${FOSSA_REVISION:-$(git rev-parse --short HEAD 2>/dev/null || echo unknown)}"

if ! command -v fossa >/dev/null 2>&1; then
    echo "安装 fossa-cli"
    curl -sSL -H 'Cache-Control: no-cache' \
        https://raw.githubusercontent.com/fossas/fossa-cli/master/install-latest.sh | bash
    PATH="$HOME/.local/bin:$PATH"
    export PATH
fi
fossa --version || true

# --------------------------------------------------------------------------- #
# analyze：非 Enterprise 路径
# --------------------------------------------------------------------------- #
if [ "$mode" != "sbom" ]; then
    deps="$wheelhouse/fossa-deps.yml"
    if [ ! -f "$deps" ]; then
        echo "::warning::$deps 不存在：--compliance 没跑，或者 wheel 里没有原生依赖，跳过"
        exit 0
    fi
    echo "→ fossa analyze ${wheelhouse}（依赖文件 ${deps}）"
    set -- analyze "$wheelhouse" --fossa-deps-file "$deps" --revision "$revision"
    if [ -n "$project" ]; then
        set -- "$@" --project "$project"
    fi
    if fossa "$@"; then
        echo "FOSSA 上传结束（project=${project:-<git remote>} revision=${revision}）"
    else
        echo "::warning::fossa analyze 上传失败（查 token 权限与项目 locator），不阻断构建" >&2
    fi
    exit 0
fi

# --------------------------------------------------------------------------- #
# sbom：Enterprise 路径
# --------------------------------------------------------------------------- #
sbom_glob="${SBOM_GLOB:-$wheelhouse/sbom/*.cdx.json}"
set -- $sbom_glob
found=0
for f in "$@"; do
    [ -f "$f" ] && found=$((found + 1))
done
if [ "$found" -eq 0 ]; then
    echo "::warning::$sbom_glob 里没有 SBOM，跳过"
    exit 0
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

# 项目/版本号的映射：
#   每个 wheel 一条 revision   <FOSSA_REVISION>-<发行名>-<版本>
#   wheelhouse 汇总一条        <FOSSA_REVISION>
# 这样同一个项目下既有汇总视角，也能单独看某个 wheel 的依赖，revision 之间不会互相覆盖
# （FOSSA 的 (project, revision) 是唯一键，同一 revision 反复上传只会保留最后一次）。
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
        rev="$revision"
    else
        rev="$revision-$name${version:+-$version}"
    fi
    echo "→ $(basename "$f")  project=${project:-$name}  revision=$rev"
    set -- sbom analyze "$f" --revision "$rev" --force-rescan
    if [ -n "$project" ]; then
        set -- "$@" --project "$project"
    fi
    if ! fossa "$@"; then
        echo "::warning::FOSSA 拒绝了 $(basename "$f")（多为未开 SBOM import 的 Enterprise 特性），不阻断构建" >&2
        failed=$((failed + 1))
    fi
done

if [ "$failed" -gt 0 ]; then
    echo "::warning::$failed 个 SBOM 未上传成功，其余已完成"
fi
echo "SBOM 上传结束"
