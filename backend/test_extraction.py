"""
测试 LLM 知识提取：读取指定路径的课程文档，调用 knowledge_extractor.py 中的
EXTRACTION_PROMPT（DeepSeek 大模型）抽取知识点实体与关系，并把结果 JSON
保存到该文档所在目录下。

运行方式（在 backend 目录下执行）：
    python test_extraction.py <文档路径>
    python test_extraction.py <文档路径> --temperature 0          # 正式评测：消除采样随机性
    python test_extraction.py <文档路径> -o D:/out/result.json    # 自定义输出路径

支持格式：txt / md / pdf / docx（由 app/services/document_parser.py 解析）
默认输出：<输入文件同目录>/<文件名>_extraction.json
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# Windows 控制台默认 GBK，避免中文/特殊字符输出报错
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.services.document_parser import DocumentParser
from app.services.knowledge_extractor import KnowledgeExtractor


def print_result(result: dict, elapsed: float, model: str) -> None:
    """美化打印提取结果"""
    if result.get("error"):
        print(f"[错误] {result['error']}")
        return

    entities = result.get("entities", [])
    relations = result.get("relations", [])

    print("=" * 60)
    print(f"提取到 {len(entities)} 个实体、{len(relations)} 条关系"
          f"（模型 {model}，耗时 {elapsed:.1f} 秒）")
    print("=" * 60)

    print("\n[实体]")
    for e in entities:
        print(f"  - {e.get('name')}（{e.get('category')}）：{e.get('description')}")

    print("\n[关系三元组] (主体) -[关系]-> (客体)")
    for r in relations:
        confidence = r.get("confidence")
        confidence_str = f"，置信度 {confidence}" if confidence is not None else ""
        print(f"  - ({r.get('source')}) -[{r.get('type')}]-> ({r.get('target')}){confidence_str}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="读取课程文档并调用大模型抽取知识图谱 JSON（保存到文档所在目录）"
    )
    parser.add_argument("file", help="待抽取的课程文档路径（支持 txt/md/pdf/docx）")
    parser.add_argument(
        "-o", "--output",
        help="结果 JSON 输出路径；默认为输入文件同目录下的 <文件名>_extraction.json",
    )
    parser.add_argument(
        "--temperature", type=float, default=0.15,
        help="LLM 采样温度，默认 0.15；正式评测传 0（默认：%(default)s）",
    )
    return parser.parse_args()


async def run() -> int:
    args = parse_args()

    input_path = Path(args.file).expanduser().resolve()
    if not input_path.is_file():
        print(f"[错误] 文件不存在：{input_path}")
        return 1
    ext = input_path.suffix.lower()
    if ext not in DocumentParser.SUPPORTED_EXTENSIONS:
        print(f"[错误] 不支持的文件格式 {ext}，仅支持 {sorted(DocumentParser.SUPPORTED_EXTENSIONS)}")
        return 1

    print(f"[1/3] 解析文档：{input_path}")
    text = await DocumentParser.parse(str(input_path))
    if not text.strip():
        print("[错误] 文档解析后为空，无法抽取")
        return 1
    print(f"      解析得到 {len(text)} 字符")

    print(f"[2/3] 调用大模型抽取（{args.temperature=}）...")
    extractor = KnowledgeExtractor(temperature=args.temperature)
    start = time.perf_counter()
    result = await extractor.extract(text)
    elapsed = time.perf_counter() - start

    if result.get("error"):
        print_result(result, elapsed, extractor.client.base_url)
        return 1

    out_path = (
        Path(args.output).expanduser().resolve() if args.output
        else input_path.parent / f"{input_path.stem}_extraction.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print_result(result, elapsed, str(extractor.client.base_url))
    print(f"\n[3/3] 结果已保存：{out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
