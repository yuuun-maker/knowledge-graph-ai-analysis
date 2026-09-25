"""
金标准校验脚本：检查人工标注的 gold JSON 是否符合规范（不参与评测，只做形式与证据校验）

用法（backend 目录下）：
    # ① 只做形式校验（跳过 evidence 逐字核对）
    python scripts/validate_gold.py eval_data/gold_第7章_树.json

    # ② 单文档：附带原文，做 evidence 逐字核对
    python scripts/validate_gold.py eval_data/gold_第7章_树.json eval_data/第7章_树.txt

    # ③ 多文档：按 text_file 字段（或 <text_id>.txt）在目录中查找原文
    python scripts/validate_gold.py eval_data/gold_all.json --text-dir eval_data/

校验项：
1. 顶层为 list-of-docs（兼容旧的单文档 dict 写法）
2. 每个文档：text_id/source 非空；text_id 全局唯一
3. 实体：name 非空且不重复；category ∈ {概念,定理,公式,方法}；description 非空
4. 关系：type ∈ {PRECEDES,CONTAINS,RELATED_TO,APPLIES_TO}；source/target 都在实体中；无自环；无重复三元组
5. evidence 逐字存在于原文中（防编造）；confidence ∈ [0,1]
6. core 字段（若存在）必须是 JSON 布尔值，不能是 "true"/1/"是" 这类写法
7. Core 非空：有关系的文档不能全部标 core=false
8. 提示 Core == Full 时双层口径未生效（警告，非错误）

关于"Core ⊆ Full"：
    本数据模型下 Core 定义为 core=true 的关系、Full 定义为全部关系，
    因此 Core ⊆ Full 是构造上恒真的，无法作为校验项。
    真正会出错、且会静默污染指标的是「Core 全空」——此时
    eval_accuracy.py 的 recall = 0/0 = 0.0 会被当成"召回率为零"报出去。
    故第 7 项校验的是这个，而不是恒真的子集关系。
"""
import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

VALID_CATEGORIES = ("概念", "定理", "公式", "方法")
VALID_TYPES = ("PRECEDES", "CONTAINS", "RELATED_TO", "APPLIES_TO")


def load_gold(path: Path) -> list[dict]:
    """读入 gold。兼容旧的单文档 dict 写法，统一返回 list-of-docs。"""
    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, dict):
        return [data]

    if not isinstance(data, list):
        raise ValueError("gold 顶层必须是 list（list-of-docs）或 dict（单个文档）")

    return data


def resolve_text(doc: dict, text_dir: Path | None) -> tuple[str | None, str]:
    """
    为单个文档找到原文。返回 (原文, 说明)。
    找不到时返回 (None, 原因)，由调用方降级为"跳过 evidence 校验"。
    """
    if text_dir is None:
        return None, "未提供原文，已跳过 evidence 逐字核对"

    candidates = []
    if doc.get("text_file"):
        candidates.append(text_dir / doc["text_file"])
    if doc.get("text_id"):
        candidates.append(text_dir / f"{doc['text_id']}.txt")

    for candidate in candidates:
        if candidate.is_file():
            text = candidate.read_text(encoding="utf-8").replace("\n", "")
            return text, f"evidence 逐字核对：{candidate.name}"

    return None, (
        f"在 {text_dir} 中找不到原文"
        f"（试过 {[c.name for c in candidates]}），已跳过 evidence 校验"
    )


def validate_document(
    doc: dict,
    text: str | None,
) -> tuple[list[str], list[str], dict]:
    """校验单个文档。返回 (errors, warnings, stats)。"""
    errors: list[str] = []
    warnings: list[str] = []
    prefix = doc.get("text_id") or "<无 text_id>"

    def err(msg: str) -> None:
        errors.append(f"[{prefix}] {msg}")

    def warn(msg: str) -> None:
        warnings.append(f"[{prefix}] {msg}")

    if not doc.get("text_id"):
        err("text_id 为空")
    if not doc.get("source"):
        err("source 为空")

    entities = doc.get("entities", [])
    relations = doc.get("relations", [])

    # ---- 实体 ----
    names = []
    for i, e in enumerate(entities):
        name = (e.get("name") or "").strip()
        if not name:
            err(f"实体[{i}] name 为空")
        names.append(name)
        cat = e.get("category")
        if cat not in VALID_CATEGORIES:
            err(f"实体「{name}」category 非法: {cat!r}")
        if not (e.get("description") or "").strip():
            err(f"实体「{name}」缺 description")

    dup_names = {n for n in names if names.count(n) > 1}
    if dup_names:
        err(f"实体重名: {dup_names}")
    name_set = set(names)

    # ---- 关系 ----
    seen: set[tuple[str, str, str]] = set()
    core_count = 0
    core_type_error = False

    for i, r in enumerate(relations):
        s = (r.get("source") or "").strip()
        t = (r.get("target") or "").strip()
        typ = (r.get("type") or "").strip().upper()

        if typ not in VALID_TYPES:
            err(f"关系[{i}] type 非法: {typ!r}")
            continue
        if s not in name_set or t not in name_set:
            err(f"关系[{i}] 端点不在实体中: {s} -[{typ}]-> {t}")
        if s == t:
            err(f"关系[{i}] 自环: {s}")

        key = (s, typ, t)
        if key in seen:
            err(f"关系[{i}] 重复三元组: {s} -[{typ}]-> {t}")
        seen.add(key)

        ev = (r.get("evidence") or "").strip()
        if not ev:
            err(f"关系[{i}] {s} -[{typ}]-> {t} 缺 evidence")
        elif text is not None and ev not in text:
            err(
                f"关系[{i}] evidence 不在原文中（逐字核对失败）: {ev[:40]}…"
            )

        conf = r.get("confidence")
        if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not (0 <= conf <= 1):
            err(f"关系[{i}] confidence 非法: {conf!r}")

        # ---- core ----
        if "core" in r:
            core = r["core"]
            # bool 必须在 int 之前判：JSON 里的 true 反序列化后是 bool，
            # 而 bool 是 int 的子类，只判 int 会把 1/0 也放过
            if not isinstance(core, bool):
                err(
                    f"关系[{i}] core 必须是 JSON 布尔（true/false），"
                    f"实际是 {type(core).__name__}: {core!r}"
                )
                core_type_error = True
            elif core:
                core_count += 1
        else:
            # 缺省视为 true，与 eval_accuracy.gold_core_relations 的
            # relation.get("core", True) 保持一致
            core_count += 1

    stats = {
        "text_id": prefix,
        "entities": len(entities),
        "relations": len(relations),
        "core": core_count,
        "full": len(relations),
    }

    # core 类型写错时不再叠加"Core 为空"——根因只有一个（字段写错），
    # 报两条会让标注员以为有两个问题
    if relations and core_count == 0 and not core_type_error:
        err(
            "Core 为空：全部关系都标了 core=false。"
            "此时 eval_accuracy.py 的 recall = 0/0 = 0.0，"
            "会被当成「召回率为零」报出去。至少要有一条 core=true。"
        )

    if relations and core_count == len(relations):
        warn(
            f"Core == Full（{core_count}/{len(relations)}）："
            "双层口径未生效，relation_primary 与 relation_full 将完全相同。"
            "若确实没有边界模糊的关系，可忽略本提示。"
        )

    if not relations:
        warn("该文档没有任何关系")

    return errors, warnings, stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gold 金标准校验（形式 + 证据逐字核对 + core 字段）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("gold", help="Gold JSON 文件")
    parser.add_argument(
        "text", nargs="?", default=None,
        help="原文文件（单文档时使用；多文档请改用 --text-dir）",
    )
    parser.add_argument(
        "--text-dir", default=None,
        help="原文目录，按 text_file 字段或 <text_id>.txt 匹配",
    )
    args = parser.parse_args()

    gold_path = Path(args.gold)
    if not gold_path.is_file():
        print(f"找不到 gold 文件：{gold_path}")
        return 2

    if args.text and args.text_dir:
        print("--text 与 --text-dir 不能同时使用")
        return 2

    try:
        docs = load_gold(gold_path)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"gold 解析失败：{e}")
        return 2

    text_dir = Path(args.text_dir) if args.text_dir else None
    single_text = None

    if args.text:
        single_text_path = Path(args.text)
        if not single_text_path.is_file():
            print(f"找不到原文文件：{single_text_path}")
            return 2
        single_text = single_text_path.read_text(encoding="utf-8").replace("\n", "")
        if len(docs) != 1:
            print(
                f"gold 含 {len(docs)} 个文档，但只给了一个原文文件。"
                "请改用 --text-dir。"
            )
            return 2

    errors: list[str] = []
    warnings: list[str] = []
    all_stats: list[dict] = []

    # 跨文档：text_id 唯一
    ids = [d.get("text_id") for d in docs]
    dup_ids = {i for i in ids if ids.count(i) > 1}
    if dup_ids:
        errors.append(f"text_id 重复: {dup_ids}")

    for doc in docs:
        if single_text is not None:
            text, note = single_text, "evidence 逐字核对：已提供原文"
        else:
            text, note = resolve_text(doc, text_dir)

        doc_errors, doc_warnings, stats = validate_document(doc, text)
        errors.extend(doc_errors)
        warnings.extend(doc_warnings)
        all_stats.append(stats)
        stats["note"] = note

    # ---- 报告 ----
    print(f"文档 {len(docs)} 个 / gold：{gold_path}")
    print()
    print(
        f"{'text_id':<28}{'实体':>6}{'关系':>6}{'Core':>6}{'Full':>6}{'Core占比':>10}"
    )
    for s in all_stats:
        ratio = f"{s['core'] / s['full']:.0%}" if s["full"] else "—"
        print(
            f"{s['text_id']:<28}{s['entities']:>6}{s['relations']:>6}"
            f"{s['core']:>6}{s['full']:>6}{ratio:>10}"
        )

    total_e = sum(s["entities"] for s in all_stats)
    total_r = sum(s["relations"] for s in all_stats)
    total_c = sum(s["core"] for s in all_stats)
    print(
        f"{'合计':<28}{total_e:>6}{total_r:>6}{total_c:>6}{total_r:>6}"
        f"{(f'{total_c / total_r:.0%}' if total_r else '—'):>10}"
    )

    notes = [s["note"] for s in all_stats if s.get("note")]
    if notes:
        print()
        for note in dict.fromkeys(notes):
            print(f"  · {note}")

    if warnings:
        print(f"\n警告 {len(warnings)} 条（不阻断）：")
        for w in warnings:
            print(f"  ! {w}")

    if errors:
        print(f"\n发现 {len(errors)} 个问题：")
        for e in errors:
            print(f"  ✗ {e}")
        return 1

    print("\n全部校验通过 ✓（形式、端点、去重、core 字段、evidence 逐字均合法）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
