"""
E2｜论文表 3-1 复现与超越：kd_tree / ball_tree / HNSW 三方对比

论文原表只有「排序时间 + 平均准确率」（1000~9000 题，HNSW 准确率 0.84 却被选中），
本脚本复现该对比并补齐它缺的三项：**Recall@10（以暴力检索为 ground truth）、P95 延迟、
以及 HNSW 的 efSearch/M 参数曲线**，从而回答"0.84 的近似精度换来多少延迟收益、值不值"。

数据来源（零新依赖，不写库）：
- 真实向量：SQLite `t_kp_embedding`（bge-m3，1024 维，JSON 文本）
- 规模扩样：真实向量 + 高斯扰动（生成簇状分布，ANN 的适用前提），固定随机种子

用法（backend 目录下）：
    python eval_ann_compare.py                 # 默认 1k~9k，Q=50
    python eval_ann_compare.py --queries 100   # 调整查询数
    python eval_ann_compare.py --no-sweep      # 跳过参数扫描，只看三方对比
"""
import argparse
import json
import os
import sys
import time
from statistics import mean

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from app.core.sql_database import sql_db


def load_real_vectors() -> np.ndarray:
    """读取全部真实知识点向量（1024 维），返回 (n, d) float32 数组"""
    rows = sql_db._query("SELECT kp_id, embedding FROM t_kp_embedding")
    vecs = []
    for r in rows:
        try:
            vec = json.loads(r["embedding"]) if isinstance(r["embedding"], str) else r["embedding"]
        except (ValueError, TypeError):
            continue
        if isinstance(vec, list) and vec:
            vecs.append(vec)
    if not vecs:
        return np.zeros((0, 0), dtype=np.float32)
    arr = np.asarray(vecs, dtype=np.float32)
    # 统一 L2 归一化：此时「欧氏最近 = 余弦最大」，三种索引可在同一口径下比较
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


def expand_to(base: np.ndarray, size: int, rng: np.random.Generator, noise: float = 0.05) -> np.ndarray:
    """把真实向量扩样到 size 条：以真实向量为簇心 + 高斯扰动（模拟同主题的簇状分布）"""
    n, d = base.shape
    idx = rng.integers(0, n, size=size)
    out = base[idx] + rng.normal(0.0, noise, size=(size, d)).astype(np.float32)
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return out / norms


def make_queries(base: np.ndarray, count: int, rng: np.random.Generator,
                 noise: float = 0.05) -> np.ndarray:
    """生成**留出查询**：以真实向量为基准再加扰动，不与索引内任何点重合。

    为什么不用索引内点做查询：那样等于查自己（每个簇内邻居必然被找到），
    HNSW 在各种 efSearch 下都会接近 1.0 召回，无法暴露"精度-延迟"权衡。
    """
    n, d = base.shape
    idx = rng.integers(0, n, size=count)
    q = base[idx] + rng.normal(0.0, noise, size=(count, d)).astype(np.float32)
    norms = np.linalg.norm(q, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return q / norms


def brute_force_topk(data: np.ndarray, queries: np.ndarray, k: int) -> list:
    """暴力检索（ground truth）：归一化向量的内积 = 余弦"""
    sims = queries @ data.T
    return [set(np.argpartition(-row, k)[:k].tolist()) for row in sims]


def time_queries(fn, queries: np.ndarray, k: int) -> tuple:
    """执行查询并返回 (结果列表, 单次平均毫秒, P95 毫秒)"""
    lat = []
    results = []
    for q in queries:
        t0 = time.perf_counter()
        res = fn(q)
        lat.append((time.perf_counter() - t0) * 1000.0)
        results.append(set(res[:k]) if res is not None else set())
    lat.sort()
    p95 = lat[min(len(lat) - 1, int(round(0.95 * len(lat))) - 1)] if lat else 0.0
    return results, round(mean(lat), 4), round(p95, 4)


def recall_at_k(results: list, truth: list) -> float:
    """Recall@k = |结果 ∩ 真值| / |真值| 的平均"""
    if not results:
        return 0.0
    return round(sum(len(r & t) / max(1, len(t)) for r, t in zip(results, truth)) / len(results), 4)


def build_indexes(data: np.ndarray, k: int):
    """构建三方索引：KDTree / BallTree（sklearn）与 HNSW（hnswlib）"""
    from sklearn.neighbors import BallTree, KDTree
    import hnswlib

    idx = {}
    t0 = time.perf_counter()
    idx["kd_tree"] = KDTree(data, leaf_size=40)
    idx["kd_tree_build_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    t0 = time.perf_counter()
    idx["ball_tree"] = BallTree(data, leaf_size=40)
    idx["ball_tree_build_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    t0 = time.perf_counter()
    hnsw = hnswlib.Index(space="l2", dim=data.shape[1])
    hnsw.init_index(max_elements=data.shape[0], ef_construction=200, M=16)
    hnsw.add_items(data, np.arange(data.shape[0]))
    hnsw.set_ef(64)
    idx["hnsw"] = hnsw
    idx["hnsw_build_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return idx


def query_fn(idx: dict, name: str, k: int):
    """把三种索引统一成 fn(query_vector) -> 邻居下标列表"""
    if name in ("kd_tree", "ball_tree"):
        tree = idx[name]
        return lambda q: tree.query(q.reshape(1, -1), k=k)[1][0].tolist()
    hnsw = idx["hnsw"]
    return lambda q: hnsw.knn_query(q.reshape(1, -1), k=k)[0][0].tolist()


def compare_at_size(data: np.ndarray, queries: np.ndarray, k: int) -> dict:
    """在给定规模上跑三方对比（含暴力检索 ground truth）"""
    truth = brute_force_topk(data, queries, k)
    idx = build_indexes(data, k)
    row = {"size": int(data.shape[0]), "dim": int(data.shape[1]),
           "kd_tree_build_ms": idx["kd_tree_build_ms"],
           "ball_tree_build_ms": idx["ball_tree_build_ms"],
           "hnsw_build_ms": idx["hnsw_build_ms"]}
    for name in ("kd_tree", "ball_tree", "hnsw"):
        res, avg_ms, p95_ms = time_queries(query_fn(idx, name, k), queries, k)
        row[f"{name}_ms"] = avg_ms
        row[f"{name}_p95_ms"] = p95_ms
        row[f"{name}_recall@{k}"] = recall_at_k(res, truth)
    return row


def sweep_hnsw(data: np.ndarray, queries: np.ndarray, k: int) -> list:
    """HNSW 参数曲线：M × efSearch → 召回/延迟（论文完全没给这一层）"""
    import hnswlib

    truth = brute_force_topk(data, queries, k)
    rows = []
    for m in (8, 16, 32):
        index = hnswlib.Index(space="l2", dim=data.shape[1])
        index.init_index(max_elements=data.shape[0], ef_construction=200, M=m)
        index.add_items(data, np.arange(data.shape[0]))
        for ef in (16, 32, 64, 128, 256):
            index.set_ef(ef)
            def fn(q, _idx=index):
                return _idx.knn_query(q.reshape(1, -1), k=k)[0][0].tolist()
            res, avg_ms, p95_ms = time_queries(fn, queries, k)
            rows.append({"M": m, "efSearch": ef, "avg_ms": avg_ms, "p95_ms": p95_ms,
                         "recall": recall_at_k(res, truth)})
    return rows


def main():
    ap = argparse.ArgumentParser(description="E2：kd_tree / ball_tree / HNSW 对比（论文表 3-1 复现与超越）")
    ap.add_argument("--k", type=int, default=10, help="近邻数（默认 10）")
    ap.add_argument("--queries", type=int, default=50, help="查询条数（默认 50）")
    ap.add_argument("--sizes", default="1000,2000,3000,4000,5000,6000,7000,8000,9000")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--noise", type=float, default=0.05, help="扩样/查询扰动强度（默认 0.05）")
    ap.add_argument("--no-sweep", action="store_true", help="跳过 HNSW 参数扫描")
    ap.add_argument("--out", default=os.path.join("eval_data", "eval_report_ann_compare.json"))
    args = ap.parse_args()

    sql_db.init_tables()
    base = load_real_vectors()
    print("真实向量（t_kp_embedding）:", base.shape)
    if base.shape[0] < 3:
        print("✗ 库中没有足够的真实向量，无法对比")
        return False

    sizes = [int(x) for x in args.sizes.split(",") if x.strip()]
    rng = np.random.default_rng(args.seed)
    results = {"real": None, "scaled": [], "sweep": []}
    params = {"k": args.k, "queries": args.queries, "seed": args.seed, "sizes": sizes,
              "hnsw": {"M": 16, "ef_construction": 200, "ef": 64},
              "trees": {"leaf_size": 40, "metric": "euclidean(on L2-normalized vectors)"},
              "expand_noise": args.noise,
              "query_protocol": "held-out perturbed queries (not indexed points)"}

    # ① 真实向量上的对比（规模小但完全真实）
    q_real = make_queries(base, min(args.queries, base.shape[0]), rng, args.noise)
    results["real"] = compare_at_size(base, q_real, min(args.k, base.shape[0] - 1))
    r = results["real"]
    print(f"  真实 N={r['size']}  kd_tree {r['kd_tree_ms']}ms / ball_tree {r['ball_tree_ms']}ms / "
          f"hnsw {r['hnsw_ms']}ms  recall@{args.k}(hnsw)={r[f'hnsw_recall@{args.k}']}")

    # ② 扩样到论文表的规模点
    for size in sizes:
        data = base if size <= base.shape[0] else expand_to(base, size, rng, args.noise)
        q = make_queries(base, min(args.queries, data.shape[0]), rng, args.noise)
        row = compare_at_size(data, q, args.k)
        results["scaled"].append(row)
        print(f"  N={row['size']:<6} kd_tree {row['kd_tree_ms']:>9}ms recall {row[f'kd_tree_recall@{args.k}']}"
              f" | ball_tree {row['ball_tree_ms']:>9}ms recall {row[f'ball_tree_recall@{args.k}']}"
              f" | hnsw {row['hnsw_ms']:>8}ms recall {row[f'hnsw_recall@{args.k}']}")

    # ③ HNSW 参数曲线（固定中等规模，控制总耗时）
    if not args.no_sweep:
        size = min(max(sizes), 5000)
        data = expand_to(base, size, rng, args.noise)
        q = make_queries(base, min(args.queries, data.shape[0]), rng, args.noise)
        results["sweep"] = sweep_hnsw(data, q, args.k)
        print(f"\nHNSW 参数曲线（N={size}）：")
        for row in results["sweep"]:
            print(f"  M={row['M']:<3} efSearch={row['efSearch']:<4} avg {row['avg_ms']:>8}ms "
                  f"p95 {row['p95_ms']:>8}ms recall@{args.k}={row['recall']}")

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"params": params, "results": results, "command": " ".join(sys.argv)},
                  f, ensure_ascii=False, indent=2)
    print(f"\n报告已写入：{args.out}")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

