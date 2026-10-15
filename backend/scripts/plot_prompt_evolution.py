"""
提示词工程图表生成器

从 `backend/eval_data/` 下的评测报告 JSON **直接读取**数字作图，不手工填写任何数值——
图上每个点都能追回到某份报告文件，避免「图里的数字是哪来的」这类质疑。

产出四张 300dpi PNG 到 `docs/figures/`，供《提示词工程完整记录》引用：

    fig_01_版本迭代.png      关系/实体 F1 随提示词版本的走势（含玩具规模→真实章节的断裂）
    fig_02_错误收敛.png      v1.2→v1.5 四类错误的数量收敛
    fig_03_泛化落差.png      开发集 vs 三章封存集的关系 F1，叠加赛题 0.70 阈值线
    fig_04_分类型F1.png      按关系类型对比开发集与三章封存集的 F1

用法（backend 目录下）：

    python scripts/plot_prompt_evolution.py
    python scripts/plot_prompt_evolution.py --out-dir ../docs/figures

依赖 matplotlib（已在 backend/requirements.txt 中声明为 matplotlib==3.10.7）。
Linux 上若无中文字体会渲染成方块，脚本会打印警告。
"""
import argparse
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EVAL = "eval_data"

# 玩具规模（708 字节示例文本）的两个数据点不在 eval_data 里——它们来自早期的
# test_extraction_accuracy.py，早于本评测体系建立。单独标注，不与真实章节的曲线混画。
TOY = [("v1.0", 1.0000, 0.4667), ("v1.1", 1.0000, 0.9333)]

DEV_REPORTS = [
    ("v1.2", "eval_report_第7章_树_v12基线.json"),
    ("v1.3", "eval_report_第7章_树_v13.json"),
    ("v1.4", "eval_report_第7章_树_v14.json"),
    ("v1.5", "eval_report_第7章_树_v15.json"),
]

SEALED_REPORTS = [
    ("物理·第2章", "eval_report_物理_第2章_运动学_v15_人工版.json"),
    ("数据结构·第2章", "eval_report_数据结构_第2章_复杂度分析_v15_人工版.json"),
    ("化学·第2章", "eval_report_化学_第2章_原子分子与离子_v15_人工版.json"),
]

DEV_LABEL = "开发集\n第7章·树"

# 赛题硬性指标
THRESHOLD = 0.70

C_DEV = "#2E5BFF"
C_SEALED = "#E6543A"
C_TOY = "#9AA5B1"
C_THRESH = "#E6A23C"
ERR_COLORS = ["#E6543A", "#E6A23C", "#8E6FD8", "#2E5BFF"]


def configure_font() -> str | None:
    """选一个可用的中文字体；找不到就返回 None（图上的中文会变方块）。"""
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC",
                 "Source Han Sans SC", "WenQuanYi Zen Hei"]:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return name
    return None


def load(name):
    path = os.path.join(EVAL, name)
    if not os.path.isfile(path):
        raise SystemExit(f"✗ 找不不到报告文件：{path}（需在 backend/ 目录下运行）")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dev_series():
    out = []
    for ver, fname in DEV_REPORTS:
        d = load(fname)
        st = d["stability"]
        out.append({
            "ver": ver,
            "entity_f1": st["entity_f1"]["mean"],
            "rel_f1": st["relation_primary_f1"]["mean"],
            "rel_f1_std": st["relation_primary_f1"].get("std"),
            "errors": {k: v["mean"] for k, v in d["error_taxonomy_across_runs"].items()},
            "by_type": {t: (v.get("micro") or {}).get("f1", 0.0)
                        for t, v in d["summary"]["relation_by_type"].items()},
        })
    return out


def sealed_series():
    out = []
    for label, fname in SEALED_REPORTS:
        d = load(fname)
        st = d["stability"]
        out.append({
            "label": label,
            "entity_f1": st["entity_f1"]["mean"],
            "rel_f1": st["relation_primary_f1"]["mean"],
            "rel_f1_std": st["relation_primary_f1"].get("std"),
            "by_type": {t: (v.get("micro") or {}).get("f1", 0.0)
                        for t, v in d["summary"]["relation_by_type"].items()},
        })
    return out


def fig_iteration(dev, out_dir):
    """图 1：版本迭代。真实章节画折线，玩具规模单点标注——两者规模差 20 倍，不能连成一条线。"""
    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    # 玩具规模占 0/1 两个位置，真实章节占 2~5，中间留一条分界线
    toy_x = [0, 1]
    dev_x = [2, 3, 4, 5]
    labels = [t[0] for t in TOY] + [d["ver"] for d in dev]

    rel = [d["rel_f1"] for d in dev]
    std = [d["rel_f1_std"] or 0 for d in dev]

    ax.errorbar(dev_x, rel, yerr=std, marker="o", ms=8, lw=2.4, capsize=5,
                color=C_DEV, label="关系 F1（真实章节，三轮均值±标准差）")
    ax.plot(dev_x, [d["entity_f1"] for d in dev], marker="s", ms=7, lw=2,
            ls="--", color="#7FA0FF", label="实体 F1（真实章节）")

    ax.axhline(THRESHOLD, color=C_THRESH, ls=":", lw=1.8)
    ax.text(5.15, THRESHOLD + 0.025, "赛题要求 0.70",
            color=C_THRESH, fontsize=9, ha="right")

    # 玩具规模：空心菱形 + 灰色，明确它是另一套数据
    ax.scatter(toy_x, [t[2] for t in TOY], marker="D", s=70,
               facecolors="none", edgecolors=C_TOY, lw=1.8,
               label="关系 F1（708 字节玩具文本，非同一数据集）")
    ax.scatter(toy_x, [t[1] for t in TOY], marker="D", s=60,
               facecolors="none", edgecolors=C_TOY, lw=1.4, alpha=0.55)
    for i, (ver, ent_f1, rel_f1) in enumerate(TOY):
        ax.annotate(f"{rel_f1:.4f}", (i, rel_f1), textcoords="offset points",
                    xytext=(12, 4), fontsize=8.2, color=C_TOY)

    # 数据集分界线（两个数据集的区别已写进 legend，这里不再重复标注）
    ax.axvline(1.5, color="#C6CDD6", ls="-", lw=1.2)

    ax.set_xticks(toy_x + dev_x)
    ax.set_xticklabels(labels)
    ax.set_ylim(-0.03, 1.08)
    ax.set_xlim(-0.6, 5.6)
    ax.set_ylabel("F1")
    ax.set_xlabel("提示词版本")
    ax.set_title("P1 知识抽取：版本迭代效果\n"
                 "玩具规模上「已达标」是假象；放大到真实章节后 v1.2 基线仅 0.1614",
                 fontsize=12, pad=12)
    ax.grid(alpha=0.25, ls="--", lw=0.6)
    # 曲线从左下升到右上，右下角是整块空白区，legend 放这里不遮数据
    ax.legend(fontsize=8.6, loc="lower right", framealpha=0.95)
    fig.tight_layout()
    p = os.path.join(out_dir, "fig_01_版本迭代.png")
    fig.savefig(p, dpi=300)
    plt.close(fig)
    return p


def fig_errors(dev, out_dir):
    """图 2：四类错误随版本收敛。"""
    order = [("fabricated", "① 臆造（节点对不在 Gold）"),
             ("direction_reversed", "② 方向颠倒"),
             ("type_confused", "③ 类型混淆"),
             ("missed_core", "⑤ 完全漏抽（Core）")]
    fig, ax = plt.subplots(figsize=(8.2, 4.4))
    vers = [d["ver"] for d in dev]
    n = len(order)
    w = 0.8 / n
    base = range(len(vers))
    for i, (key, label) in enumerate(order):
        vals = [d["errors"].get(key, 0.0) for d in dev]
        pos = [b - 0.4 + w * (i + 0.5) for b in base]
        bars = ax.bar(pos, vals, width=w * 0.92, color=ERR_COLORS[i], label=label)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.6, f"{v:.1f}",
                    ha="center", fontsize=7.6)
    ax.set_xticks(list(base))
    ax.set_xticklabels(vers)
    ax.set_xlabel("提示词版本")
    ax.set_ylabel("条数（三轮均值）")
    ax.set_title("P1 抽取错误归因的收敛（开发集第 7 章·树）\n"
                 "每次修复都由上一轮归因驱动，而非事前推测", fontsize=12, pad=12)
    ax.grid(axis="y", alpha=0.25, ls="--", lw=0.6)
    ax.legend(fontsize=8.6)
    ax.set_ylim(0, max(d["errors"].get("fabricated", 0) for d in dev) * 1.22)
    fig.tight_layout()
    p = os.path.join(out_dir, "fig_02_错误收敛.png")
    fig.savefig(p, dpi=300)
    plt.close(fig)
    return p


def fig_gap(dev, sealed, out_dir):
    """图 3：开发集 → 封存集的泛化落差。这张图是这份文档最该被看到的一张。"""
    names = [DEV_LABEL] + [s["label"] for s in sealed]
    rel = [dev[-1]["rel_f1"]] + [s["rel_f1"] for s in sealed]
    ent = [dev[-1]["entity_f1"]] + [s["entity_f1"] for s in sealed]
    colors = [C_DEV] + [C_SEALED] * len(sealed)

    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    xs = range(len(names))
    b1 = ax.bar([x - 0.2 for x in xs], rel, width=0.38, color=colors, label="关系 F1")
    b2 = ax.bar([x + 0.2 for x in xs], ent, width=0.38, color=colors, alpha=0.38,
                label="实体 F1")
    for bars in (b1, b2):
        for b in bars:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.015,
                    f"{b.get_height():.4f}", ha="center", fontsize=8.2)

    ax.axhline(THRESHOLD, color=C_THRESH, ls=":", lw=2)
    # 标签放在第一、二组之间的空隙里，避免压在柱子上
    ax.text(0.52, THRESHOLD + 0.035, "赛题要求 0.70", color=C_THRESH,
            fontsize=9.5, ha="left", weight="bold",
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85))
    ax.axvspan(-0.5, 0.5, color=C_DEV, alpha=0.06)

    ax.set_xticks(list(xs))
    ax.set_xticklabels(names, fontsize=9.5)
    ax.set_ylim(0, 1.06)
    ax.set_ylabel("F1（三轮均值）")
    ax.set_title("泛化落差：开发集的高分没有迁移到封存集\n"
                 "三章封存集的关系 F1 全部低于 0.70，实体 F1 仍在 0.81~0.86",
                 fontsize=12, pad=12)
    ax.grid(axis="y", alpha=0.25, ls="--", lw=0.6)
    ax.legend(fontsize=9)
    fig.tight_layout()
    p = os.path.join(out_dir, "fig_03_泛化落差.png")
    fig.savefig(p, dpi=300)
    plt.close(fig)
    return p


def fig_by_type(dev, sealed, out_dir):
    """图 4：按关系类型的 F1 对比。"""
    types = ["CONTAINS", "RELATED_TO", "APPLIES_TO"]
    groups = [("开发集 第7章·树", dev[-1]["by_type"], C_DEV)]
    for s in sealed:
        groups.append((s["label"], s["by_type"], C_SEALED))

    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    n = len(groups)
    w = 0.8 / n
    base = range(len(types))
    for i, (label, bt, color) in enumerate(groups):
        vals = [bt.get(t, 0.0) for t in types]
        pos = [b - 0.4 + w * (i + 0.5) for b in base]
        bars = ax.bar(pos, vals, width=w * 0.9, color=color,
                      alpha=1.0 if i == 0 else 0.42 + 0.16 * i, label=label)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.015, f"{v:.2f}",
                    ha="center", fontsize=7.2, rotation=0)
    ax.set_xticks(list(base))
    ax.set_xticklabels(types)
    ax.set_ylim(0, 1.06)
    ax.set_ylabel("F1（第 1 轮，微平均）")
    ax.set_title("按关系类型看泛化：CONTAINS 最稳，RELATED_TO / APPLIES_TO 在封存集上近乎失效",
                 fontsize=12, pad=12)
    ax.grid(axis="y", alpha=0.25, ls="--", lw=0.6)
    ax.legend(fontsize=8.6)
    fig.tight_layout()
    p = os.path.join(out_dir, "fig_04_分类型F1.png")
    fig.savefig(p, dpi=300)
    plt.close(fig)
    return p


def main():
    ap = argparse.ArgumentParser(description="生成《提示词工程完整记录》的图表")
    ap.add_argument("--out-dir", default="../docs/figures")
    args = ap.parse_args()

    font = configure_font()
    if font is None:
        print("⚠ 未找到中文字体，图上的中文会渲染成方块。Windows 一般自带 Microsoft YaHei。")
    else:
        print(f"使用中文字体：{font}")

    os.makedirs(args.out_dir, exist_ok=True)
    dev = dev_series()
    sealed = sealed_series()

    for fn in (fig_iteration, fig_errors):
        print("  已生成", fn(dev, args.out_dir))
    for fn in (fig_gap, fig_by_type):
        print("  已生成", fn(dev, sealed, args.out_dir))

    print("\n数据来源（图上每个点都可以在这些文件里核对）：")
    print(f"  开发集：{EVAL}/eval_report_第7章_树_v1{{2,3,4,5}}*.json → stability.*.mean")
    print(f"  封存集：{EVAL}/eval_report_{{物理,数据结构,化学}}_*_v15_人工版.json")
    print(f"  玩具规模 v1.0/v1.1 的两个点来自早期 test_extraction_accuracy.py，"
          f"不在 eval_data 中，图中已单独标注为「非同一数据集」")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
