"""
人工抽样验证 —— 抽样器

赛题要求「知识抽取的准确率（人工抽样验证）不低于 70%」。本脚本把系统抽取出的
知识点与关系**分层随机抽样**成一份判定表，交给人工逐条判对错；判定结果由
`calc_manual_accuracy.py` 汇总成准确率。

与「对冻结金标准自动评测」（eval_accuracy.py）的区别，以及为什么要两个都做：

    自动评测   Pred  vs 人工 Gold        —— 覆盖率全、可复现，但依赖一份完整金标准，
                                           且评判标准是「与标注者是否一致」
    人工抽样   人工直接看原文判 Pred 对错  —— 赛题明确要求的口径，评判标准是
                                           「这条知识本身对不对」，不经过金标准这一层

设计要点：

1. **分层抽样而非简单随机**。四类关系的产出量极不均衡（开发集 CONTAINS 25 条、
   PRECEDES 0 条），简单随机抽出来的样本会被高频类型淹没，稀有类型的准确率无从估计。
   每类先保底 `--min-per-type` 条，剩余名额按各类型池子大小比例分配。
2. **抽样母本用封存集**（物理·第2章 / 数据结构·第2章 / 化学·第2章）——这三章的文本
   从未参与过提示词迭代，用它做样本比用开发集更能代表真实泛化表现。
3. **固定随机种子**：同一批 pred + 同一个 seed 必然抽出同一批样本，可复现、可复核。
4. **自动附上原文上下文**：按模型给出的 evidence 在原文中定位并截取前后文，
   标注者不必自己去全文里找证据（找不到时标 ⚠，这本身也是「证据不实」的信号）。

用法（backend 目录下）：

    python scripts/sample_for_manual_check.py                # 用内置三章封存集，抽 100 关系 + 50 实体
    python scripts/sample_for_manual_check.py --n-relations 120 --n-entities 60 --seed 20261008

产出（默认落在 eval_data/manual_check/）：

    抽样判定表_关系.csv     —— 交给标注者填「判定」列
    抽样判定表_实体.csv     —— 同上
    抽样对照.md             —— 人读版：每条样本 + 模型证据 + 原文上下文
    抽样元信息.json         —— 抽样参数、池子大小、各类型配额（评审复核用）
"""
import argparse
import csv
import io
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

RELATION_TYPES = ["CONTAINS", "RELATED_TO", "APPLIES_TO", "PRECEDES"]

# 内置母本：三章封存集（pred, 文本）。这三章的文本未参与提示词迭代，泛化性最好。
DEFAULT_PAIRS = [
    ("eval_data/pred_物理_第2章_运动学_v15.json",
     "eval_data/第2章_运动学_Kinematics_中文版.txt"),
    ("eval_data/pred_数据结构_第2章_复杂度分析_v15.json",
     "eval_data/第2章_复杂度分析.txt"),
    ("eval_data/pred_化学_第2章_原子分子与离子_v15.json",
     "eval_data/第2章_原子分子与离子_中文版.txt"),
]

CONTEXT_RADIUS = 160


def load_pred(path):
    """pred 文件形状：[{"text_id": ..., "runs": [{entities, relations, ...}, ...]}]"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = [data]
    if not data or not isinstance(data[0], dict):
        raise ValueError(f"pred 结构无法识别：{path}")
    return data[0]


def norm(s):
    return re.sub(r"\s+", "", str(s or ""))


def _flatten_with_map(text):
    """去掉全部空白，同时记录每个折叠后字符对应的原文下标，用于回定位。"""
    chars, idxmap = [], []
    for i, ch in enumerate(text):
        if not ch.isspace():
            chars.append(ch)
            idxmap.append(i)
    return "".join(chars), idxmap


def locate_context(text, evidence, radius=CONTEXT_RADIUS):
    """
    在原文中定位 evidence，返回 (上下文片段, 是否逐字命中)。

    先折叠空白再查找（模型可能把跨行句子拼成一行），找到后用折叠时的下标映射
    还原回原文位置——不能拿 evidence 的前缀去原文里二次查找，那样只要前缀里
    含换行就会误判为「定位不到」。
    """
    if not evidence:
        return None, False
    flat_text, idxmap = _flatten_with_map(text)
    flat_ev = norm(evidence)
    if not flat_ev:
        return None, False
    idx = flat_text.find(flat_ev)
    if idx < 0:
        return None, False
    pos = idxmap[idx]
    end_pos = idxmap[min(idx + len(flat_ev) - 1, len(idxmap) - 1)] + 1
    start = max(0, pos - radius)
    end = min(len(text), end_pos + radius)
    return text[start:end].replace("\n", " "), True


def stratified_sample(items, key_fn, total, min_per_type, rng):
    """
    分层抽样：每层先保底 min_per_type 条，剩余名额按各层剩余池大小比例分配。

    items 需先去重。返回 (抽中的下标列表, 各层配额明细)。
    """
    buckets = {}
    for i, it in enumerate(items):
        buckets.setdefault(key_fn(it), []).append(i)

    picked, quota = [], {}
    remaining = total

    # 第一轮：保底
    for k in sorted(buckets):
        take = min(min_per_type, len(buckets[k]))
        quota[k] = take
        remaining -= take

    # 第二轮：按剩余池子大小比例补足
    if remaining > 0:
        pools = {k: len(buckets[k]) - quota[k] for k in buckets if len(buckets[k]) > quota[k]}
        total_pool = sum(pools.values())
        if total_pool > 0:
            # 逐层向下取整分配，余数给池子最大的层，保证总数精确且可复现
            frac = {}
            for k, n in pools.items():
                exact = remaining * n / total_pool
                add = min(int(exact), n)
                quota[k] += add
                frac[k] = (exact - add, k)
            left = total - sum(quota.values())
            for _, k in sorted(((v, k) for k, (v, _) in frac.items()), reverse=True):
                if left <= 0:
                    break
                if quota[k] < len(buckets[k]):
                    quota[k] += 1
                    left -= 1

    # 抽样
    for k in sorted(buckets):
        take = min(quota[k], len(buckets[k]))
        picked.extend(rng.sample(sorted(buckets[k]), take))
    return sorted(picked), {k: min(v, len(buckets[k])) for k, v in quota.items()}


def main():
    ap = argparse.ArgumentParser(description="人工抽样验证 —— 抽样器")
    ap.add_argument("--pair", action="append", default=None,
                    help="pred=text 配对，可重复；默认用内置三章封存集")
    ap.add_argument("--seed", type=int, default=20261008, help="随机种子（固定以保证可复现）")
    ap.add_argument("--n-relations", type=int, default=100)
    ap.add_argument("--n-entities", type=int, default=50)
    ap.add_argument("--min-per-type", type=int, default=10, help="每种关系类型的保底抽样条数")
    ap.add_argument("--run", type=int, default=0, help="取第几轮的预测（0 起），默认第 1 轮")
    ap.add_argument("--out-dir", default="eval_data/manual_check")
    args = ap.parse_args()

    pairs = args.pair or [f"{p}={t}" for p, t in DEFAULT_PAIRS]
    parsed = []
    for item in pairs:
        if "=" not in item:
            print(f"✗ --pair 需写成 pred=text：{item}")
            return 1
        pred, text = item.split("=", 1)
        parsed.append((pred, text))

    # ---- 汇总池子 ----
    rel_pool, ent_pool, meta_runs = [], [], []
    for pred_path, text_path in parsed:
        if not (os.path.isfile(pred_path) and os.path.isfile(text_path)):
            print(f"✗ 文件缺失：{pred_path} 或 {text_path}")
            return 1
        doc = load_pred(pred_path)
        text_id = doc.get("text_id") or os.path.basename(text_path)
        with open(text_path, encoding="utf-8") as f:
            text = f.read()
        runs = doc.get("runs") or []
        if not runs:
            print(f"✗ {pred_path} 里没有 runs")
            return 1
        run = runs[min(args.run, len(runs) - 1)]
        meta_runs.append({"pred": pred_path, "text_id": text_id,
                          "run_index": min(args.run, len(runs) - 1),
                          "relations": len(run.get("relations") or []),
                          "entities": len(run.get("entities") or [])})
        for r in run.get("relations") or []:
            rel_pool.append({
                "text_id": text_id, "text_path": text_path, "text": text,
                "type": r.get("type", ""), "source": r.get("source", ""),
                "target": r.get("target", ""), "evidence": r.get("evidence", ""),
                "confidence": r.get("confidence", ""),
            })
        for e in run.get("entities") or []:
            ent_pool.append({
                "text_id": text_id, "text_path": text_path, "text": text,
                "name": e.get("name", ""), "category": e.get("category", ""),
                "description": e.get("description", ""),
            })

    # ---- 去重（同一关系可能同时出现在多章的池子里）----
    def dedup(items, key_fn):
        seen, out = set(), []
        for it in items:
            k = key_fn(it)
            if k in seen:
                continue
            seen.add(k)
            out.append(it)
        return out

    rel_pool = dedup(rel_pool, lambda x: (x["text_id"], x["source"], x["type"], x["target"]))
    ent_pool = dedup(ent_pool, lambda x: (x["text_id"], x["name"]))

    rng = random.Random(args.seed)

    rel_idx, rel_quota = stratified_sample(
        rel_pool, lambda x: x["type"], args.n_relations, args.min_per_type, rng)
    rel_sample = [rel_pool[i] for i in rel_idx]

    # 实体按 category 分层，同样的保底逻辑
    ent_idx, ent_quota = stratified_sample(
        ent_pool, lambda x: x["category"] or "未分类", args.n_entities,
        max(5, args.min_per_type // 2), rng)
    ent_sample = [ent_pool[i] for i in ent_idx]

    # 按章节归组输出，便于标注者成批核对
    rel_sample.sort(key=lambda x: (x["text_id"], x["type"], x["source"]))
    ent_sample.sort(key=lambda x: (x["text_id"], x["category"], x["name"]))

    os.makedirs(args.out_dir, exist_ok=True)

    # ---- 关系判定表 ----
    rel_csv = os.path.join(args.out_dir, "抽样判定表_关系.csv")
    with open(rel_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["序号", "章节", "关系类型", "源实体", "目标实体",
                    "模型给出的证据(原文短句)", "证据能否在原文逐字定位",
                    "模型自评confidence", "原文上下文",
                    "判定(正确/错误-臆造/错误-方向反/错误-类型错/错误-端点不成立)",
                    "备注"])
        for i, r in enumerate(rel_sample, 1):
            ctx, found = locate_context(r["text"], r["evidence"])
            w.writerow([i, r["text_id"], r["type"], r["source"], r["target"],
                        r["evidence"], "是" if found else "⚠ 否",
                        r["confidence"], ctx or "",
                        "", ""])

    # ---- 实体判定表 ----
    ent_csv = os.path.join(args.out_dir, "抽样判定表_实体.csv")
    with open(ent_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["序号", "章节", "实体名", "类别", "模型给出的描述",
                    "判定(正确/错误-臆造/错误-粒度不当/错误-类别错)", "备注"])
        for i, e in enumerate(ent_sample, 1):
            w.writerow([i, e["text_id"], e["name"], e["category"],
                        e["description"], "", ""])

    # ---- 人读版对照 ----
    md = os.path.join(args.out_dir, "抽样对照.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# 人工抽样验证 —— 抽样对照表\n\n")
        f.write(f"> 随机种子 `{args.seed}`｜关系样本 {len(rel_sample)} 条"
                f"（池 {len(rel_pool)}）｜实体样本 {len(ent_sample)} 个（池 {len(ent_pool)}）\n>\n")
        f.write("> 判定标准见 `docs/人工抽样验证方案.md`。判定结果请填回 "
                "`抽样判定表_关系.csv` / `抽样判定表_实体.csv`，\n"
                "> 再跑 `python scripts/calc_manual_accuracy.py` 汇总。\n\n")
        f.write(f"## 一、关系样本（{len(rel_sample)} 条）\n\n")
        for i, r in enumerate(rel_sample, 1):
            ctx, found = locate_context(r["text"], r["evidence"])
            f.write(f"### R{i:03d}　{r['text_id']}\n\n")
            f.write(f"- **三元组**：`{r['source']}` —**{r['type']}**→ `{r['target']}`"
                    f"（模型自评 confidence={r['confidence']}）\n")
            f.write(f"- **模型证据**：{r['evidence'] or '（空）'}\n")
            if found:
                f.write(f"- **原文上下文**：…{ctx}…\n")
            else:
                f.write("- **原文上下文**：⚠ 证据未能在原文中逐字定位"
                        "（可能是模型改写、跨段拼接或臆造）\n")
            f.write(f"- **判定**：☐ 正确　☐ 错误-臆造　☐ 错误-方向反　☐ 错误-类型错"
                    f"　☐ 错误-端点不成立　　备注：\n\n")
        f.write(f"## 二、实体样本（{len(ent_sample)} 个）\n\n")
        for i, e in enumerate(ent_sample, 1):
            f.write(f"### E{i:03d}　{e['text_id']}\n\n")
            f.write(f"- **实体**：`{e['name']}`（类别：{e['category']}）\n")
            f.write(f"- **模型描述**：{e['description'] or '（空）'}\n")
            f.write(f"- **判定**：☐ 正确　☐ 错误-臆造　☐ 错误-粒度不当"
                    f"　☐ 错误-类别错　　备注：\n\n")

    # ---- 元信息（评审复核用）----
    meta = {
        "seed": args.seed,
        "run_index": args.run,
        "n_relations_requested": args.n_relations,
        "n_entities_requested": args.n_entities,
        "min_per_type": args.min_per_type,
        "relation_pool_size": len(rel_pool),
        "entity_pool_size": len(ent_pool),
        "relation_sampled": len(rel_sample),
        "entity_sampled": len(ent_sample),
        "relation_quota_by_type": {k: rel_quota[k] for k in sorted(rel_quota)},
        "relation_pool_by_type": {
            t: sum(1 for x in rel_pool if x["type"] == t) for t in RELATION_TYPES},
        "entity_pool_by_category": {},
        "sources": meta_runs,
    }
    for e in ent_pool:
        k = e["category"] or "未分类"
        meta["entity_pool_by_category"][k] = meta["entity_pool_by_category"].get(k, 0) + 1
    with open(os.path.join(args.out_dir, "抽样元信息.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"池子：关系 {len(rel_pool)} 条 / 实体 {len(ent_pool)} 个（去重后，取第 {args.run + 1} 轮预测）")
    print("关系池按类型：" + "，".join(
        f"{t} {meta['relation_pool_by_type'][t]}" for t in RELATION_TYPES))
    print(f"抽中：关系 {len(rel_sample)} 条 / 实体 {len(ent_sample)} 个")
    print(f"  关系各类型配额：" + "，".join(
        f"{k} {v}" for k, v in sorted(rel_quota.items())))
    print(f"\n产出目录：{args.out_dir}/")
    print("  抽样判定表_关系.csv  /  抽样判定表_实体.csv  （填「判定」列）")
    print("  抽样对照.md          （人读版，含原文上下文）")
    print("  抽样元信息.json      （抽样参数与各类型配额，供评审复核）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
