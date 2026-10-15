"""
人工抽样验证 —— 准确率汇总

读取 `sample_for_manual_check.py` 产出的判定表（人工填好「判定」列后），
计算赛题口径的**人工抽样准确率**：

    准确率 = 判定为「正确」的条数 / 已完成判定的条数

注意这是 **Precision（查准率）**，不是 F1：抽样只抽「系统输出了什么」，
抽不到「系统漏了什么」，所以抽样口径天然测不出召回。漏抽只能靠
`eval_accuracy.py` 对完整金标准的自动评测来反映。两份结果必须一起报。

同时输出 Wilson 95% 置信区间——样本量 100 时半宽约 ±9%，
报告里必须带上区间，否则「0.78」这种点估计会被误读成精确值。

用法（backend 目录下）：

    python scripts/calc_manual_accuracy.py                      # 默认读 eval_data/manual_check/
    python scripts/calc_manual_accuracy.py --out-dir eval_data/manual_check --json-out eval_data/manual_accuracy.json
"""
import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

RELATION_TYPES = ["CONTAINS", "RELATED_TO", "APPLIES_TO", "PRECEDES"]
Z = 1.96


def wilson(k, n):
    """Wilson 95% 置信区间，比正态近似在 p 接近 0/1 或 n 小时更稳。"""
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + Z * Z / n
    center = (p + Z * Z / (2 * n)) / d
    half = Z / d * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))


def is_correct(verdict):
    return str(verdict or "").strip().startswith("正确")


def is_judged(verdict):
    v = str(verdict or "").strip()
    return bool(v) and not v.startswith("☐")


def verdict_key(rows):
    """
    定位「判定」列。

    抽样器写出的表头是 `判定(正确/错误-臆造/…)`——把可选值写进表头是为了让标注者
    一眼看到能填什么。因此**不能按 `row["判定"]` 精确取值**，否则所有行都会被当成
    「未判定」，汇总结果恒为空（这个坑已经踩过一次）。
    """
    if not rows:
        return None
    for k in rows[0].keys():
        if k and k.strip().startswith("判定"):
            return k
    return None


def load_rows(path):
    """
    读取判定表。编码做三级兜底：utf-8-sig（本脚本产出）→ gbk（Excel 在中文 Windows
    下「另存为 CSV」的默认编码）→ utf-8。

    没有这层兜底的话，标注者用 Excel 填完另存一份，这里会直接抛 UnicodeDecodeError，
    而报错信息看起来像「文件损坏」，很容易被误判成数据丢失。
    """
    if not os.path.isfile(path):
        return None
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            with open(path, encoding=enc, newline="") as f:
                rows = list(csv.DictReader(f))
            if enc != "utf-8-sig":
                print(f"提示：{os.path.basename(path)} 以 {enc} 解码成功（Excel 另存可能导致编码变化）。")
            return rows
        except UnicodeDecodeError:
            continue
    print(f"✗ 无法解码 {path}，请另存为「CSV UTF-8(逗号分隔)」后重试。")
    return None


def summarize(rows, label, group_key, vkey):
    """按 group_key 分层统计；同时给出未判定条数（不得静默丢弃）。"""
    if vkey is None:
        return {"label": label, "total_rows": len(rows), "judged": 0,
                "unjudged": len(rows), "accuracy": None,
                "error": "找不到「判定」列，请检查表头"}
    judged = [r for r in rows if is_judged(r.get(vkey))]
    unjudged = len(rows) - len(judged)
    if not judged:
        return {"label": label, "total_rows": len(rows), "judged": 0,
                "unjudged": unjudged, "accuracy": None}

    k = sum(1 for r in judged if is_correct(r.get(vkey)))
    lo, hi = wilson(k, len(judged))
    out = {
        "label": label,
        "total_rows": len(rows),
        "judged": len(judged),
        "unjudged": unjudged,
        "correct": k,
        "accuracy": round(k / len(judged), 4),
        "ci95": [round(lo, 4), round(hi, 4)],
        "pass_70": (lo >= 0.70),      # 以置信区间下界是否 ≥0.70 判定，比点估计严格
        "by_group": {},
    }
    groups = {}
    for r in judged:
        groups.setdefault(r.get(group_key, "") or "未分组", []).append(r)
    for g, items in sorted(groups.items()):
        gk = sum(1 for r in items if is_correct(r.get(vkey)))
        glo, ghi = wilson(gk, len(items))
        out["by_group"][g] = {
            "judged": len(items), "correct": gk,
            "accuracy": round(gk / len(items), 4),
            "ci95": [round(glo, 4), round(ghi, 4)],
        }
    # 错误构成（诊断用）
    errs = {}
    for r in judged:
        v = str(r.get(vkey, "")).strip()
        if not is_correct(v):
            errs[v] = errs.get(v, 0) + 1
    out["error_breakdown"] = errs
    return out


def md_section(res, group_title):
    if not res or res.get("judged") == 0:
        return f"### {group_title}\n\n_尚无已判定的样本。_\n\n"
    s = f"### {group_title}\n\n"
    s += f"- 抽样 {res['total_rows']} 条，已判定 {res['judged']} 条"
    if res["unjudged"]:
        s += f"，**未判定 {res['unjudged']} 条**（未判定项不计入准确率）"
    s += "\n"
    s += (f"- **人工抽样准确率 = {res['correct']}/{res['judged']} = "
          f"{res['accuracy']:.4f}**，95% CI [{res['ci95'][0]:.4f}, {res['ci95'][1]:.4f}]\n")
    s += (f"- 判定：{'✓ 置信区间下界 ≥ 0.70，满足赛题要求' if res['pass_70'] else '✗ 置信区间下界 < 0.70，不能声称满足赛题 70% 要求'}\n\n")
    if res.get("by_group"):
        s += f"| 分组 | 已判定 | 正确 | 准确率 | 95% CI |\n|---|---:|---:|---:|---|\n"
        for g, v in res["by_group"].items():
            s += (f"| {g} | {v['judged']} | {v['correct']} | {v['accuracy']:.4f} | "
                  f"[{v['ci95'][0]:.4f}, {v['ci95'][1]:.4f}] |\n")
        s += "\n"
    if res.get("error_breakdown"):
        s += "错误构成：" + "，".join(f"{k} {v} 条" for k, v in res["error_breakdown"].items()) + "\n\n"
    return s


def main():
    ap = argparse.ArgumentParser(description="人工抽样验证 —— 准确率汇总")
    ap.add_argument("--out-dir", default="eval_data/manual_check")
    ap.add_argument("--json-out", default="eval_data/manual_accuracy.json")
    ap.add_argument("--md-out", default="eval_data/manual_accuracy.md")
    args = ap.parse_args()

    rel = load_rows(os.path.join(args.out_dir, "抽样判定表_关系.csv"))
    ent = load_rows(os.path.join(args.out_dir, "抽样判定表_实体.csv"))
    if rel is None and ent is None:
        print(f"✗ 在 {args.out_dir}/ 下找不到判定表。请先运行 scripts/sample_for_manual_check.py")
        return 1

    rel_res = (summarize(rel, "关系", "关系类型", verdict_key(rel))
               if rel is not None else None)
    ent_res = (summarize(ent, "实体", "类别", verdict_key(ent))
               if ent is not None else None)

    result = {
        "kind": "manual_sampling_accuracy",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "definition": "准确率 = 判定为正确的条数 / 已完成判定的条数（Precision 口径，测不出漏抽）",
        "threshold": 0.70,
        "relation": rel_res,
        "entity": ent_res,
    }

    with open(args.json_out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    md = "# 人工抽样验证 —— 准确率汇总\n\n"
    md += ("> 本文件由 `backend/scripts/calc_manual_accuracy.py` 从判定表自动生成，"
           "请勿手工修改数字。\n>\n")
    md += ("> 口径：准确率 = 判定为「正确」的条数 ÷ 已完成判定的条数。"
           "这是 **Precision（查准率）**，\n> 抽样抽不到「系统漏了什么」，"
           "因此**召回必须另由 eval_accuracy.py 对完整金标准的评测给出**。\n\n")
    md += md_section(rel_res, "一、关系抽取准确率（赛题主指标）")
    md += md_section(ent_res, "二、实体抽取准确率")
    md += ("\n---\n\n## 三、结论表述纪律\n\n"
           "只有当**置信区间下界** ≥ 0.70 时，才可以写「满足赛题准确率要求 ≥70%」。\n"
           "若点估计 ≥0.70 而区间下界 <0.70，正确写法是「点估计 X，95% CI [a,b]，"
           "样本量不足以断言达标，需扩大样本」。\n")
    with open(args.md_out, "w", encoding="utf-8") as f:
        f.write(md)

    for res, title in ((rel_res, "关系"), (ent_res, "实体")):
        if not res:
            continue
        if res["judged"] == 0:
            print(f"{title}：抽样 {res['total_rows']} 条，尚无已判定样本")
        else:
            print(f"{title}：{res['correct']}/{res['judged']} = {res['accuracy']:.4f}"
                  f"  95% CI [{res['ci95'][0]:.4f}, {res['ci95'][1]:.4f}]"
                  f"  {'✓ 达标' if res['pass_70'] else '✗ 不能断言达标'}"
                  + (f"  （未判定 {res['unjudged']} 条）" if res["unjudged"] else ""))
    print(f"\n结果已写入 {args.json_out} 与 {args.md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
