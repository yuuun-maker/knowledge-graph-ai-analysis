"""
题目推荐离线评估（P2）：用历史作答做「时间切分回测」

方法：
  1. 对每个学生，把其作答记录按时间排序后 **70% 作训练（可见历史）/ 30% 作测试（未来）**；
  2. 只用训练集构造推荐所需的全部信号（掌握度、逐题统计、错题、路径下一步）；
  3. 用打分器选 Top-N，与两种基线对比：
     - `random`      随机抽题（多次取平均，默认 30 次）
     - `wrong_first` 错题优先（把训练集里答错的题排前面）
     - `scorer`      本项目的 8 信号打分器（mixed 分层组卷）
  4. 指标（目标集合 = "未来答错的题"，即最该练的题）：
     - `HitRate@N`：Top-N 中命中目标集合的比例（命中数 / N）
     - `Coverage@N`：至少命中 1 个目标的学生比例
     - `NDCG@N`：命中位置的折损累积增益（越靠前越值钱）

⚠ 数据说明：当前是**小规模合成数据**（课程 65：5 名学生 × 约 140 条作答），作答由能力值模型
生成，因此"未来是否答错"本身具备一定可预测性 —— 指标用于**横向对比策略**，不等于线上效果承诺。

运行方式（backend 目录下，需 Neo4j 已启动以获得图谱信号）：
    python eval_question_recommend.py                # 默认课程 65，N=5
    python eval_question_recommend.py 65 101 5       # 课程 文档 N
"""
import math
import random
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.core.database import db
from app.core.sql_database import sql_db
from app.services import question_recommender as qr

COURSE_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 65
DOC_ID = int(sys.argv[2]) if len(sys.argv) > 2 else None
N = int(sys.argv[3]) if len(sys.argv) > 3 else 5
TRAIN_RATIO = 0.7
RANDOM_TRIALS = 30
RANDOM_SEED = 2026


def _hit_rate(picked, target):
    """Top-N 命中目标集合的比例（命中数 / N）"""
    return len(set(picked) & set(target)) / max(1, len(picked))


def _ndcg(picked, target):
    """二值相关性下的 NDCG@N（命中越靠前得分越高）"""
    dcg = sum(1.0 / math.log2(i + 2) for i, qid in enumerate(picked) if qid in target)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(picked), len(target))))
    return round(dcg / ideal, 4) if ideal else 0.0


def _pick_scorer(rows, train_records, manual_records, ctx, quality, q_kp, now):
    """用打分器在训练集信号上选 Top-N（复刻线上组卷：mixed 分桶 + 配额 + 题型均衡）"""
    answer_by_question = {}
    for r in train_records:
        st = answer_by_question.setdefault(
            r["question_id"],
            {"attempts": 0, "correct": 0, "last_at": None, "last_is_correct": False})
        st["attempts"] += 1
        st["correct"] += 1 if r["is_correct"] else 0
        ts = qr._parse_ts(r["answered_at"])
        if ts and (st["last_at"] is None or ts > st["last_at"]):
            st["last_at"], st["last_is_correct"] = ts, bool(r["is_correct"])

    enriched = [{"kp_id": q_kp.get(r["question_id"]), "is_correct": r["is_correct"],
                 "answered_at": r["answered_at"]} for r in train_records]
    mastery = qr.kp_mastery(enriched, manual_records, now=now)
    mastered_names = [ctx["names"].get(k) for k, v in mastery.items()
                      if (v.get("mastery") or 0) >= 80 and ctx["names"].get(k)]
    next_ids = (qr.next_knowledge_ids(COURSE_ID, DOC_ID, mastered_names, ctx)
                if ctx["available"] else set())

    candidates = qr.build_candidates(rows, answer_by_question, mastery, ctx, next_ids,
                                     quality, now=now)
    kp_limit = max(1, math.ceil(N / qr.KP_QUOTA_DIVISOR))
    kp_counter, used_types, used_qids, picked = {}, set(), set(), []
    for bucket, want in qr.allocate_buckets(N, "mixed").items():
        pool = [c for c in candidates if c["bucket"] == bucket]
        picked.extend(qr.pick_with_quota(pool, want, kp_counter, kp_limit,
                                         used_types, used_qids))
    if len(picked) < N:                      # 桶内不足 → 其余按分数回填
        rest = [c for c in candidates if c["question_id"] not in used_qids]
        picked.extend(qr.pick_with_quota(rest, N - len(picked), kp_counter, kp_limit,
                                         used_types, used_qids))
    return [c["question_id"] for c in sorted(picked, key=lambda c: -c["score"])][:N]


def main():
    course = sql_db.get_course(COURSE_ID)
    if course is None:
        print(f"✗ 课程不存在：course_id={COURSE_ID}")
        return False
    rows = [r for r in sql_db.list_questions(COURSE_ID, page=1, page_size=100000)[1]
            if r.get("is_active")]
    if not rows:
        print("✗ 该课程没有启用中的题目，无法评估")
        return False
    q_kp = {r["question_id"]: r.get("kp_id") for r in rows}
    ctx = qr.graph_context(COURSE_ID, DOC_ID)
    quality = sql_db.question_answer_stats(COURSE_ID)
    rng = random.Random(RANDOM_SEED)

    students = [r["user_id"] for r in sql_db._query(
        "SELECT DISTINCT user_id FROM t_answer_record WHERE course_id = ? ORDER BY user_id",
        (COURSE_ID,))]
    print(f"课程 {COURSE_ID}（{course['course_name']}）：{len(students)} 名学生，"
          f"{len(rows)} 道启用题，图谱可用={ctx['available']}，N={N}，训练/测试=7:3")

    agg_keys = ("hit_random", "cov_random", "ndcg_random", "hit_wrong", "cov_wrong",
                "ndcg_wrong", "hit_scorer", "cov_scorer", "ndcg_scorer")
    agg = {k: [] for k in agg_keys}
    per_student = []

    for uid in students:
        records = sql_db.list_answer_records(uid, course_id=COURSE_ID)
        records.sort(key=lambda r: (r["answered_at"] or "", r["record_id"]))
        cut = int(len(records) * TRAIN_RATIO)
        train, future = records[:cut], records[cut:]
        if not train or not future:
            continue
        target_wrong = {r["question_id"] for r in future if not r["is_correct"]}
        if not target_wrong:
            continue
        now = qr._parse_ts(future[0]["answered_at"]) or datetime.now()
        all_ids = [r["question_id"] for r in rows]

        # 基线 1：随机（多次平均）
        hits, covs, ndcgs = [], [], []
        for _ in range(RANDOM_TRIALS):
            picked = rng.sample(all_ids, min(N, len(all_ids)))
            hits.append(_hit_rate(picked, target_wrong))
            covs.append(1.0 if set(picked) & target_wrong else 0.0)
            ndcgs.append(_ndcg(picked, target_wrong))

        # 基线 2：错题优先（训练集答错的题排前，其余随机补足）
        wrong_first, seen = [], set()
        for r in train:
            if not r["is_correct"] and r["question_id"] in q_kp and r["question_id"] not in seen:
                wrong_first.append(r["question_id"])
                seen.add(r["question_id"])
        for qid in rng.sample(all_ids, len(all_ids)):
            if len(wrong_first) >= N:
                break
            if qid not in seen:
                wrong_first.append(qid)
                seen.add(qid)

        # 打分器（只用训练集信号）
        manual_records = sql_db.list_records_by_user_course(uid, COURSE_ID)
        scorer_ids = _pick_scorer(rows, train, manual_records, ctx, quality, q_kp, now)

        row = {
            "uid": uid, "train": len(train), "future": len(future),
            "wrong_future": len(target_wrong),
            "hit_random": sum(hits) / len(hits),
            "cov_random": sum(covs) / len(covs),
            "ndcg_random": sum(ndcgs) / len(ndcgs),
            "hit_wrong": _hit_rate(wrong_first, target_wrong),
            "cov_wrong": 1.0 if set(wrong_first) & target_wrong else 0.0,
            "ndcg_wrong": _ndcg(wrong_first, target_wrong),
            "hit_scorer": _hit_rate(scorer_ids, target_wrong),
            "cov_scorer": 1.0 if set(scorer_ids) & target_wrong else 0.0,
            "ndcg_scorer": _ndcg(scorer_ids, target_wrong),
        }
        per_student.append(row)
        for k in agg_keys:
            agg[k].append(row[k])

    if not per_student:
        print("✗ 没有可用于回测的学生（作答量不足）")
        return False

    n = len(per_student)
    avg = {k: sum(v) / n for k, v in agg.items()}
    print("\n" + "=" * 80)
    print(f"{'学生':>6} {'训练':>5} {'未来':>5} {'未来错题':>8} | "
          f"{'随机HitRate':>11} {'错题优先':>9} {'打分器':>8} | {'打分器NDCG':>10}")
    print("-" * 80)
    for r in per_student:
        print(f"{r['uid']:>6} {r['train']:>5} {r['future']:>5} {r['wrong_future']:>8} | "
              f"{r['hit_random']:>11.3f} {r['hit_wrong']:>9.3f} {r['hit_scorer']:>8.3f} | "
              f"{r['ndcg_scorer']:>10.4f}")
    print("-" * 80)
    print(f"{'平均':>6} {'':>5} {'':>5} {'':>8} | "
          f"{avg['hit_random']:>11.3f} {avg['hit_wrong']:>9.3f} {avg['hit_scorer']:>8.3f} | "
          f"{avg['ndcg_scorer']:>10.4f}")
    print("=" * 80)
    print(f"HitRate@{N}（未来错题命中率）: 随机 {avg['hit_random']:.3f} | "
          f"错题优先 {avg['hit_wrong']:.3f} | 打分器 **{avg['hit_scorer']:.3f}**")
    print(f"Coverage@{N}（至少命中 1 个）  : 随机 {avg['cov_random']:.3f} | "
          f"错题优先 {avg['cov_wrong']:.3f} | 打分器 **{avg['cov_scorer']:.3f}**")
    print(f"NDCG@{N}                      : 随机 {avg['ndcg_random']:.4f} | "
          f"错题优先 {avg['ndcg_wrong']:.4f} | 打分器 **{avg['ndcg_scorer']:.4f}**")
    print("=" * 80)
    print("说明：小规模合成数据（能力值模型生成），指标用于横向对比策略，不等于线上效果。")
    db.close()
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
