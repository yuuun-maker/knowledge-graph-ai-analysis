"""
E1｜论文 3.1 节复现：基于知识点向量的试题召回（0/1 表示 + 余弦 + 相关度阈值 λ）

论文做法：把试题的知识点集合表示为 0/1 向量，用余弦计算试题间相关度，
再以阈值 λ 截断得到召回候选集。

本脚本复现该流程，并对**标签密度**这一关键前提做敏感性分析（论文未讨论）：
  A) 真实单标签：库中每题恰好挂 1 个知识点 → 余弦只取 {0, 1}，λ 无区分度（预期退化）
  B) 仿真多标签：按论文设定每题 1~3 个知识点 → 余弦出现中间值，λ 曲线才有意义
  C) 语义向量变体（可选）：若该课程存在知识点向量，则用「知识点向量均值」当试题向量，
     对比「0/1 稀疏表示」与「稠密语义表示」的召回质量

指标：Recall@K（真值 = 共享至少 1 个知识点的题）、平均候选数、候选压缩率、λ 扫描表。

用法（backend 目录下，零新依赖、不写库）：
    python eval_paper_recall_knn.py --course-id 65 --k 10
"""
import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from app.core.sql_database import sql_db


def load_questions(course_id: int) -> tuple:
    """取该课程「已挂知识点」的题目，返回 (question_ids, kp_ids)"""
    _, rows = sql_db.list_questions(course_id, page=1, page_size=100000,
                                    auto_grade_only=False)
    qids, kps = [], []
    for r in rows:
        kp = (r.get("kp_id") or "").strip()
        if kp:
            qids.append(r["question_id"])
            kps.append(kp)
    return qids, kps


def build_binary_matrix(qids: list, label_lists: list) -> tuple:
    """把「每题的标签集合」编译成 0/1 矩阵（论文的知识点向量）"""
    vocab = sorted({kp for labels in label_lists for kp in labels})
    idx = {kp: i for i, kp in enumerate(vocab)}
    mat = np.zeros((len(qids), len(vocab)), dtype=np.float32)
    for i, labels in enumerate(label_lists):
        for kp in labels:
            mat[i, idx[kp]] = 1.0
    return mat, vocab


def cosine_matrix(mat: np.ndarray) -> np.ndarray:
    """0/1 向量余弦（稀疏表示下可能出现中间值，取决于每题标签数）"""
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = mat / norms
    return unit @ unit.T


def ground_truth(label_lists: list) -> list:
    """真值 = 与查询题共享至少 1 个知识点的其他题（论文语境下的「相关试题」）"""
    gt = []
    for i, labels in enumerate(label_lists):
        s = set(labels)
        gt.append({j for j, other in enumerate(label_lists)
                   if j != i and s & set(other)})
    return gt


def evaluate_lambda(sim: np.ndarray, gt: list, k: int,
                    lambdas=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 0.9, 1.0)) -> list:
    """按 λ 截断召回 → 统计候选规模、覆盖率与 Recall@K"""
    n = sim.shape[0]
    rows = []
    for lam in lambdas:
        recall_hits, recall_total = 0, 0
        cand_sizes, covered = 0, 0
        for i in range(n):
            order = np.argsort(-sim[i])
            picked = [j for j in order if j != i and sim[i][j] >= lam][:k]
            cand_sizes += len(picked)
            if picked:
                covered += 1
            if gt[i]:
                recall_hits += len(set(picked) & gt[i])
                recall_total += len(gt[i])
        rows.append({
            "lambda": round(lam, 2),
            "avg_candidates": round(cand_sizes / n, 3),
            "compression": round(1 - (cand_sizes / n) / max(1, n - 1), 4),
            "coverage": round(covered / n, 4),
            "recall@k": round(recall_hits / recall_total, 4) if recall_total else 0.0,
        })
    return rows


def simulate_multi_label(label_lists: list, rng: np.random.Generator,
                         extra_max: int = 2) -> list:
    """仿真论文设定：每题 1~3 个知识点（真标签 + 同课程随机附加标签）"""
    vocab = sorted({kp for labels in label_lists for kp in labels})
    out = []
    for labels in label_lists:
        extra = int(rng.integers(0, extra_max + 1))
        pool = [kp for kp in vocab if kp not in labels]
        chosen = list(rng.choice(pool, size=min(extra, len(pool)), replace=False))
        out.append(sorted(set(labels) | set(chosen)))
    return out


def load_kp_vectors(course_id: int) -> dict:
    """该课程的知识点向量（用于 C 变体：语义表示 vs 0/1 稀疏表示）"""
    rows = sql_db.get_embeddings_by_course(course_id)
    out = {}
    for r in rows:
        vec = r.get("embedding")
        if r.get("kp_id") and vec:
            out[r["kp_id"]] = np.asarray(vec, dtype=np.float32)
    return out


def question_vectors_from_kp(label_lists: list, kp_vectors: dict):
    """C 变体：试题向量 = 其知识点向量的均值（稠密语义表示）"""
    vecs = []
    for labels in label_lists:
        arr = [kp_vectors[kp] for kp in labels if kp in kp_vectors]
        if not arr:
            return None
        vecs.append(np.mean(np.stack(arr), axis=0))
    mat = np.stack(vecs)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


def _pairwise_stats(sim: np.ndarray) -> dict:
    """相似度取值分布：论文方法在稀疏标签下的关键诊断（是否退化为二值）"""
    iu = np.triu_indices(sim.shape[0], k=1)
    vals = sim[iu]
    distinct = sorted({round(float(v), 4) for v in vals})
    nonzero = float((vals > 0).mean()) if vals.size else 0.0
    return {
        "distinct_values": distinct[:10],
        "distinct_count": len(distinct),
        "nonzero_pair_ratio": round(nonzero, 4),
        "max": round(float(vals.max()), 4) if vals.size else 0.0,
        "mean": round(float(vals.mean()), 4) if vals.size else 0.0,
    }


def main():
    ap = argparse.ArgumentParser(description="E1：论文式试题召回（0/1 知识点向量 + 余弦 + λ）")
    ap.add_argument("--course-id", type=int, default=65)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default=os.path.join("eval_data", "eval_report_paper_recall.json"))
    args = ap.parse_args()

    sql_db.init_tables()
    qids, kps = load_questions(args.course_id)
    print(f"课程 {args.course_id}：已挂知识点的题 {len(qids)} 道，"
          f"涉及知识点 {len(set(kps))} 个")
    if len(qids) < 3:
        print("✗ 题量不足，无法评估")
        return False

    rng = np.random.default_rng(args.seed)
    report = {"course_id": args.course_id, "k": args.k, "seed": args.seed,
              "questions": len(qids), "distinct_kp": len(set(kps))}

    # ---------- A) 真实单标签（复现流程，预期退化） ----------
    labels_a = [[kp] for kp in kps]
    mat_a, vocab_a = build_binary_matrix(qids, labels_a)
    sim_a = cosine_matrix(mat_a)
    gt_a = ground_truth(labels_a)
    report["A_real_single_label"] = {
        "matrix_shape": list(mat_a.shape),
        "similarity": _pairwise_stats(sim_a),
        "avg_ground_truth": round(sum(len(g) for g in gt_a) / len(gt_a), 3),
        "sweep": evaluate_lambda(sim_a, gt_a, args.k),
    }

    # ---------- B) 仿真多标签（论文设定） ----------
    labels_b = simulate_multi_label(labels_a, rng)
    mat_b, vocab_b = build_binary_matrix(qids, labels_b)
    sim_b = cosine_matrix(mat_b)
    gt_b = ground_truth(labels_b)
    report["B_simulated_multi_label"] = {
        "matrix_shape": list(mat_b.shape),
        "avg_labels_per_question": round(sum(len(x) for x in labels_b) / len(labels_b), 3),
        "similarity": _pairwise_stats(sim_b),
        "avg_ground_truth": round(sum(len(g) for g in gt_b) / len(gt_b), 3),
        "sweep": evaluate_lambda(sim_b, gt_b, args.k),
    }

    # ---------- C) 语义向量变体（若该课程有知识点向量） ----------
    kp_vectors = load_kp_vectors(args.course_id)
    q_mat = question_vectors_from_kp(labels_a, kp_vectors) if kp_vectors else None
    if q_mat is not None:
        sim_c = q_mat @ q_mat.T
        report["C_semantic_variant"] = {
            "kp_vectors": len(kp_vectors),
            "similarity": _pairwise_stats(sim_c),
            "sweep": evaluate_lambda(sim_c, gt_a, args.k),
        }
    else:
        report["C_semantic_variant"] = {
            "available": False,
            "reason": f"该课程没有知识点向量（t_kp_embedding 命中 {len(kp_vectors)} 条）",
        }

    # ---------- 输出 ----------
    for key, title in (("A_real_single_label", "A) 真实单标签"),
                       ("B_simulated_multi_label", "B) 仿真多标签（论文设定）"),
                       ("C_semantic_variant", "C) 语义向量变体")):
        block = report[key]
        print(f"\n{title}")
        if block.get("available") is False:
            print("  不可用：", block.get("reason"))
            continue
        sim_stat = block["similarity"]
        print(f"  相似度取值种类 {sim_stat['distinct_count']}（{sim_stat['distinct_values']}）"
              f" | 非零题对比例 {sim_stat['nonzero_pair_ratio']} | 平均真值题数 {block['avg_ground_truth']}")
        for row in block["sweep"]:
            print(f"    λ={row['lambda']:<5} 候选均值 {row['avg_candidates']:<7} "
                  f"覆盖率 {row['coverage']:<7} 压缩率 {row['compression']:<7} Recall@{args.k}={row['recall@k']}")

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({**report, "command": " ".join(sys.argv)}, f, ensure_ascii=False, indent=2)
    print(f"\n报告已写入：{args.out}")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
