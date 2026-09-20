"""
E3｜论文 3.3 节布隆过滤器复现与超越（避免重复推荐已做过的题）

论文只做了公式推导（m/k/误判率）并把 Bloom 直接用于"避免二次推荐"，
但没处理：删除/过期、分片、负向验证正确性、以及与精确集合的代价对比。本脚本补齐这四项。

四组实验：
  A) 公式复现：m = -n·ln p/(ln2)²、k = (m/n)·ln2、p_theory = (1-e^{-kn/m})^k  → 理论 vs 实测 FP
  B) 业务 A/B（真实数据）：已作答集合过滤候选池，精确 set vs Bloom（**负向验证**），
     断言两者结果完全一致（Bloom 不得误杀），统计跳过精确查询的比例
  C) 论文未处理的：删除/过期（普通 Bloom 做不到 → 计数 Bloom / 分片 + 重建）、
     FP 随插入量增长曲线、重建成本
  D) 规模-代价对比：与 Python set 的内存/延迟对比，给出"何时值得上 Bloom"的拐点

用法（backend 目录下，**不依赖 Neo4j 与 embedding**）：
    python eval_bloom_filter.py
"""
import argparse
import hashlib
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from app.core.sql_database import sql_db

LN2 = 0.6931471805599453


class BloomFilter:
    """标准布隆过滤器（numpy 位数组 + blake2b 双哈希派生 k 个位置）

    性质（必须记住）：只会假阳性、不会假阴性；不支持删除。
    正确用法（本项目采用）：**判否 → 可信地跳过；判是 → 回查精确集合确认**。
    """

    def __init__(self, n: int, p: float = 0.01):
        self.n = max(1, int(n))
        self.p = float(p)
        self.m = max(64, int(-self.n * np.log(self.p) / (LN2 ** 2)))
        self.k = max(1, int(round((self.m / self.n) * LN2)))
        self.bits = np.zeros(self.m, dtype=np.uint8)
        self._inserted = 0

    def _positions(self, item):
        h = hashlib.blake2b(str(item).encode("utf-8"), digest_size=16).digest()
        h1 = int.from_bytes(h[:8], "little")
        h2 = int.from_bytes(h[8:], "little") | 1
        for i in range(self.k):
            yield (h1 + i * h2) % self.m

    def add(self, item):
        for pos in self._positions(item):
            self.bits[pos] = 1
        self._inserted += 1

    def add_many(self, items):
        for it in items:
            self.add(it)

    def contains(self, item) -> bool:
        return all(self.bits[pos] for pos in self._positions(item))

    @property
    def memory_kb(self) -> float:
        return self.bits.nbytes / 1024.0

    def theory_fp(self, inserted: int = None) -> float:
        """理论误判率（按实际插入量代入 n）"""
        n = self._inserted if inserted is None else inserted
        return (1.0 - np.exp(-self.k * n / self.m)) ** self.k


class CountingBloomFilter:
    """计数布隆过滤器（4bit 饱和计数）：支持删除，代价是内存 ×4 左右

    论文完全没提"学生删作答记录 / 题目停用"后过滤器如何失效的问题，这里给出可删除方案。
    """

    def __init__(self, n: int, p: float = 0.01):
        self.m = max(64, int(-max(1, n) * np.log(p) / (LN2 ** 2)))
        self.k = max(1, int(round((self.m / max(1, n)) * LN2)))
        self.counters = np.zeros(self.m, dtype=np.uint8)     # 0-255 饱和计数（简单可靠）
        self._inserted = 0

    def _positions(self, item):
        h = hashlib.blake2b(str(item).encode("utf-8"), digest_size=16).digest()
        h1 = int.from_bytes(h[:8], "little")
        h2 = int.from_bytes(h[8:], "little") | 1
        for i in range(self.k):
            yield (h1 + i * h2) % self.m

    def add(self, item):
        for pos in self._positions(item):
            if self.counters[pos] < 255:
                self.counters[pos] += 1
        self._inserted += 1

    def remove(self, item) -> bool:
        """删除（计数 -1）；未插入过的元素调用会破坏计数，故调用前须确认存在"""
        positions = list(self._positions(item))
        if not all(self.counters[p] > 0 for p in positions):
            return False
        for pos in positions:
            self.counters[pos] -= 1
        self._inserted -= 1
        return True

    def contains(self, item) -> bool:
        return all(self.counters[pos] > 0 for pos in self._positions(item))

    @property
    def memory_kb(self) -> float:
        return self.counters.nbytes / 1024.0


# ---------- A) 公式复现：理论 vs 实测误判率 ----------

def experiment_formula(sizes=(1_000, 10_000, 100_000, 1_000_000),
                       targets=(0.01, 0.05, 0.10), probes: int = 10_000) -> list:
    rows = []
    for n in sizes:
        for p in targets:
            bf = BloomFilter(n, p)
            inserted = [f"item-{i}" for i in range(n)]
            t0 = time.perf_counter()
            bf.add_many(inserted)
            build_ms = (time.perf_counter() - t0) * 1000
            probes_items = [f"probe-{i}" for i in range(probes)]
            t0 = time.perf_counter()
            fp = sum(1 for x in probes_items if bf.contains(x))
            query_ms = (time.perf_counter() - t0) * 1000
            emp = fp / probes
            th = float(bf.theory_fp())
            # 实测假阳性的抽样误差：二项分布 95% 置信区间半宽 ≈ 1.96·sqrt(p(1-p)/N)
            ci = 1.96 * ((th * (1 - th) / probes) ** 0.5) if probes else 0.0
            rows.append({
                "n": n, "p_target": p, "m_bits": bf.m, "k": bf.k,
                "memory_kb": round(bf.memory_kb, 1),
                "memory_kb_theoretical": round(bf.m / 8 / 1024.0, 2),
                "fp_theory": round(th, 6), "fp_empirical": round(emp, 6),
                "fp_ci95_half_width": round(ci, 6),
                "within_ci": bool(abs(emp - th) <= ci),
                "rel_error": round(abs(emp - th) / th, 4) if th else None,
                "build_ms": round(build_ms, 1),
                "query_us_per_item": round(query_ms * 1000 / probes, 3),
                "probes": probes,
            })
    return rows


# ---------- B) 业务 A/B：真实作答集合上的去重（负向验证） ----------

def _load_real_answered(course_id: int) -> dict:
    """从 t_answer_record 取「每个学生已作答过的题目 id 集合」（真实数据）"""
    rows = sql_db._query(
        "SELECT user_id, question_id FROM t_answer_record WHERE course_id = ?",
        (course_id,),
    )
    by_user = {}
    for r in rows:
        by_user.setdefault(r["user_id"], set()).add(r["question_id"])
    return by_user


def experiment_dedup(course_id: int) -> dict:
    """精确 set vs Bloom（负向验证）→ 断言结果一致，统计省下的精确查询次数"""
    answered_by_user = _load_real_answered(course_id)
    _, questions = sql_db.list_questions(course_id, page=1, page_size=100000,
                                        auto_grade_only=False)
    pool = [q["question_id"] for q in questions]
    details, total_pool, total_skip = [], 0, 0

    for uid, answered in sorted(answered_by_user.items()):
        exact_keep = [qid for qid in pool if qid not in answered]
        bf = BloomFilter(max(1, len(answered)), 0.01)
        bf.add_many(answered)
        bloom_keep, verifications = [], 0
        for qid in pool:
            if not bf.contains(qid):        # 判否 → 必然没做过 → 直接保留（不查精确集）
                bloom_keep.append(qid)
            else:                            # 判是 → 可能假阳性 → 回查精确集确认
                verifications += 1
                if qid not in answered:
                    bloom_keep.append(qid)
        identical = set(bloom_keep) == set(exact_keep)
        skip = len(pool) - verifications
        total_pool += len(pool)
        total_skip += skip
        details.append({
            "user_id": uid, "answered": len(answered), "pool": len(pool),
            "kept": len(exact_keep), "bloom_filter_kb": round(bf.memory_kb, 3),
            "verifications": verifications, "skipped_exact_lookups": skip,
            "result_identical": identical,
            "fp_theory": round(float(bf.theory_fp()), 5),
        })

    return {
        "course_id": course_id, "students": len(details),
        "pool_size": len(pool),
        "all_results_identical": all(d["result_identical"] for d in details) if details else False,
        "skip_rate": round(total_skip / total_pool, 4) if total_pool else 0.0,
        "details": details,
    }


# ---------- C) 论文未处理的：删除 / 分片 ----------

def experiment_delete_and_shard(n: int = 100_000, p: float = 0.01, probes: int = 10_000) -> dict:
    """演示：普通 Bloom 无法删除（残留假阳性）；计数 Bloom 可删；分片控制误判面"""
    items = [f"q-{i}" for i in range(n)]
    removed = items[: n // 10]                       # 删掉 10%（模拟学生删除作答/题目停用）
    remaining = set(items[n // 10:])

    plain = BloomFilter(n, p)
    plain.add_many(items)                            # 只增不减

    counting = CountingBloomFilter(n, p)
    for it in items:
        counting.add(it)
    removed_ok = sum(1 for it in removed if counting.remove(it))

    def fp_rate(filter_obj, check_items):
        """在给定探针集合上统计假阳性率（探针均不在 remaining 中）"""
        bad = total = 0
        for x in check_items:
            if x in remaining:
                continue
            total += 1
            if filter_obj.contains(x):
                bad += 1
        return round(bad / total, 6) if total else 0.0

    shards = [BloomFilter(max(1, n // 8), p) for _ in range(8)]
    for i, it in enumerate(items):
        if it in remaining:
            shards[i % 8].add(it)
    shard_probes = [f"probe-{i}" for i in range(probes)]

    return {
        "n": n, "p_target": p, "removed": len(removed),
        "plain_bloom_cannot_delete": True,
        "plain_bloom_fp_on_removed_items": fp_rate(plain, removed),
        "counting_bloom_removed_ok": removed_ok,
        "counting_bloom_fp_on_removed_items": fp_rate(counting, removed),
        "counting_bloom_memory_kb": round(counting.memory_kb, 1),
        "plain_memory_kb": round(plain.memory_kb, 1),
        "shards": len(shards),
        "shard_total_memory_kb": round(sum(s.memory_kb for s in shards), 1),
        "shard_fp": round(sum(fp_rate(s, shard_probes) for s in shards) / len(shards), 6),
        "rebuild_note": "重建需 O(n) 次插入；构建耗时见 formula 实验的 build_ms",
    }


# ---------- D) 规模-代价对比：Bloom vs Python set ----------

def experiment_scale_cost(sizes=(10_000, 100_000, 1_000_000), p: float = 0.01,
                          probes: int = 5_000) -> list:
    rows = []
    for n in sizes:
        items = list(range(n))
        bf = BloomFilter(n, p)
        t0 = time.perf_counter()
        bf.add_many(items)
        bf_build_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        exact = set(items)
        set_build_ms = (time.perf_counter() - t0) * 1000

        probe_items = list(range(n, n + probes))
        t0 = time.perf_counter()
        for x in probe_items:
            bf.contains(x)
        bf_q_us = (time.perf_counter() - t0) * 1000 * 1000 / probes

        t0 = time.perf_counter()
        for x in probe_items:
            x in exact
        set_q_us = (time.perf_counter() - t0) * 1000 * 1000 / probes

        set_bytes = sys.getsizeof(exact) + sum(sys.getsizeof(x) for x in exact)
        bloom_bits_kb = bf.m / 8 / 1024.0                 # 理论位宽（m/8）
        rows.append({
            "n": n,
            "bloom_memory_kb": round(bf.memory_kb, 1),          # numpy uint8 实现实测占用
            "bloom_memory_kb_theoretical": round(bloom_bits_kb, 2),
            "set_memory_kb": round(set_bytes / 1024.0, 1),
            "memory_ratio_set_over_bloom": round((set_bytes / 1024.0) / bloom_bits_kb, 2),
            "bloom_build_ms": round(bf_build_ms, 1),
            "set_build_ms": round(set_build_ms, 1),
            "bloom_query_us": round(bf_q_us, 3),
            "set_query_us": round(set_q_us, 3),
            "query_slowdown_bloom_over_set": round(bf_q_us / set_q_us, 1) if set_q_us else None,
            "bloom_theory_fp": round(float(bf.theory_fp()), 6),
        })
    return rows


def main():
    ap = argparse.ArgumentParser(description="E3：布隆过滤器复现与超越（论文 3.3 节）")
    ap.add_argument("--course-id", type=int, default=65)
    ap.add_argument("--probes", type=int, default=10_000)
    ap.add_argument("--out", default=os.path.join("eval_data", "eval_report_bloom_filter.json"))
    args = ap.parse_args()

    sql_db.init_tables()
    print("A) 公式复现（理论 vs 实测误判率）")
    formula = experiment_formula(probes=args.probes)
    for r in formula:
        print(f"  n={r['n']:<8} p={r['p_target']:<5} m={r['m_bits']:<9} k={r['k']:<3} "
              f"mem {r['memory_kb_theoretical']:>8}KB(理论位宽)  "
              f"FP 理论 {r['fp_theory']:<10} 实测 {r['fp_empirical']:<10} "
              f"CI95±{r['fp_ci95_half_width']} 落在区间={r['within_ci']}")

    print("\nB) 业务 A/B（真实作答集合，负向验证）")
    dedup = experiment_dedup(args.course_id)
    print(f"  课程 {dedup['course_id']}：{dedup['students']} 名学生，候选池 {dedup['pool_size']} 题，"
          f"跳过精确查询比例 {dedup['skip_rate']}，结果与精确方案一致：{dedup['all_results_identical']}")
    for d in dedup["details"]:
        print(f"    学生 {d['user_id']}: 已做 {d['answered']}、保留 {d['kept']}、"
              f"回查 {d['verifications']}、跳过 {d['skipped_exact_lookups']}、一致={d['result_identical']}")

    print("\nC) 删除 / 分片（论文未处理）")
    dele = experiment_delete_and_shard()
    print(f"  普通 Bloom 无法删除 → 已删元素的假阳性残留 = {dele['plain_bloom_fp_on_removed_items']}")
    print(f"  计数 Bloom 删除成功 {dele['counting_bloom_removed_ok']}/{dele['removed']}，"
          f"已删元素假阳性 = {dele['counting_bloom_fp_on_removed_items']}，"
          f"内存 {dele['counting_bloom_memory_kb']}KB（普通 {dele['plain_memory_kb']}KB）")
    print(f"  8 分片：总内存 {dele['shard_total_memory_kb']}KB，分片平均误判 {dele['shard_fp']}")

    print("\nD) 规模-代价（Bloom vs Python set）")
    scale = experiment_scale_cost()
    for r in scale:
        print(f"  n={r['n']:<9} Bloom {r['bloom_memory_kb_theoretical']:>9}KB vs set {r['set_memory_kb']:>10}KB "
              f"(set/Bloom={r['memory_ratio_set_over_bloom']}×)  查询 Bloom {r['bloom_query_us']}us "
              f"vs set {r['set_query_us']}us（Bloom 慢 {r['query_slowdown_bloom_over_set']}×）")

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"formula": formula, "dedup": dedup, "delete_shard": dele, "scale_cost": scale,
                   "command": " ".join(sys.argv)}, f, ensure_ascii=False, indent=2)
    print(f"\n报告已写入：{args.out}")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

