"""
题目推荐打分器（P2）

把「随机抽题」升级为「按学生学情选卷」：对候选题池逐题打分 → 分桶 → 配额裁剪 → 题型均衡，
并给每题生成人类可读的推荐理由（前端可直接展示）。

八个信号（权重集中在下方常量，便于调参与实验）：

| 信号 | 含义 | 数据来源 |
|------|------|----------|
| ① 薄弱度 need | 该知识点掌握度越低越该练 | 掌握度（本模块 `kp_mastery()`） |
| ② 遗忘到期 due | 距上次作答越久越该复习 | `t_answer_record.answered_at` |
| ③ 难度适配 diff_fit | 目标难度 = 1 + 4·掌握度/100（最近发展区） | `t_question.difficulty` |
| ④ 新颖度 novelty | 没做过 > 做错过 > 做过且最近答对 | `t_answer_record` |
| ⑤ 错题优先 wrong_flag | 最近一次答错的题优先 | `t_answer_record` |
| ⑥ 知识点重要性 | 图谱中度数越高的知识点越优先 | Neo4j 度数（`(n)--(m)`） |
| ⑦ 题目区分度 quality | 全班正确率过高/过低（≥3 次作答后）降权 | 全班作答统计 |
| ⑧ 多样性配额 | 同知识点题数上限 + 题型均衡 | 组卷阶段 |

分桶（`mode`）：
- `weak`     薄弱强化（掌握度 ≤ 60 的知识点）
- `review`   复习巩固（做过且到期，或最近答错）
- `new`      路径新知识（`PathRecommender` 推荐的下一步知识点）
- `advanced` 进阶提升（掌握度 ≥ 70 的巩固题）
- `mixed`    分层组卷（默认，四桶按比例拼卷，桶内不足自动回填）
- `random`   随机基线（用于与现状对照 / A-B 实验）

掌握度说明：这里是**推荐用的轻量掌握度**（练习表现 + 学生自评，读时计算、不落库）；
对外公开的「掌握度指标」与前端展示属后续工作，本模块先把内部实现沉淀成可复用函数。
"""
import math
import random
from datetime import datetime

from ..core.database import db
from ..core.sql_database import sql_db

# ---------- 权重与阈值（调参集中在此） ----------

W_NEED = 0.35          # 薄弱度（掌握度越低越优先）
W_DUE = 0.20           # 遗忘到期（越久没练越优先）
W_DIFF = 0.15          # 难度适配（最近发展区）
W_NOVELTY = 0.10       # 新颖度（没做过优先，避免反复刷同一题）
W_WRONG = 0.10         # 最近答错优先
W_IMPORTANCE = 0.10    # 知识点图谱重要性（度数）

HALF_LIFE_DAYS = 14.0  # 练习表现的时间衰减半衰期（天）
REVIEW_DUE_DAYS = 7.0  # 超过该天数未练视为"该复习"
WEAK_THRESHOLD = 60.0  # 掌握度 ≤ 60 记入「薄弱」
ADVANCED_THRESHOLD = 70.0   # 掌握度 ≥ 70 记入「进阶」
MASTERY_DEFAULT = 50.0      # 无任何证据时的中性掌握度
DIFF_SLOPE = 4.0            # 目标难度 = 1 + DIFF_SLOPE·掌握度/100（难度取 1-5）
QUALITY_MIN_ATTEMPTS = 3    # 全班作答达到该次数后才评估区分度
QUALITY_LOW, QUALITY_HIGH = 0.2, 0.95   # 正确率低于/高于该值视为区分度差
QUALITY_PENALTY = 0.3                   # 区分度差时的乘性惩罚
KP_QUOTA_DIVISOR = 3        # 同一知识点的题数上限 = ceil(count / 该值)

# mixed 模式的四桶配比（按 count 分配，余数依次补给靠前的桶）
MIXED_RATIO = (("weak", 0.40), ("review", 0.25), ("new", 0.20), ("advanced", 0.15))

VALID_MODES = ("weak", "review", "new", "advanced", "mixed", "random")

BUCKET_LABELS = {
    "weak": "薄弱强化", "review": "复习巩固", "new": "路径新知识",
    "advanced": "进阶提升", "random": "随机练习",
}


def _parse_ts(text):
    """解析 'YYYY-MM-DD HH:MM:SS'（t_answer_record.answered_at 的存储格式）"""
    if not text:
        return None
    try:
        return datetime.strptime(str(text)[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def kp_mastery(answer_records, manual_records, now=None, half_life_days: float = HALF_LIFE_DAYS) -> dict:
    """按知识点算「轻量掌握度」（0-100），返回 {kp_id: {...}}。

    练习信号：时间衰减加权的正确率
        acc = Σ w_i·correct_i / Σ w_i ,  w_i = 0.5 ^ (Δdays / half_life)
    自评信号：MASTERED=1.0 / LEARNING=0.5 / 其他=0
    融合：有练习数据 → 0.5·acc + 0.5·自评；无练习数据 → 自评（evidence=0，前端可标注"证据不足"）

    `answer_records` / `manual_records` 由调用方传入（同一学生同一课程），避免重复查库。
    """
    now = now or datetime.now()
    buckets = {}
    for r in answer_records:
        kp_id = r.get("kp_id") or r.get("question_kp_id")
        if not kp_id:
            continue
        answered_at = _parse_ts(r.get("answered_at"))
        delta_days = max(0.0, (now - answered_at).total_seconds() / 86400) if answered_at else 0.0
        weight = 0.5 ** (delta_days / half_life_days)
        b = buckets.setdefault(kp_id, {"w_sum": 0.0, "w_correct": 0.0, "attempts": 0,
                                       "last_at": None, "days_since": None})
        b["w_sum"] += weight
        # 掌握度得分（Scope B）：教师批改后的主观题可能得部分分（0~100），
        # 用 score/100 参与加权比布尔 is_correct 更贴近真实掌握程度；
        # 记录未携带 score 时退回 is_correct（与旧调用方/旧数据兼容）。
        score = r.get("score")
        if score is None:
            credit = 1.0 if r.get("is_correct") else 0.0
        else:
            try:
                credit = _clamp(float(score) / 100.0)
            except (TypeError, ValueError):
                credit = 1.0 if r.get("is_correct") else 0.0
        b["w_correct"] += weight * credit
        b["attempts"] += 1
        if answered_at and (b["last_at"] is None or answered_at > b["last_at"]):
            b["last_at"] = answered_at
    for kp_id, b in buckets.items():
        if b["last_at"]:
            b["days_since"] = round((now - b["last_at"]).total_seconds() / 86400, 2)

    manual = {}
    for r in manual_records:
        kp_id = r.get("kp_id")
        if not kp_id:
            continue
        status = r.get("status")
        score = 1.0 if status == "MASTERED" else (0.5 if status == "LEARNING" else 0.0)
        prev = manual.get(kp_id)
        if prev is None or score > prev:
            manual[kp_id] = score

    result = {}
    for kp_id in set(buckets) | set(manual):
        b = buckets.get(kp_id)
        acc = (b["w_correct"] / b["w_sum"]) if b and b["w_sum"] > 0 else None
        manual_score = manual.get(kp_id)
        if acc is None and manual_score is None:
            mastery = None
        elif acc is None:
            mastery = manual_score * 100
        elif manual_score is None:
            mastery = acc * 100
        else:
            mastery = (0.5 * acc + 0.5 * manual_score) * 100
        result[kp_id] = {
            "mastery": round(mastery, 1) if mastery is not None else None,
            "accuracy": round(acc * 100, 1) if acc is not None else None,
            "manual": manual_score,
            "attempts": b["attempts"] if b else 0,
            "last_at": b["last_at"].strftime("%Y-%m-%d %H:%M:%S") if b and b["last_at"] else None,
            "days_since": b["days_since"] if b else None,
        }
    return result


def graph_context(course_id: int, document_id=None) -> dict:
    """取图谱上下文：`kp_id → 名称`、`kp_id → 归一化度数（重要性）`、图谱是否可用。

    图谱不可用（未启动/查询异常）时全部降级：`available=False`，重要性取中性 0.5，
    名称回落到 `kp_id`，"路径新知识"桶自动失效——不抛异常、不阻塞出题。
    """
    ctx = {"available": False, "names": {}, "importance": {}}
    try:
        cypher = ("MATCH (n:KnowledgePoint {course_id: $cid"
                  + (", document_id: $did" if document_id else "") + "}) "
                  "OPTIONAL MATCH (n)--(m:KnowledgePoint) "
                  "RETURN n.kp_id AS kp_id, n.name AS name, count(m) AS degree")
        params = {"cid": course_id}
        if document_id:
            params["did"] = document_id
        rows = db.query(cypher, params)
    except Exception:
        return ctx
    if not rows:
        return ctx

    ctx["available"] = True
    max_degree = max((r.get("degree") or 0) for r in rows) or 1
    for r in rows:
        kp_id = r.get("kp_id")
        if not kp_id:
            continue
        ctx["names"][kp_id] = r.get("name") or kp_id
        ctx["importance"][kp_id] = _clamp((r.get("degree") or 0) / max_degree)
    return ctx


def next_knowledge_ids(course_id: int, document_id, mastered_names, ctx) -> set:
    """学习路径推荐的「下一步知识点」→ kp_id 集合（图谱不可用/无推荐时返回空集）。"""
    from .path_recommender import PathRecommender      # 延迟导入：避免模块级循环依赖
    try:
        recs = PathRecommender.recommend_next(mastered_names or [], course_id, document_id)
    except Exception:
        return set()
    name_to_kp = {name: kp_id for kp_id, name in (ctx.get("names") or {}).items()}
    return {name_to_kp[r.get("name")] for r in recs if r.get("name") in name_to_kp}


def _target_difficulty(mastery: float) -> float:
    """最近发展区：掌握度越高，越应该给难题（目标难度 1-5）"""
    return 1.0 + DIFF_SLOPE * (mastery / 100.0)


def _reason(bucket: str, kp_name: str, mastery, mine, days_since, quality_flag: bool) -> str:
    """生成人类可读的推荐理由（前端直接展示，也便于解释"为什么推这题"）"""
    name = kp_name or "该知识点"
    if bucket == "review":
        if days_since is not None:
            return f"「{name}」最近答错，已隔 {days_since:.0f} 天，建议复习巩固"
        return f"「{name}」最近答错，建议复习巩固"
    if bucket == "new":
        return f"「{name}」是学习路径推荐的下一步，可以开始练了"
    if bucket == "weak":
        if mastery is None:
            return f"「{name}」还没有作答记录，建议先摸底练几题"
        return f"「{name}」掌握度 {mastery:.0f}%，建议巩固薄弱点"
    return f"「{name}」掌握度 {mastery:.0f}%，来道进阶题保持手感"


def build_candidates(rows, answer_by_question: dict, mastery: dict, ctx: dict,
                     next_kp_ids: set, quality_stats: dict, now=None) -> list:
    """把题目行 + 各信号组装成「带分数 / 桶 / 理由」的候选列表（按分数降序）。"""
    now = now or datetime.now()
    candidates = []
    names = ctx.get("names") or {}
    for row in rows:
        qid = row["question_id"]
        kp_id = row.get("kp_id")
        kp_info = mastery.get(kp_id) or {}
        m = kp_info.get("mastery")
        m_eff = m if m is not None else MASTERY_DEFAULT

        need = _clamp((100.0 - m_eff) / 100.0)
        mine = answer_by_question.get(qid)
        days_since = None
        if mine and mine.get("last_at"):
            days_since = max(0.0, (now - mine["last_at"]).total_seconds() / 86400)
        due = _clamp(days_since / REVIEW_DUE_DAYS) if days_since is not None else 0.0

        difficulty = row.get("difficulty") or 3
        diff_fit = _clamp(1.0 - abs(difficulty - _target_difficulty(m_eff)) / DIFF_SLOPE)
        # 对错语义（Scope B）：last_is_correct 可能是 None（待批改）——
        # 只有明确的 False 才算"最近答错"，明确的 True 才算"掌握得不错"。
        novelty = 1.0 if not mine else (0.3 if mine.get("last_is_correct") is True else 0.5)
        wrong_flag = 1.0 if (mine and mine.get("last_is_correct") is False) else 0.0
        importance = ctx["importance"].get(kp_id, 0.5) if ctx.get("available") else 0.5

        score = (W_NEED * need + W_DUE * due + W_DIFF * diff_fit
                 + W_NOVELTY * novelty + W_WRONG * wrong_flag + W_IMPORTANCE * importance)

        # 区分度：全班正确率过高（太水）/过低（太偏）降权，需至少 QUALITY_MIN_ATTEMPTS 次作答
        st = quality_stats.get(qid) or {}
        q_attempts = st.get("attempts", 0)
        q_rate = (st.get("correct", 0) / q_attempts) if q_attempts else None
        quality_flag = bool(q_attempts >= QUALITY_MIN_ATTEMPTS and q_rate is not None
                            and (q_rate < QUALITY_LOW or q_rate > QUALITY_HIGH))
        if quality_flag:
            score *= (1.0 - QUALITY_PENALTY)

        if wrong_flag:
            bucket = "review"
        elif kp_id in next_kp_ids:
            bucket = "new"
        elif m is None or need >= (100.0 - WEAK_THRESHOLD) / 100.0:
            bucket = "weak"
        else:
            bucket = "advanced"

        candidates.append({
            "row": row,
            "question_id": qid,
            "q_type": row.get("q_type"),
            "difficulty": difficulty,
            "kp_id": kp_id,
            "kp_name": names.get(kp_id) if kp_id else None,
            "bucket": bucket,
            "score": round(score, 4),
            "mastery": m,
            "attempts": (mine or {}).get("attempts", 0),
            "reason": _reason(bucket, names.get(kp_id), m, mine, days_since, quality_flag),
            "signals": {
                "need": round(need, 3), "due": round(due, 3), "diff_fit": round(diff_fit, 3),
                "novelty": novelty, "wrong": wrong_flag,
                "importance": round(importance, 3), "quality_flag": quality_flag,
            },
        })
    candidates.sort(key=lambda c: (-c["score"], c["question_id"]))
    return candidates


def allocate_buckets(count: int, mode: str) -> dict:
    """按模式算各桶目标数量（mixed 按 MIXED_RATIO 分配，余数补给靠前的桶）"""
    if mode == "mixed":
        targets, assigned = {}, 0
        for bucket, ratio in MIXED_RATIO:
            targets[bucket] = int(count * ratio)
            assigned += targets[bucket]
        for bucket, _ in MIXED_RATIO:
            if assigned >= count:
                break
            targets[bucket] += 1
            assigned += 1
        return targets
    return {}                              # 单桶模式：由调用方按 mode 直接取该桶


def pick_with_quota(cands, want, kp_counter, kp_limit, used_types, used_qids) -> list:
    """从候选里挑 want 题：遵守「同知识点题数上限」，并优先补上尚未出现的题型。

    两轮挑选：第一轮只接受"题型还没出现过"的题（题型均衡），第二轮放开该限制补足数量。
    未挂知识点的题（kp_id 为空）不占知识点配额，按题计数。
    """
    picked = []
    for prefer_new_type in (True, False):
        for c in cands:
            if len(picked) >= want:
                return picked
            if c["question_id"] in used_qids:
                continue
            key = c["kp_id"] or f"__q{c['question_id']}"
            if kp_counter.get(key, 0) >= kp_limit:
                continue
            if prefer_new_type and c["q_type"] in used_types:
                continue
            picked.append(c)
            used_qids.add(c["question_id"])
            kp_counter[key] = kp_counter.get(key, 0) + 1
            used_types.add(c["q_type"])
    return picked


class QuestionRecommender:
    """题目推荐器：打分 → 分桶 → 配额裁剪 → 题型均衡。

    `recommend()` 返回的是**数据库原始行**（含 answer/options），调用方必须走
    `PracticeService._public_view()` 投影后再下发给学生——防泄题纪律不能破。
    """

    @staticmethod
    def recommend(user_id: int, course_id: int, document_id=None, kp_id: str = None,
                  q_type: str = None, count: int = 10, mode: str = "mixed",
                  seed: int = None, now=None) -> dict:
        """返回 {"items": [{row, reason, bucket, kp_name, mastery, signals}], "meta": {...}}"""
        now = now or datetime.now()
        rng = random.Random(seed) if seed is not None else random.Random()
        mode = (mode or "mixed").lower()
        if mode not in VALID_MODES:
            mode = "mixed"

        # 1) 候选池（仅启用中的题；文档级作用域自动含课程通用题）
        #    Scope B：auto_grade_only=True —— 主观题（FILL/ESSAY）不进自动组卷候选池，
        #    实现「自动组卷不硬插入主观题」；学生显式指定 q_type=FILL/ESSAY 时才会取到。
        _, rows = sql_db.list_questions(
            course_id, document_id=document_id, kp_id=(kp_id or "").strip() or None,
            q_type=(q_type or "").strip().upper() or None, is_active=True,
            page=1, page_size=100000, auto_grade_only=True,
        )
        # 2) 课程全部题目：把作答记录映射到知识点 + 全班区分度统计
        #    区分度统计内部已按 grade_status='GRADED' 过滤（未批改的主观题不参与）
        _, all_rows = sql_db.list_questions(course_id, page=1, page_size=100000)
        q_kp = {r["question_id"]: r.get("kp_id") for r in all_rows}
        quality_stats = sql_db.question_answer_stats(course_id)

        # 3) 我的作答 → 逐题统计（最近一次/次数）+ 知识点维度明细
        #    口径：逐题统计包含「待批改」记录（学生确实做过，影响新颖度与遗忘到期），
        #    但对错只在已批改记录上判定；掌握度只喂已批改记录（未批改对错未知）。
        records = sql_db.list_answer_records(user_id, course_id=course_id)
        answer_by_question, enriched = {}, []
        for r in records:
            qid = r["question_id"]
            graded = (r.get("grade_status") or "GRADED") == "GRADED"
            st = answer_by_question.setdefault(
                qid, {"attempts": 0, "correct": 0, "last_at": None, "last_is_correct": False})
            st["attempts"] += 1
            ts = _parse_ts(r["answered_at"])
            if graded:
                st["correct"] += 1 if r["is_correct"] else 0
                if ts and (st["last_at"] is None or ts > st["last_at"]):
                    st["last_at"], st["last_is_correct"] = ts, bool(r["is_correct"])
                # score 一并传入：教师批改后的主观题可能得部分分（见 kp_mastery）
                enriched.append({"kp_id": q_kp.get(qid), "is_correct": r["is_correct"],
                                 "score": r["score"], "answered_at": r["answered_at"]})
            else:
                # 待批改：只更新"最近作答时间"，对错标记为 None（既不当作对，也不当作错）
                if ts and (st["last_at"] is None or ts > st["last_at"]):
                    st["last_at"], st["last_is_correct"] = ts, None

        # 4) 轻量掌握度（练习表现 + 学生自评；读时计算，不落库）
        manual = sql_db.list_records_by_user_course(user_id, course_id)
        mastery = kp_mastery(enriched, manual, now=now)

        # 5) 图谱上下文 + 学习路径的"下一步知识点"
        ctx = graph_context(course_id, document_id)
        mastered_names = [ctx["names"].get(k) for k, v in mastery.items()
                          if (v.get("mastery") or 0) >= 80 and ctx["names"].get(k)]
        next_ids = (next_knowledge_ids(course_id, document_id, mastered_names, ctx)
                    if ctx["available"] else set())

        # 6) 逐题打分
        candidates = build_candidates(rows, answer_by_question, mastery, ctx, next_ids,
                                      quality_stats, now=now)
        if mode == "random":
            rng.shuffle(candidates)

        # 7) 组卷：桶配额 + 同知识点题数上限 + 题型均衡；不足时回填、再不足则放宽配额
        kp_limit = max(1, math.ceil(count / KP_QUOTA_DIVISOR))
        kp_counter, used_types, used_qids, picked = {}, set(), set(), []
        bucket_counts = {}
        if mode == "random":
            picked = pick_with_quota(candidates, count, kp_counter, kp_limit,
                                     used_types, used_qids)
            bucket_counts = {"random": len(picked)}
        else:
            for bucket, want in (allocate_buckets(count, mode) or {mode: count}).items():
                pool = [c for c in candidates if c["bucket"] == bucket]
                got = pick_with_quota(pool, want, kp_counter, kp_limit, used_types, used_qids)
                bucket_counts[bucket] = len(got)
                picked.extend(got)
            if len(picked) < count:                     # 桶内不足 → 其余桶按分数回填
                rest = [c for c in candidates if c["question_id"] not in used_qids]
                extra = pick_with_quota(rest, count - len(picked), kp_counter, kp_limit,
                                        used_types, used_qids)
                bucket_counts["filled"] = len(extra)
                picked.extend(extra)
            if len(picked) < count:                     # 仍不足（配额卡住）→ 放宽配额凑满
                rest = [c for c in candidates if c["question_id"] not in used_qids]
                extra = pick_with_quota(rest, count - len(picked), kp_counter, 10 ** 6,
                                        used_types, used_qids)
                bucket_counts["quota_relaxed"] = len(extra)
                picked.extend(extra)

        picked.sort(key=lambda c: (-c["score"], c["question_id"]))
        meta = {
            "mode": mode,
            "count": len(picked),
            "requested": count,
            "buckets": bucket_counts,
            "candidates": len(candidates),
            # Scope B：自动组卷默认排除主观题；显式指定 q_type=FILL/ESSAY 时才是 "requested"
            "subjectivity_policy": ("requested"
                                    if (q_type or "").strip().upper() in ("FILL", "ESSAY")
                                    else "excluded"),
            "kp_quota": kp_limit,
            "mastery_available": any(v.get("mastery") is not None for v in mastery.values()),
            "graph_available": ctx["available"],
            "next_kp_ids": sorted(next_ids),
            "weights": {"need": W_NEED, "due": W_DUE, "diff_fit": W_DIFF,
                        "novelty": W_NOVELTY, "wrong": W_WRONG, "importance": W_IMPORTANCE},
        }
        if mode not in ("mixed", "random"):
            # 单桶模式：桶内无题时会用其它桶回填，这里显式告知（前端可提示"该类型暂无题"）
            meta["requested_bucket"] = mode
            meta["requested_bucket_count"] = bucket_counts.get(mode, 0)
            meta["bucket_empty"] = bucket_counts.get(mode, 0) == 0
        return {
            "items": [{
                "row": c["row"], "reason": c["reason"], "bucket": c["bucket"],
                "bucket_label": BUCKET_LABELS.get(c["bucket"], c["bucket"]),
                "kp_id": c["kp_id"], "kp_name": c["kp_name"], "mastery": c["mastery"],
                "attempts": c["attempts"], "score": c["score"], "signals": c["signals"],
            } for c in picked],
            "meta": meta,
        }
