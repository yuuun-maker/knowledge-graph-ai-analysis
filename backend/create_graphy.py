"""
A10 知识抽取评测结果可视化生成器

用途
----
读取 eval_accuracy.py 生成的评测 JSON，生成可直接放进实验报告 / 比赛材料的：
    - PNG 图（<output-dir>/figures/）
    - CSV 表（<output-dir>/tables/，UTF-8-BOM，Excel 直接打开不乱码）
    - Markdown 表（<output-dir>/tables/）

重要原则
--------
1. 本文件绝不调用 LLM
2. 本文件绝不修改 Gold / Pred
3. 本文件只读取已有评测结果
4. 所有数字直接来自 eval_accuracy.py 输出的 JSON，不手工输入
5. 报告里没有的字段明确跳过并提示，绝不静默填 0
   （静默填 0 会让"这一列没算"伪装成"这一列是 0"，评测材料里这是最危险的一种错）

用法（backend 目录下）
----------------------
    python create_graphy.py --report eval_data/eval_report_第7章_树.json \\
                            --output-dir eval_data/visuals

依赖
----
matplotlib（已写进 backend/requirements.txt，装依赖时会一起装上）。
中文标签还需系统字体：Windows 自带 Microsoft YaHei / SimHei 即可，
Linux 需另装 fonts-noto-cjk，否则图中的中文会渲染成方块。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import matplotlib

# 必须在 import pyplot 之前指定后端：本脚本只落盘不弹窗，
# 用 Agg 才能在无显示环境（服务器 / CI）下正常出图
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager

# Windows 控制台默认 GBK，直接 print 中文表格会 UnicodeEncodeError。
# stderr 同样要设：报错信息（如"找不到评测报告"）走的就是 stderr。
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# ============================================================
# 字体：中文字形
# ============================================================

# 按优先级排列的中文字体候选。
# matplotlib 默认字体 DejaVu Sans 不含 CJK 字形，中文会渲染成空心方块（tofu），
# 且只在 stderr 抛一条 UserWarning —— 图能生成、看起来"成功了"，
# 但放进报告就是一堆方框。故此处显式选择字体。
_CJK_FONT_CANDIDATES = (
    "Microsoft YaHei",     # Windows 默认，最优先
    "SimHei",
    "SimSun",
    "Noto Sans CJK SC",    # Linux
    "Source Han Sans SC",
    "WenQuanYi Zen Hei",
    "Arial Unicode MS",    # macOS
)


def configure_font() -> str | None:
    """选择可用的中文字体并写入 rcParams。返回选中的字体名，找不到返回 None。"""
    available = {f.name for f in font_manager.fontManager.ttflist}

    for name in _CJK_FONT_CANDIDATES:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            # 中文字体通常不含 U+2212（真正的减号），不改这个的话负号会变方块
            plt.rcParams["axes.unicode_minus"] = False
            return name

    return None


# ============================================================
# 输出描述：表 / 图 / 区块
# ============================================================
#
# 五个 generate_* 函数的骨架完全相同（取值 → 组行 → 写 CSV → 写 Markdown
# → 画图 → savefig → close），差别只在"取哪些数、画什么形状"。
# 下面用三个 dataclass 把"数据"与"落盘"分开：builder 只负责取值与组表，
# 由 emit_block 统一落盘。新增一张图表 = 新增一个 builder，不再复制骨架。

@dataclass
class Table:
    """一张表：同一份行数据，同时输出 CSV 与 Markdown。"""
    stem: str
    headers: list[str]
    rows: list[list[Any]]


@dataclass
class Series:
    """图中一条数据系列。errors 给定时画误差棒（用于跨轮 std）。"""
    label: str
    values: list[float]
    errors: list[float] | None = None


@dataclass
class Chart:
    """一张图。kind 决定画法，其余字段为通用样式。"""
    stem: str
    kind: str                       # bar | grouped_bar | stacked_bar | line
    title: str
    ylabel: str
    categories: list[str]
    series: list[Series]
    ylim: tuple[float, float] | None = (0.0, 1.05)
    xtick_rotation: int = 0
    value_labels: bool = False      # 在柱顶标数值（报告用图建议开）
    footnote: str | None = None     # 图下方小字说明
    inactive: list[bool] | None = None   # 标记"无 Gold 样本"的分类，画斜线区分
    figsize: tuple[float, float] = (10.0, 6.0)


@dataclass
class Block:
    """一个输出区块 = 一张表 +（可选的）一张图。"""
    title: str
    table: Table | None = None
    chart: Chart | None = None
    note: str | None = None         # 降级 / 跳过原因，会在控制台打印


# ============================================================
# 数值与落盘
# ============================================================

def fmt(value: Any) -> str:
    """表格单元格格式化：浮点保留 4 位，其余原样，None 显示为破折号。"""
    if value is None:
        return "—"
    # bool 必须在 int 之前判：bool 是 int 的子类，否则 True 会显示成 "True" 之外的怪值
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _label_num(value: float) -> str:
    """柱顶数值标签：整数就写成整数。
    "3.0000" 这种写法在计数类图里既占地方又让人以为是精度指标。

    注意 int 与 float 都要判：计数类从 JSON 读出来是 int（74），
    指标类才是 float（0.8675），只判 float 会让计数显示成 "74.0000"。"""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return f"{value:.4f}"


def write_csv(path: Path, headers: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig：带 BOM，Excel 双击打开中文不乱码
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def write_markdown_table(path: Path, headers: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(x) for x in row) + " |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _save_chart(chart: Chart, figures_dir: Path) -> Path:
    """按 chart.kind 画图并落盘。四种图型共用同一套坐标轴/网格/图例设置。"""
    fig, ax = plt.subplots(figsize=chart.figsize)
    x = list(range(len(chart.categories)))

    if chart.kind == "line":
        for series in chart.series:
            if series.errors:
                ax.errorbar(
                    x[: len(series.values)], series.values, yerr=series.errors,
                    marker="o", capsize=4, label=series.label,
                )
            else:
                ax.plot(x[: len(series.values)], series.values, marker="o", label=series.label)

    elif chart.kind == "grouped_bar":
        n = max(len(chart.series), 1)
        width = 0.8 / n
        for index, series in enumerate(chart.series):
            # 让整组柱子以刻度为中心：第 i 根偏移 (i - (n-1)/2) * width
            offset = (index - (n - 1) / 2) * width
            bars = ax.bar(
                [i + offset for i in x], series.values, width,
                yerr=series.errors, capsize=3, label=series.label,
            )
            if chart.value_labels:
                # 有误差棒时标签要抬到棒顶之上，否则数字会被误差棒竖线穿过
                tops = [
                    value + (series.errors[i] if series.errors else 0.0)
                    for i, value in enumerate(series.values)
                ]
                for rect, value, top in zip(bars, series.values, tops):
                    ax.annotate(
                        _label_num(value), (rect.get_x() + rect.get_width() / 2, top),
                        ha="center", va="bottom", fontsize=8,
                        xytext=(0, 2), textcoords="offset points",
                    )

    elif chart.kind == "stacked_bar":
        bottom = [0.0] * len(chart.categories)
        for series in chart.series:
            bars = ax.bar(x, series.values, 0.6, bottom=bottom, label=series.label)
            if chart.value_labels:
                for rect, value, base in zip(bars, series.values, bottom):
                    if value:  # 0 段不标，否则数字会叠在图例线上
                        ax.annotate(
                            _label_num(value),
                            (rect.get_x() + rect.get_width() / 2, base + value / 2),
                            ha="center", va="center", fontsize=8,
                        )
            bottom = [b + v for b, v in zip(bottom, series.values)]

    else:  # bar
        series = chart.series[0]
        colors = None
        if chart.inactive:
            # 无 Gold 样本的分类单独上色，避免"F1=0"被读成"模型全错"
            colors = ["#c9ced6" if flag else "#4c78a8" for flag in chart.inactive]
        bars = ax.bar(x, series.values, 0.6, color=colors, yerr=series.errors, capsize=3)
        if chart.inactive:
            for rect, flag in zip(bars, chart.inactive):
                if flag:
                    rect.set_hatch("//")
                    rect.set_edgecolor("white")
        if chart.value_labels:
            tops = [
                value + (series.errors[i] if series.errors else 0.0)
                for i, value in enumerate(series.values)
            ]
            for rect, value, top, flag in zip(
                bars, series.values, tops, chart.inactive or [False] * len(x)
            ):
                ax.annotate(
                    "无 Gold 样本" if flag else _label_num(value),
                    (rect.get_x() + rect.get_width() / 2, top),
                    ha="center", va="bottom", fontsize=8,
                    xytext=(0, 2), textcoords="offset points",
                )

    ax.set_xticks(x)
    ax.set_xticklabels(
        chart.categories,
        rotation=chart.xtick_rotation,
        ha="right" if chart.xtick_rotation else "center",
    )
    ax.set_title(chart.title)
    ax.grid(axis="y", alpha=0.25)

    if chart.ylabel:
        # 中文竖排标签不能直接用 set_ylabel(rotation=90)：
        # matplotlib 3.10 + Agg 下中文字形会互相重叠成一团墨（Microsoft YaHei 与
        # SimHei 都一样，加 rotation_mode="anchor" 也无效）。
        # 改用水平标签放在 y 轴顶端 —— 这也是中文期刊图表的通行样式。
        ax.set_ylabel("")
        ax.annotate(
            chart.ylabel,
            xy=(0.0, 1.0), xycoords="axes fraction",
            xytext=(0, 8), textcoords="offset points",
            ha="left", va="bottom", fontsize=10,
        )

    if chart.ylim:
        ax.set_ylim(*chart.ylim)

    # 只有一条系列时不画图例（图例反而占地方）；折线图即使一条也保留
    if len(chart.series) > 1 or chart.kind == "line":
        ax.legend()

    if chart.footnote:
        fig.text(0.5, -0.02, chart.footnote, ha="center", fontsize=8, color="#555555")

    fig.tight_layout()

    path = figures_dir / f"{chart.stem}.png"
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)   # 必须关：循环出图时不关会累积 ~20 个 figure 触发警告并吃内存
    return path


def emit_block(block: Block, output_dir: Path) -> tuple[list[Path], dict[str, Any]]:
    """把一个 Block 落盘。返回 (生成的文件路径, 供控制台打印的摘要)。"""
    produced: list[Path] = []
    summary: dict[str, Any] = {"title": block.title, "note": block.note}

    if block.table:
        tables_dir = output_dir / "tables"
        csv_path = tables_dir / f"{block.table.stem}.csv"
        md_path = tables_dir / f"{block.table.stem}.md"
        write_csv(csv_path, block.table.headers, block.table.rows)
        write_markdown_table(md_path, block.table.headers, block.table.rows)
        produced += [csv_path, md_path]
        summary["table"] = block.table.stem
        summary["rows"] = len(block.table.rows)

    if block.chart:
        produced.append(_save_chart(block.chart, output_dir / "figures"))
        summary["figure"] = block.chart.stem

    return produced, summary


# ============================================================
# 取值助手
# ============================================================

def _stability_mean(report: dict[str, Any], key: str) -> float:
    return report["stability"][key]["mean"]


def _stability_std(report: dict[str, Any], key: str) -> float:
    # std 可能缺失（旧报告），缺失返回 0 即不画误差棒
    return report["stability"][key].get("std", 0.0) or 0.0


def _taxonomy_mean(report: dict[str, Any], key: str) -> float | None:
    """读某个错误类别的跨轮均值。类别不存在时返回 None（由调用方决定跳过或提示）。"""
    item = report["error_taxonomy_across_runs"].get(key)
    if not isinstance(item, dict):
        return None
    return item.get("mean")


# 已计分关系上的错误类别 —— 这些是"必然存在"的，缺失说明报告对不上，需要提示。
_SCORED_ERROR_KEYS: tuple[tuple[str, str], ...] = (
    ("fabricated", "臆造"),
    ("direction_reversed", "方向颠倒"),
    ("type_confused", "类型混淆"),
    ("missed_core", "完全漏抽"),
)

# 计分前丢弃的原因 —— 只有新版 eval_accuracy.py 才写这些字段，
# 旧报告缺失属正常，静默跳过即可（不当作错误）。
# 代号与 eval_accuracy.py 的 DROP_REASON_LABELS 对齐，勿单方面改名。
_DROP_REASON_KEYS: tuple[tuple[str, str], ...] = (
    ("invalid_relation_type", "关系类型非法"),
    ("invalid_endpoint", "端点为空"),
    ("synonym_split", "同义拆分(归一化后自环)"),
    ("dangling_endpoint", "悬空端点"),
    ("duplicate", "重复三元组"),
    ("low_confidence", "置信度低于阈值"),
)


# ============================================================
# 区块 1：总体 P / R / F1
# ============================================================

def build_main_metrics(report: dict[str, Any]) -> Block:
    items = [
        ("实体", "entity"),
        ("关系主指标", "relation_primary"),
        ("关系 Core", "relation_core"),
        ("关系 Full", "relation_full"),
    ]

    labels = [label for label, _ in items]
    precision = [_stability_mean(report, f"{key}_precision") for _, key in items]
    recall = [_stability_mean(report, f"{key}_recall") for _, key in items]
    f1 = [_stability_mean(report, f"{key}_f1") for _, key in items]

    rows = [
        [label, fmt(p), fmt(r), fmt(f)]
        for label, p, r, f in zip(labels, precision, recall, f1)
    ]

    chart = Chart(
        stem="figure_01_main_metrics",
        kind="grouped_bar",
        title="知识抽取总体指标（跨轮均值）",
        ylabel="得分",
        categories=labels,
        series=[
            # 误差棒 = 跨轮标准差。eval_accuracy.py 已经算了 std，
            # 只画均值等于把"这个数稳不稳"的信息丢掉，报告里会说不清可信度。
            Series("Precision", precision, [_stability_std(report, f"{k}_precision") for _, k in items]),
            Series("Recall", recall, [_stability_std(report, f"{k}_recall") for _, k in items]),
            Series("F1", f1, [_stability_std(report, f"{k}_f1") for _, k in items]),
        ],
        value_labels=True,
        footnote=f"误差棒为跨 {report.get('runs', '?')} 轮标准差；关系主指标 = 对 Full 算 P、对 Core 算 R（双层口径）",
    )

    return Block(
        title="总体指标",
        table=Table("table_01_main_metrics", ["指标", "Precision", "Recall", "F1"], rows),
        chart=chart,
    )


# ============================================================
# 区块 2：按关系类型的 F1
# ============================================================

def build_relation_type_metrics(report: dict[str, Any]) -> Block:
    relation_summary = report["summary"]["relation_by_type"]

    labels: list[str] = []
    p_values: list[float] = []
    r_values: list[float] = []
    f1_values: list[float] = []
    gold_values: list[int] = []
    pred_values: list[int] = []

    for relation_type in report.get("relation_types", list(relation_summary.keys())):
        item = relation_summary.get(relation_type)
        if item is None:
            continue
        metrics = item["micro"]
        labels.append(relation_type)
        p_values.append(metrics["precision"])
        r_values.append(metrics["recall"])
        f1_values.append(metrics["f1"])
        gold_values.append(item["gold_total"])
        pred_values.append(item["pred_total"])

    rows = [
        [label, gold, pred, fmt(p), fmt(r), fmt(f)]
        for label, gold, pred, p, r, f in zip(
            labels, gold_values, pred_values, p_values, r_values, f1_values
        )
    ]

    # gold_total=0 的类型，P/R/F1 全是 0 且恒为 0（分母为 0）。
    # 若不标出来，报告读者会把"本数据集没有这类关系"误读成"模型这类全错"。
    inactive = [gold == 0 for gold in gold_values]
    footnotes = []
    if any(inactive):
        names = "、".join(l for l, flag in zip(labels, inactive) if flag)
        footnotes.append(
            f"标为「无 Gold 样本」的（{names}）在 Gold 中条数为 0，"
            "P/R/F1 因分母为 0 而恒等于 0，不代表模型在这类关系上全错"
        )

    chart = Chart(
        stem="figure_02_relation_type_f1",
        kind="bar",
        title="各关系类型 F1（微平均）",
        ylabel="F1",
        categories=labels,
        series=[Series("F1", f1_values)],
        value_labels=True,
        inactive=inactive,
        footnote="；".join(footnotes) or None,
        figsize=(10.0, 6.5),
    )

    return Block(
        title="关系类型表现",
        table=Table(
            "table_02_relation_types",
            ["关系类型", "Gold", "Pred", "Precision", "Recall", "F1"],
            rows,
        ),
        chart=chart,
    )


# ============================================================
# 区块 3：多轮稳定性
# ============================================================

def build_stability(report: dict[str, Any]) -> Block:
    run_count = report["runs"]
    entity_f1 = report["stability"]["entity_f1"].get("values", [])
    primary_f1 = report["stability"]["relation_primary_f1"].get("values", [])
    core_f1 = report["stability"]["relation_core_f1"].get("values", [])

    # 旧报告可能没有 values（只有 mean/std）。此时用轮数补零没有意义，
    # 直接按实际可用长度截断，避免 IndexError。
    available = min(run_count, len(entity_f1), len(primary_f1), len(core_f1))
    if available < 1:
        return Block(
            title="多轮稳定性",
            note="报告不含逐轮 values 字段，跳过稳定性图（仅旧版报告会出现）",
        )

    rows = [
        [i + 1, fmt(entity_f1[i]), fmt(primary_f1[i]), fmt(core_f1[i])]
        for i in range(available)
    ]

    chart = Chart(
        stem="figure_03_stability",
        kind="line",
        title="多轮运行的 F1 稳定性",
        ylabel="F1",
        categories=[f"第{i + 1}轮" for i in range(available)],
        series=[
            Series("实体 F1", entity_f1[:available]),
            Series("关系主指标 F1", primary_f1[:available]),
            Series("关系 Core F1", core_f1[:available]),
        ],
    )

    note = None
    if available < run_count:
        note = f"报告声明 {run_count} 轮，但逐轮数据只有 {available} 轮，已按实际长度出图"

    return Block(
        title="多轮稳定性",
        table=Table(
            "table_03_stability",
            ["Run", "Entity F1", "Relation Primary F1", "Relation Core F1"],
            rows,
        ),
        chart=chart,
        note=note,
    )


# ============================================================
# 区块 4：已计分关系的错误归因
# ============================================================
#
# 注意：本区块只放"已经进入计分的关系"上的错误。
# 被丢弃在计分之前的关系（同义拆分、低置信度等）不在这里，见区块 6 ——
# 两者混在一起会重蹈把"阈值砍掉的"算进"模型漏抽的"的老问题。

def build_error_taxonomy(report: dict[str, Any]) -> Block:
    labels: list[str] = []
    values: list[float] = []
    missing: list[str] = []

    for key, label in _SCORED_ERROR_KEYS:
        mean = _taxonomy_mean(report, key)
        if mean is None:
            missing.append(key)
            continue
        labels.append(label)
        values.append(mean)

    if not labels:
        return Block(
            title="错误归因",
            note="报告中找不到任何已计分错误类别，请确认输入的是 eval_accuracy.py 的输出",
        )

    rows = [[label, fmt(value)] for label, value in zip(labels, values)]

    chart = Chart(
        stem="figure_04_error_taxonomy",
        kind="bar",
        title="已计分关系的错误归因（跨轮均值）",
        ylabel="跨轮平均条数",
        categories=labels,
        series=[Series("条数", values)],
        ylim=None,          # 计数无上界，不锁 0~1
        value_labels=True,
        footnote="仅统计进入计分的关系；计分前被丢弃的见 figure_06",
        figsize=(10.0, 6.5),
    )

    note = None
    if missing:
        note = f"报告缺少这些错误类别，已跳过：{'、'.join(missing)}"

    return Block(
        title="错误归因（已计分）",
        table=Table("table_04_error_taxonomy", ["错误类型", "跨轮平均条数"], rows),
        chart=chart,
        note=note,
    )


# ============================================================
# 区块 5：逐文档表现（至少 2 个文档时生成）
# ============================================================

def build_document_metrics(report: dict[str, Any]) -> Block:
    documents = report.get("documents", [])

    if len(documents) < 2:
        return Block(
            title="逐文档表现",
            note=f"报告只含 {len(documents)} 个文档，逐文档对比图无意义，跳过",
        )

    labels = [doc["text_id"] for doc in documents]
    entity_f1 = [doc["entity"]["f1"] for doc in documents]
    relation_f1 = [doc["relation_primary"]["f1"] for doc in documents]

    rows = [
        [
            doc["text_id"],
            fmt(doc["entity"]["f1"]),
            fmt(doc["relation_primary"]["f1"]),
            fmt(doc["relation_core"]["f1"]),
            fmt(doc["relation_direction_error_rate"]),
        ]
        for doc in documents
    ]

    chart = Chart(
        stem="figure_05_document_metrics",
        kind="grouped_bar",
        title="各文档的实体 / 关系 F1",
        ylabel="F1",
        categories=labels,
        series=[
            Series("实体 F1", entity_f1),
            Series("关系主指标 F1", relation_f1),
        ],
        xtick_rotation=30,
        value_labels=True,
        figsize=(12.0, 6.5),
    )

    return Block(
        title="逐文档表现",
        table=Table(
            "table_05_document_metrics",
            ["文档", "Entity F1", "Relation Primary F1", "Relation Core F1", "Direction Error Rate"],
            rows,
        ),
        chart=chart,
    )


# ============================================================
# 区块 6：计分前丢弃明细
# ============================================================

def build_drop_reasons(report: dict[str, Any]) -> Block:
    labels: list[str] = []
    values: list[float] = []

    for key, label in _DROP_REASON_KEYS:
        mean = _taxonomy_mean(report, key)
        if mean is None:
            continue
        labels.append(label)
        values.append(mean)

    if not labels:
        return Block(
            title="计分前丢弃",
            note="报告不含丢弃原因字段，跳过（旧版 eval_accuracy.py 的输出即如此）",
        )

    dropped_total = _taxonomy_mean(report, "dropped_total")
    rows = [[label, fmt(value)] for label, value in zip(labels, values)]
    if dropped_total is not None:
        rows.append(["合计", fmt(dropped_total)])

    footnotes = ["这些关系被抽取器或评测器在计分前丢弃，不计入 P/R/F1"]
    low_conf = _taxonomy_mean(report, "low_confidence")
    if low_conf is not None and low_conf > 0:
        # 这一条最值得盯：它是"模型抽到了、被系统自己的阈值砍掉"，
        # 若这些关系本是对的，会伪装成 missed_core，把"阈值太严"误诊成"模型召回低"
        footnotes.append(f"注意置信度丢弃 {fmt(low_conf)} 条：调阈值可能比调 Prompt 更快见效")

    chart = Chart(
        stem="figure_06_drop_reasons",
        kind="bar",
        title="计分前丢弃的关系（跨轮均值）",
        ylabel="跨轮平均条数",
        categories=labels,
        series=[Series("条数", values)],
        ylim=None,
        value_labels=True,
        footnote="；".join(footnotes),
        figsize=(11.0, 6.5),
    )

    return Block(
        title="计分前丢弃明细",
        table=Table("table_06_drop_reasons", ["丢弃原因", "跨轮平均条数"], rows),
        chart=chart,
    )


# ============================================================
# 区块 7：抽取侧对账（原始输出 vs 计分 vs 丢弃）
# ============================================================
#
# 恒等式：pred_raw_total == pred_total + dropped_total
# 对上了，才说明"少掉的那些关系"都有交代、没有凭空消失。

def build_reconciliation(report: dict[str, Any]) -> Block:
    rec = report.get("reconciliation")
    if not isinstance(rec, dict) or not rec.get("per_run"):
        return Block(
            title="抽取侧对账",
            note="报告不含 reconciliation 块，跳过（旧版 eval_accuracy.py 的输出即如此）",
        )

    per_run = rec["per_run"]
    rows = []
    for index, item in enumerate(per_run, start=1):
        rows.append([
            f"第{index}轮",
            item.get("raw"),
            item.get("scored"),
            item.get("dropped"),
            "✓" if item.get("reconciles") else "✗",
        ])

    # 原始输出总数在各轮不一致，故用合计行而不是均值——合计才是"账"。
    total_raw = sum(item.get("raw", 0) for item in per_run)
    total_scored = sum(item.get("scored", 0) for item in per_run)
    total_dropped = sum(item.get("dropped", 0) for item in per_run)
    rows.append([
        "合计",
        total_raw,
        total_scored,
        total_dropped,
        "✓" if rec.get("balanced_all_runs") else "✗",
    ])

    raw_source = rec.get("raw_source", "?")
    source_note = {
        "extractor": "原始计数来自抽取器上报（抽取侧精确记账）",
        "derived": "原始计数由评测器从预测文件反推（抽取侧未上报，仅供参考）",
    }.get(raw_source, f"原始计数来源未知：{raw_source}")

    chart = Chart(
        stem="figure_07_reconciliation",
        kind="stacked_bar",
        title="抽取侧对账：计分 + 丢弃 = 原始输出",
        ylabel="关系条数",
        categories=[f"第{i + 1}轮" for i in range(len(per_run))],
        series=[
            Series("计分", [item.get("scored", 0) for item in per_run]),
            Series("丢弃", [item.get("dropped", 0) for item in per_run]),
        ],
        ylim=None,
        value_labels=True,
        footnote=rec.get("identity", ""),
    )

    return Block(
        title="抽取侧对账",
        table=Table(
            "table_07_reconciliation",
            ["轮次", "原始输出", "计分", "丢弃", "恒等式成立"],
            rows,
        ),
        chart=chart,
        note=source_note,
    )


# ============================================================
# 主流程
# ============================================================

# 本脚本只认 eval_accuracy.py 的输出。缺了这些字段说明传错了文件，
# 与其画一堆空图，不如直接报错退出。
_REQUIRED_TOP_KEYS = (
    "runs",
    "stability",
    "summary",
    "error_taxonomy_across_runs",
    "documents",
)

# 全部区块。新增图表只需在这里登记一个 builder。
_BUILDERS = (
    build_main_metrics,
    build_relation_type_metrics,
    build_stability,
    build_error_taxonomy,
    build_document_metrics,
    build_drop_reasons,
    build_reconciliation,
)


def load_report(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"找不到评测报告：{path}")

    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"评测报告不是合法 JSON：{error}")

    if not isinstance(report, dict):
        raise SystemExit(f"评测报告顶层应为 JSON 对象，实际是 {type(report).__name__}")

    missing = [key for key in _REQUIRED_TOP_KEYS if key not in report]
    if missing:
        raise SystemExit(
            "评测报告缺少必需字段："
            + "、".join(missing)
            + "\n本脚本只读取 eval_accuracy.py 生成的报告，请确认 --report 指向的文件"
        )

    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="A10 知识抽取评测结果可视化生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--report", required=True, help="eval_accuracy.py 生成的评测 JSON")
    parser.add_argument("--output-dir", default="eval_data/visuals", help="图表输出目录")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    report_path = Path(args.report)
    output_dir = Path(args.output_dir)

    report = load_report(report_path)

    (output_dir / "figures").mkdir(parents=True, exist_ok=True)
    (output_dir / "tables").mkdir(parents=True, exist_ok=True)

    font = configure_font()

    print("=" * 70)
    print("A10 评测可视化生成")
    print("=" * 70)
    print(f"输入报告：{report_path}")
    print(f"输出目录：{output_dir}")
    print(f"运行轮数：{report.get('runs', '?')}")
    if font:
        print(f"中文字体：{font}")
    else:
        print(
            "中文字体：未找到可用中文字体，图中的中文将显示为方块。\n"
            "           请安装 Microsoft YaHei / SimHei / Noto Sans CJK SC 之一后重跑。"
        )
    print()

    produced: list[Path] = []

    for builder in _BUILDERS:
        block = builder(report)

        if block.table is None and block.chart is None:
            print(f"[跳过] {block.title}：{block.note}")
            print()
            continue

        files, summary = emit_block(block, output_dir)
        produced.extend(files)

        print(f"[生成] {block.title}")
        if summary.get("table"):
            print(f"       表：{summary['table']}.csv / .md（{summary.get('rows', 0)} 行）")
        if summary.get("figure"):
            print(f"       图：{summary['figure']}.png")
        if block.note:
            print(f"       注：{block.note}")
        print()

    print("-" * 70)
    print(f"共生成 {len(produced)} 个文件（图 {len(list((output_dir / 'figures').glob('*.png')))} 张）")
    print("-" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
