"""
试题文档导入对照评估（P2.3）

对样本试题文档跑三种策略并对比：
  RULE          —— 确定性规则解析（零成本）
  RULE+LLM      —— 规则为主，LLM 兜底补规则漏掉的题（合并时规则优先）
  LLM-ONLY      —— 纯 LLM（用于看清"规则到底贡献了多少"）

指标：解析题数 / 答案覆盖率 / 相对答案区真值的缺失数 / LLM 调用次数 / 耗时 / token 粗估与成本粗估。
真值基线：答案区声明的题号集合（见 question_importer.audit）。

用法（backend 目录下）：
    python eval_question_import.py --docs 2 --max-llm-calls 4     # 小预算试跑
    python eval_question_import.py --docs 16 --max-llm-calls 40   # 全量（注意成本）
"""
import argparse
import glob
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services import question_importer as qi
from app.services.question_extractor import QuestionExtractor, merge_items

# DeepSeek 输入侧价格粗估（元/百万 token）；仅用于量级参考，正式报告需按当期价目核对
PRICE_PER_M_INPUT = 1.0


def _count_with_answer(items: list) -> int:
    return sum(1 for i in items if "answer_missing" not in (i.get("warnings") or []))


def _sample_paths(limit: int) -> list:
    marker = chr(0x6D4B) + chr(0x8BD5) + chr(0x9898)      # 测试题
    paths = sorted(p for p in glob.glob("data/sample_docs/**/*.txt", recursive=True)
                   if marker in os.path.basename(p))
    return paths[:limit]


def evaluate(path: str, extractor: QuestionExtractor, budget: int) -> dict:
    text = open(path, encoding="utf-8").read()
    truth = qi.audit(text)                                 # 真值基线（答案区声明）
    t0 = time.perf_counter()

    rule = qi.parse_text(text)
    rule_items = rule["items"]
    rule_missing = sorted(set(truth["missing_numbers"])) if truth["answer_entries"] else []

    calls_before = extractor.calls
    llm = extractor.extract(text, max_calls=max(0, budget))
    llm_calls = extractor.calls - calls_before

    merged, minfo = merge_items(rule_items, llm["questions"])
    merged_numbers = {i.get("number") for i in merged if i.get("number")}
    truth_numbers = set(truth["missing_numbers"]) | {i.get("number") for i in rule_items}
    merged_missing = sorted(truth_numbers - merged_numbers) if truth["answer_entries"] else []

    return {
        "file": os.path.basename(path),
        "chars": len(text),
        "answer_entries": truth["answer_entries"],
        "rule_items": len(rule_items),
        "rule_with_answer": _count_with_answer(rule_items),
        "rule_missing_vs_truth": rule_missing,
        "llm_calls": llm_calls,
        "llm_items": len(llm["questions"]),
        "llm_added": minfo["llm_added"],
        "merged_items": len(merged),
        "merged_with_answer": _count_with_answer(merged),
        "merged_missing_vs_truth": merged_missing,
        "elapsed_sec": round(time.perf_counter() - t0, 2),
    }


def main():
    ap = argparse.ArgumentParser(description="E4：试题文档导入对照评估（RULE vs RULE+LLM）")
    ap.add_argument("--docs", type=int, default=2, help="评估前 N 份文档（默认 2，控制成本）")
    ap.add_argument("--max-llm-calls", type=int, default=6, help="本次评估的 LLM 调用总上限")
    ap.add_argument("--out", default=os.path.join("eval_data", "eval_report_question_import.json"))
    args = ap.parse_args()

    paths = _sample_paths(args.docs)
    if not paths:
        print("✗ 未找到样本试题文档")
        return False
    _BUDGET_BASE = args.max_llm_calls
    extractor = QuestionExtractor(temperature=0.0)
    print(f"样本 {len(paths)} 份 | LLM 调用上限 {args.max_llm_calls}")

    rows = []
    budget_left = args.max_llm_calls
    for path in paths:
        row = evaluate(path, extractor, budget_left)
        budget_left -= row["llm_calls"]
        rows.append(row)
        print("%-38s 真值 %-4d 规则 %-4d(含答案 %-4d) LLM补 %-3d → 合并 %-4d(含答案 %-4d) 缺 %s" % (
            row["file"][:36], row["answer_entries"], row["rule_items"], row["rule_with_answer"],
            row["llm_added"], row["merged_items"], row["merged_with_answer"],
            row["merged_missing_vs_truth"] or "无"))

    agg = {
        "docs": len(rows),
        "truth_total": sum(r["answer_entries"] for r in rows),
        "rule_total": sum(r["rule_items"] for r in rows),
        "rule_with_answer": sum(r["rule_with_answer"] for r in rows),
        "llm_added": sum(r["llm_added"] for r in rows),
        "merged_total": sum(r["merged_items"] for r in rows),
        "merged_with_answer": sum(r["merged_with_answer"] for r in rows),
        "llm_calls": extractor.calls,
        "prompt_tokens_est": extractor.prompt_tokens,
        "cost_est_yuan": round(extractor.prompt_tokens / 1_000_000 * PRICE_PER_M_INPUT, 4),
    }
    print("\n汇总：", json.dumps(agg, ensure_ascii=False))

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"params": {"temperature": 0.0, "max_llm_calls": args.max_llm_calls,
                              "docs": args.docs, "price_per_m_input": PRICE_PER_M_INPUT},
                   "aggregate": agg, "per_doc": rows, "command": " ".join(sys.argv)},
                  f, ensure_ascii=False, indent=2)
    print(f"报告已写入：{args.out}")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
