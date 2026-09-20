"""
LLM 兜底抽题（Scope D / P2.3）

用途：规则解析搞不定的版式（**答案逐题内嵌**、**答案区不完整**、版式怪异）交给 LLM。
原则：
  1. **答案必须来自原文**，文本里没有就留空，严禁让模型自己解题（错答案比没答案更糟）；
  2. 严格 JSON 输出 + 三级容错解析（沿用 knowledge_extractor 的既有做法）；
  3. **后校验**把关：题型白名单、答案字母必须落在选项集合内、主观题必须有参考答案；
  4. 只做「补空」：与规则结果合并时**规则优先**，LLM 只填规则漏掉的题。
"""

import json
import re

from openai import OpenAI

from ..core.config import settings

QUESTION_EXTRACTION_PROMPT = """你是试题结构化专家。请从给定课程文本中抽取试题，并输出严格 JSON。

## 规则
1. 只抽取文本中**真实存在**的试题；不要臆造题目；看不清或不确定的题直接跳过。
2. 答案必须来自文本（题目后紧跟的“答案/解答”，或文末答案区）。
   - 文本中没有给出答案时：answer 填空字符串 ""，**绝对不要自己解题**。
   - 选择题答案写选项字母（如 "B"）；多选写数组（如 ["A","C"]）。
3. q_type 只能取：SINGLE（单选）/ MULTI（多选）/ JUDGE（判断，answer 为 "true" 或 "false"）/
   FILL（填空）/ ESSAY（解答）。
4. 选项写成 [{"key":"A","text":"..."}]；没有选项时用 []。
5. 只输出 JSON，不要 Markdown 代码块，不要任何解释文字。

## 输出格式
{"questions":[{"number":1,"q_type":"SINGLE","stem":"题干","options":[{"key":"A","text":"选项"}],"answer":"B","analysis":""}]}

## 课程文本
{text}"""

VALID_TYPES = ("SINGLE", "MULTI", "JUDGE", "FILL", "ESSAY")
MAX_STEM_LEN = 1000


def _parse_json(content: str) -> dict:
    """三级容错解析（与 knowledge_extractor 同款）：直接解析 → 去代码块 → 正则取 JSON"""
    if not content:
        return {"questions": []}
    text = content.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {"questions": []}


def _normalize_item(item: dict):
    """后校验 + 归一化；不合格返回 None（宁缺毋滥）"""
    if not isinstance(item, dict):
        return None
    q_type = (item.get("q_type") or "").strip().upper()
    stem = (item.get("stem") or "").strip()
    if q_type not in VALID_TYPES or not stem or len(stem) > MAX_STEM_LEN:
        return None

    options, keys = [], set()
    for i, opt in enumerate(item.get("options") or []):
        if isinstance(opt, dict):
            key = str(opt.get("key") or chr(65 + i)).strip().upper()
            text = str(opt.get("text") or "").strip()
        else:
            key, text = chr(65 + i), str(opt).strip()
        if text:
            options.append({"key": key, "text": text})
            keys.add(key)

    answer = item.get("answer")
    if q_type in ("SINGLE", "MULTI"):
        if len(options) < 2:
            return None                                  # 选择题必须给出选项
        letters = answer if isinstance(answer, list) else [answer]
        letters = sorted({str(x).strip().upper() for x in letters if str(x).strip()})
        if not letters or any(x not in keys for x in letters):
            answer = None                                # 答案不在选项内 → 视为缺答案（交教师补）
        else:
            q_type = "MULTI" if len(letters) > 1 else "SINGLE"
            answer = letters[0] if len(letters) == 1 else letters
    elif q_type == "JUDGE":
        low = str(answer or "").strip().lower()
        answer = "true" if low in ("true", "对", "正确", "是", "t", "1") else (
            "false" if low in ("false", "错", "错误", "否", "f", "0") else None)
    else:                                                # FILL / ESSAY：必须有参考答案
        answer = (answer if isinstance(answer, str) else "").strip() or None
        if not answer:
            return None

    warnings = []
    if answer in (None, "", []):
        warnings.append("answer_missing")
    return {
        "number": item.get("number"),
        "q_type": q_type,
        "stem": stem,
        "options": options,
        "answer": answer,
        "analysis": (item.get("analysis") or "").strip(),
        "warnings": warnings,
        "import_status": "NEEDS_REVIEW" if warnings else "READY",
        "confidence": 0.6 if warnings else 0.8,
        "source": "LLM",
    }


class QuestionExtractor:
    """LLM 抽题（同步客户端；由调用方串行执行以控制成本与限流）"""

    def __init__(self, temperature: float = 0.0):
        self.client = OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_API_BASE)
        self.temperature = temperature
        self.calls = 0
        self.prompt_tokens = 0

    def extract(self, text: str, max_questions: int = None, max_calls: int = None) -> dict:
        """对一段文本抽题；返回 {"questions": [...], "calls": n, "chars": len(text)}

        max_calls 为本次调用的硬上限（预算保护）：达到后立即停止，返回已抽取的部分。
        """
        from ..utils.text_processor import chunk_text_for_llm

        chunks = chunk_text_for_llm(text, max_tokens=6000, overlap_tokens=0)
        items = []
        for chunk in chunks:
            if max_calls is not None and self.calls >= max_calls:
                break
            self.calls += 1
            self.prompt_tokens += max(1, len(chunk) // 3)      # 粗估（中文约 3 字符/token）
            try:
                resp = self.client.chat.completions.create(
                    model=settings.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": "你只输出 JSON。"},
                        {"role": "user",
                         "content": QUESTION_EXTRACTION_PROMPT.replace("{text}", chunk)},
                    ],
                    temperature=self.temperature,
                    max_tokens=4096,
                    timeout=settings.EXTRACTION_TIMEOUT,
                )
                data = _parse_json(resp.choices[0].message.content)
            except Exception:
                continue                                        # 单块失败不影响整体（与抽取服务同策略）
            for raw in (data.get("questions") or []):
                normalized = _normalize_item(raw)
                if normalized:
                    items.append(normalized)
            if max_questions and len(items) >= max_questions:
                break
        return {"questions": items[:max_questions] if max_questions else items,
                "calls": self.calls, "chars": len(text)}


def merge_items(rule_items: list, llm_items: list) -> tuple:
    """合并规则与 LLM 结果：**规则优先**，LLM 只补规则没有的题。

    判重键：优先题号（两边都有 number 时），否则题干归一化文本。
    返回 (merged, stats)。
    """

    def _stem_key(text):
        return re.sub(r"[\s　]+", "",
                      re.sub(r"^\s*\d{1,3}\s*[.、．]\s*", "", text or ""))[:120]

    merged = list(rule_items)
    seen_numbers = {i.get("number") for i in rule_items if i.get("number")}
    seen_stems = {_stem_key(i.get("stem")) for i in rule_items}
    added = 0
    for item in llm_items:
        number, key = item.get("number"), _stem_key(item.get("stem"))
        if (number and number in seen_numbers) or key in seen_stems:
            continue                                            # 规则已有 → 保留规则结果
        merged.append(item)
        seen_numbers.add(number)
        seen_stems.add(key)
        added += 1
    return merged, {"rule_count": len(rule_items), "llm_count": len(llm_items),
                    "llm_added": added}

