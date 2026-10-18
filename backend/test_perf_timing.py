"""
性能测试：文档解析 → 分块 → 并发抽取 的端到端耗时（赛题指标：≤60 秒）

用法（backend 目录下）：

    python test_perf_timing.py --parse-only          # 只测解析，不调 LLM（零成本，用于挑选测试文档）
    python test_perf_timing.py --runs 3              # 用默认文件集，每个文件跑 3 轮并落盘
    python test_perf_timing.py --files a.txt b.pdf --runs 3 --output eval_data/perf_timing.json

与旧版的区别：结果落盘为 JSON（旧版只 print，导致交付材料里的性能数字无原始数据可溯源）。
落盘内容含每个文件的每一轮明细、均值与达标判定，以及模型/提示词版本/分块参数快照。

安全边界：本脚本只读文件、只调 LLM 抽取接口。不写 SQLite、不写 Neo4j——`KnowledgeExtractor.extract()`
是纯「文本进、JSON 出」，不落库。
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.core.config import settings
from app.services.document_parser import DocumentParser
from app.services.knowledge_extractor import (
    KnowledgeExtractor, _CHUNK_MAX_TOKENS, _OVERLAP_TOKENS, _MAX_CONCURRENCY,
)
from app.utils.text_processor import chunk_text_for_llm

# 演示视频与交付报告用的默认测试集：覆盖「小 / 中 / 大」三档纯文本，
# 另加一份 PDF 用于记录解析开销（PDF 解析明显贵于 TXT）。
DEFAULT_FILES = [
    "eval_data/第7章_树.txt",
    "eval_data/第2章_复杂度分析.txt",
    "eval_data/第2章_运动学_Kinematics_中文版.txt",
]

THRESHOLD_SECONDS = 60.0


def _sha256_head(path: str) -> str:
    """记录文件指纹，保证「这个耗时是为哪份文本测的」可追溯。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


async def measure_one(path: str, runs: int) -> dict:
    """对单个文件跑 runs 轮，返回明细与统计。"""
    fmt = os.path.splitext(path)[1].lower().lstrip(".") or "unknown"
    record = {
        "file": path.replace("\\", "/"),
        "format": fmt,
        "size_bytes": os.path.getsize(path),
        "sha256": _sha256_head(path),
        "parsed_chars": 0,
        "chunks": 0,
        "runs": [],
        "errors": [],
    }

    # 第 1 轮既有解析也有抽取；后续轮次沿用同一份文本，
    # 但**解析仍重新计时**，因为赛题口径是「解析 + 抽取」的总耗时。
    text = None
    for i in range(runs):
        t0 = time.perf_counter()
        text = await DocumentParser.parse(path)
        parse_s = time.perf_counter() - t0

        if i == 0:
            record["parsed_chars"] = len(text)
            record["chunks"] = len(chunk_text_for_llm(
                text, max_tokens=_CHUNK_MAX_TOKENS, overlap_tokens=_OVERLAP_TOKENS))
            print(f"    解析 {len(text)} 字符 / {record['chunks']} 块（{fmt}）")

        extractor = KnowledgeExtractor()   # 每轮新建，避免跨轮状态影响计时
        t1 = time.perf_counter()
        result = await extractor.extract(text)
        extract_s = time.perf_counter() - t1

        err = result.get("error")
        if err:
            record["errors"].append(f"run{i + 1}: {err}")

        item = {
            "run": i + 1,
            "parse_s": round(parse_s, 3),
            "extract_s": round(extract_s, 3),
            "total_s": round(parse_s + extract_s, 3),
            "entities": len(result.get("entities", [])),
            "relations": len(result.get("relations", [])),
            "error": err,
        }
        record["runs"].append(item)
        print(f"    第 {i + 1}/{runs} 轮：解析 {parse_s:.2f}s + 抽取 {extract_s:.2f}s "
              f"= {item['total_s']:.2f}s（实体 {item['entities']} / 关系 {item['relations']}）")

    totals = [r["total_s"] for r in record["runs"] if not r["error"]]
    if totals:
        record["total_mean_s"] = round(sum(totals) / len(totals), 3)
        record["total_min_s"] = min(totals)
        record["total_max_s"] = max(totals)
        record["runs_ok"] = len(totals)
        record["pass"] = record["total_max_s"] <= THRESHOLD_SECONDS
    else:
        record["runs_ok"] = 0
        record["pass"] = False
    return record


async def main() -> int:
    ap = argparse.ArgumentParser(description="解析+抽取端到端耗时测试（赛题指标 ≤60s）")
    ap.add_argument("--files", nargs="*", default=None,
                    help="待测文件路径（相对 backend/）；默认用内置三档文本集")
    ap.add_argument("--runs", type=int, default=3, help="每个文件的独立轮数，默认 3")
    ap.add_argument("--output", default="eval_data/perf_timing.json", help="结果落盘路径")
    ap.add_argument("--parse-only", action="store_true",
                    help="只测解析耗时，不调用 LLM（零 API 成本）")
    args = ap.parse_args()

    files = args.files or DEFAULT_FILES
    missing = [f for f in files if not os.path.isfile(f)]
    if missing:
        print("✗ 文件不存在：" + "、".join(missing))
        return 1

    if args.parse_only:
        print("=== 仅解析（不调 LLM）===")
        rows = []
        for f in files:
            t0 = time.perf_counter()
            text = await DocumentParser.parse(f)
            el = time.perf_counter() - t0
            chunks = len(chunk_text_for_llm(
                text, max_tokens=_CHUNK_MAX_TOKENS, overlap_tokens=_OVERLAP_TOKENS))
            rows.append((f, os.path.getsize(f), len(text), chunks, el))
            print(f"  {el:7.2f}s  {len(text):>8} 字符  {chunks:>3} 块  {f}")
        out = {
            "kind": "parse_only",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "files": [{"file": f, "size_bytes": s, "parsed_chars": c,
                       "chunks": k, "parse_s": round(e, 3)}
                      for f, s, c, k, e in rows],
        }
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as fp:
            json.dump(out, fp, ensure_ascii=False, indent=2)
        print(f"\n结果已写入 {args.output}")
        return 0

    print(f"=== 解析 + 抽取端到端耗时（{len(files)} 个文件 × {args.runs} 轮）===")
    records = []
    for f in files:
        print(f"\n[{f}]")
        records.append(await measure_one(f, args.runs))

    out = {
        "kind": "parse_plus_extract",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "threshold_seconds": THRESHOLD_SECONDS,
        "params": {
            "model": settings.LLM_MODEL,
            "prompt_version": getattr(__import__("eval_config"), "PROMPT_VERSION", "unknown"),
            "temperature": 0.15,          # 运行时取值（KnowledgeExtractor 默认）
            "chunk_max_tokens": _CHUNK_MAX_TOKENS,
            "overlap_tokens": _OVERLAP_TOKENS,
            "max_concurrency": _MAX_CONCURRENCY,
            "runs_per_file": args.runs,
        },
        "files": records,
    }
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=2)

    print("\n=== 汇总 ===")
    print(f"{'文件':<48}{'字符':>9}{'块':>5}{'均值(s)':>10}{'最大(s)':>10}  判定")
    for r in records:
        mark = "✓ 达标" if r.get("pass") else "✗ 未达标/有失败轮次"
        mean = f"{r['total_mean_s']:.2f}" if r.get("total_mean_s") else "—"
        mx = f"{r['total_max_s']:.2f}" if r.get("total_max_s") else "—"
        print(f"{os.path.basename(r['file']):<48}{r['parsed_chars']:>9}{r['chunks']:>5}"
              f"{mean:>10}{mx:>10}  {mark}")
    print(f"\n结果已写入 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
