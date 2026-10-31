"""向量索引缓存并发回归测试（纯打桩，不读真实库）。

自动标注改为线程池执行后，写侧 invalidate() 会与问答侧 _load() 并发。
本测试用两个线程反复「检索 + 失效」，确认缓存遍历与写入不会互相破坏。

运行：cd backend && python test_vector_index_thread_safety.py
"""
import array
import sys
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.services import vector_index as vi

failures = []


def check(label, ok, detail=""):
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def main() -> int:
    original_loader = vi.sql_db.get_kp_embedding_blobs
    original_ttl = vi.CACHE_TTL
    blob = array.array("f", [0.1, 0.2, 0.3]).tobytes()

    vi.CACHE_TTL = 3600
    vi.sql_db.get_kp_embedding_blobs = lambda course_id, document_id: [
        {"kp_id": f"kp_{course_id}_{document_id}", "blob": blob}
    ]
    index = vi.VectorIndex()
    errors = []

    def reader():
        try:
            for _ in range(1500):
                index.kp_search(1, 1, [0.1, 0.2, 0.3], top_k=1)
                index.kp_search(2, 2, [0.1, 0.2, 0.3], top_k=1)
                index.stats()
        except Exception as e:  # noqa: BLE001 - 收集其他线程异常
            errors.append(("reader", type(e).__name__, str(e)))

    def invalidator():
        try:
            for _ in range(1500):
                index.invalidate(kind="kp", course_id=1)
                index.invalidate(kind="kp", course_id=2)
        except Exception as e:  # noqa: BLE001 - 收集其他线程异常
            errors.append(("invalidator", type(e).__name__, str(e)))

    threads = [threading.Thread(target=reader), threading.Thread(target=invalidator)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
    finally:
        vi.sql_db.get_kp_embedding_blobs = original_loader
        vi.CACHE_TTL = original_ttl

    check("并发检索与失效无异常", not errors, str(errors))
    check("线程全部结束", all(not t.is_alive() for t in threads))
    check("缓存命中/未命中统计可读",
          index.stats()["hits"] + index.stats()["misses"] > 0, str(index.stats()))

    print(f"通过 {3 - len(failures)}/3")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
