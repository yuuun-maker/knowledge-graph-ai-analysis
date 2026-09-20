# -*- coding: utf-8 -*-
"""合并本地库与 origin/main 库（2026-09-17 pull 时的一次性脚本）。

背景：pull 前本地 app.db 与 origin/main 的 app.db 各自演进，冲突点在 course_id=65
（本地=C++，远端=高数A）。两侧其余数据互补，故合并而非二选一。

策略：
  基库 = 本地库（数据更全：多 course 64、多 3 条学习记录）
  并入远端独有数据；远端课程与本地区块同号但内容不同时（course 65：本地 C++、
  远端高数A），自动改到最大课程号 +1 的空闲号，并同步 doc / member 的 course_id

已核对：course 64/65 在两侧库中均无 kp_embedding / learning_record / question /
favorite 引用，仅 t_document 与 t_course_member 有外键，故重编号影响面仅这两张表。
本脚本可重复执行（每次先还原为本地库再合并）。

用户与个人资料（2026-09-17 补）：
  原版只并入课程/文档/成员/学习记录，t_user 与 t_user_profile 整表跟随 LOCAL。
  首次执行后出现事故——头像指针与个人资料整体消失（avatar_url 变成 NULL），
  而头像图片其实还留在 data/uploads/avatars/ 里。两者按「本地优先、远端补缺」
  合并：本地已填字段绝不覆盖，只填补本地为空、远端有值的字段。
  另加两道保险：
    1) 覆盖前检查 TARGET 是否含有 LOCAL 没有的资料，有则中止（确认要覆盖加 --force）；
    2) 覆盖前先给 TARGET 留一份 .pre_merge_<时间戳>.bak 快照。
"""
import os
import shutil
import sqlite3
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL = os.path.join(HERE, "app.db.local_before_pull")
REMOTE = os.path.join(HERE, "app.db.remote_before_pull")
TARGET = os.path.normpath(os.path.join(HERE, "..", "..", "data", "app.db"))


def rows(conn, table):
    """按列名返回全表行，便于安全地改字段后回插"""
    cols = [r[1] for r in conn.execute("pragma table_info(%s)" % table)]
    return cols, [dict(zip(cols, r)) for r in conn.execute("select * from %s" % table)]


def check_would_lose_data():
    """覆盖是单向的 LOCAL -> TARGET：TARGET 在两次运行之间新增的资料
    （例如用户重新上传头像、补填了个人资料）在 LOCAL 和 REMOTE 里都不存在，
    一旦覆盖就无从恢复，因此先拦下来。
    返回「会被丢掉」的描述列表；无风险返回空列表。
    """
    if not os.path.exists(TARGET) or "--force" in sys.argv:
        return []
    try:
        cur = sqlite3.connect(TARGET)
        cur.row_factory = sqlite3.Row
        _, cur_profiles = rows(cur, "t_user_profile")
        loc = sqlite3.connect(LOCAL)
        loc.row_factory = sqlite3.Row
        _, loc_profiles = rows(loc, "t_user_profile")
    except sqlite3.OperationalError:
        return []                       # 老库没有 t_user_profile，无资料可丢

    loc_by_uid = {r["user_id"]: r for r in loc_profiles}
    lost = []
    for r in cur_profiles:
        lr = loc_by_uid.get(r["user_id"])
        for key, value in dict(r).items():
            if key == "user_id" or value in (None, ""):
                continue                # 只关心「当前库有值」的字段
            if lr is None or lr.get(key) in (None, ""):
                lost.append("user_id=%s 的 %s=%r" % (r["user_id"], key, value))
    cur.close()
    loc.close()
    return lost


def main():
    if not (os.path.exists(LOCAL) and os.path.exists(REMOTE)):
        sys.exit("缺少备份文件，终止")

    # --- 0. 覆盖前风险检查：TARGET 里 LOCAL 没有的资料会被永久丢掉 ---
    lost = check_would_lose_data()
    if lost:
        print("当前目标库里下列资料在 LOCAL 中不存在，覆盖后将永久丢失：")
        for item in lost:
            print("   ", item)
        sys.exit("已中止（覆盖前不会做任何改动）。确认要覆盖请加 --force，"
                 "届时仍会先自动备份当前目标库。")

    # 覆盖前先给「当前目标库」留快照：若 LOCAL 本身是旧的/不完整的，
    # 这一步是唯一的后悔药（历史事故正是 LOCAL 陈旧导致本地资料被静默覆盖）。
    if os.path.exists(TARGET):
        snapshot = "%s.pre_merge_%s.bak" % (TARGET, datetime.now().strftime("%Y%m%d_%H%M%S"))
        shutil.copyfile(TARGET, snapshot)
        print("当前目标库已备份 -> %s" % snapshot)

    shutil.copyfile(LOCAL, TARGET)
    conn = sqlite3.connect(TARGET)
    conn.row_factory = sqlite3.Row

    rem = sqlite3.connect(REMOTE)
    rem.row_factory = sqlite3.Row

    # --- 1. 取远端独有行（整行比对：course_id=65 两侧同号但内容不同，不能只比主键）---
    def local_set(table):
        cols, rs = rows(conn, table)
        return cols, {tuple(r[c] for c in cols) for r in rs}

    lcols_c, local_course_rows = local_set("t_course")
    lcols_d, local_doc_rows = local_set("t_document")
    lcols_m, local_mem_rows = local_set("t_course_member")
    lcols_l, local_lr_rows = local_set("t_learning_record")

    rcols, rcourse = rows(rem, "t_course")
    local_course_ids = {r[0] for r in conn.execute("select course_id from t_course")}
    add_courses = [r for r in rcourse if tuple(r[c] for c in rcols) not in local_course_rows]

    rcols_d, rdocs = rows(rem, "t_document")
    add_docs = [r for r in rdocs if tuple(r[c] for c in rcols_d) not in local_doc_rows]

    rcols_m, rmem = rows(rem, "t_course_member")
    add_mems = [r for r in rmem if tuple(r[c] for c in rcols_m) not in local_mem_rows]

    lcols_lr, rlr = rows(rem, "t_learning_record")
    add_lr = [r for r in rlr if tuple(r[c] for c in lcols_lr) not in local_lr_rows]

    print("待并入：课程 %d、文档 %d、成员 %d、学习记录 %d"
          % (len(add_courses), len(add_docs), len(add_mems), len(add_lr)))

    # --- 2. 重编号映射：远端课程若与本地区块同号但不同课，则改到空闲号 ---
    remap = {}
    next_free = max(local_course_ids) + 1
    for r in add_courses:
        if r["course_id"] in local_course_ids:
            remap[r["course_id"]] = next_free
            print("  课程 %s(%s) 与本地区块同号，重编号 -> %d"
                  % (r["course_id"], r["course_name"], next_free))
            next_free += 1

    # --- 3. 课程 ---
    for r in add_courses:
        r = dict(r)
        r["course_id"] = remap.get(r["course_id"], r["course_id"])
        conn.execute(
            "insert into t_course (%s) values (%s)" % (
                ",".join(rcols), ",".join("?" * len(rcols))),
            [r[c] for c in rcols])

    # --- 4. 文档：随课程重编号，并把 file_path 指向本机实际文件 ---
    for r in add_docs:
        r = dict(r)
        old = r["course_id"]
        r["course_id"] = remap.get(old, old)
        if old in remap:
            name = os.path.basename(str(r["file_path"]).replace("\\", "/"))
            actual = os.path.normpath(os.path.join(
                HERE, "..", "..", "data", "uploads", str(old), name))
            if os.path.exists(actual):
                r["file_path"] = actual
                print("  文档 %s 的 file_path 已指向本机文件：%s" % (r["doc_id"], actual))
            else:
                print("  [警告] 文档 %s 的本机文件不存在：%s" % (r["doc_id"], actual))
        conn.execute(
            "insert into t_document (%s) values (%s)" % (
                ",".join(rcols_d), ",".join("?" * len(rcols_d))),
            [r[c] for c in rcols_d])

    # --- 5. 成员：随课程重编号；同 (course_id,user_id) 已有本地行时跳过 ---
    for r in add_mems:
        r = dict(r)
        r["course_id"] = remap.get(r["course_id"], r["course_id"])
        dup = conn.execute(
            "select member_id from t_course_member where course_id=? and user_id=?",
            (r["course_id"], r["user_id"])).fetchone()
        if dup:
            print("  [跳过] 成员 %s (course %s/user %s) 已存在本地行 member_id=%s"
                  % (r["member_id"], r["course_id"], r["user_id"], dup[0]))
            continue
        conn.execute(
            "insert into t_course_member (%s) values (%s)" % (
                ",".join(rcols_m), ",".join("?" * len(rcols_m))),
            [r[c] for c in rcols_m])

    # --- 6. 学习记录 ---
    for r in add_lr:
        conn.execute("insert into t_learning_record (%s) values (%s)" % (
            ",".join(lcols_lr), ",".join("?" * len(lcols_lr))),
            [r[c] for c in lcols_lr])

    # --- 7. 用户与个人资料：本地优先，远端只补缺 ---
    # 这两张表不能像课程那样「整行二选一」：同一个 user_id 在两侧都可能填过资料，
    # 必须保住本地已填的值，只把「本地为空、远端有值」的字段补上。
    local_user_ids = {r[0] for r in conn.execute("select user_id from t_user")}
    lcols_p, local_profiles = rows(conn, "t_user_profile")
    local_profile_by_uid = {r["user_id"]: r for r in local_profiles}
    rcols_p, remote_profiles = rows(rem, "t_user_profile")
    remote_profile_by_uid = {r["user_id"]: r for r in remote_profiles}
    ucols, remote_users = rows(rem, "t_user")

    add_users = [r for r in remote_users if r["user_id"] not in local_user_ids]
    print("待并入：用户 %d、资料行 %d" % (len(add_users), len(remote_profiles)))

    for ru in add_users:
        conn.execute("insert into t_user (%s) values (%s)" % (
            ",".join(ucols), ",".join("?" * len(ucols))),
            [ru[c] for c in ucols])
        print("  新增用户 %s(%s)" % (ru["user_id"], ru["username"]))

    # 资料合并对「两侧都有该用户」同样生效，故遍历远端全量而非仅新增用户
    for uid, rp in remote_profile_by_uid.items():
        lp = local_profile_by_uid.get(uid)
        if lp is None:
            conn.execute("insert into t_user_profile (%s) values (%s)" % (
                ",".join(rcols_p), ",".join("?" * len(rcols_p))),
                [rp[c] for c in rcols_p])
            print("  新增资料 user_id=%s" % uid)
            continue
        fills = {c: rp[c] for c in rcols_p
                 if c != "user_id" and rp[c] not in (None, "") and lp.get(c) in (None, "")}
        if fills:
            conn.execute("update t_user_profile set %s where user_id=?" % (
                ",".join("%s=?" % c for c in fills)),
                list(fills.values()) + [uid])
            print("  补齐资料 user_id=%s 的字段：%s" % (uid, "、".join(fills)))

    # --- 8. 修正自增序列，避免后续新建记录撞号 ---
    for table, col in (("t_course", "course_id"), ("t_document", "doc_id"),
                       ("t_course_member", "member_id"),
                       ("t_learning_record", "record_id"), ("t_user", "user_id")):
        mx = conn.execute("select coalesce(max(%s),0) from %s" % (col, table)).fetchone()[0]
        has = conn.execute("select 1 from sqlite_sequence where name=?", (table,)).fetchone()
        if has:
            conn.execute("update sqlite_sequence set seq=? where name=?", (mx, table))
        else:
            conn.execute("insert into sqlite_sequence(name,seq) values(?,?)", (table, mx))

    conn.commit()

    # --- 9. 校验：计数 + 外键完整性 ---
    print("\n=== 合并后计数 ===")
    for t in ("t_course", "t_document", "t_course_member", "t_learning_record",
              "t_kp_embedding", "t_user", "t_question", "t_student_favorite"):
        print("  %-20s %d" % (t, conn.execute("select count(*) from %s" % t).fetchone()[0]))

    print("\n=== 外键检查（孤儿行应为 0）===")
    for t in ("t_document", "t_course_member", "t_learning_record", "t_kp_embedding",
              "t_question"):
        try:
            n = conn.execute(
                "select count(*) from %s x where x.course_id is not null and not exists "
                "(select 1 from t_course c where c.course_id=x.course_id)" % t).fetchone()[0]
            print("  %-20s 孤儿 %d" % (t, n))
        except sqlite3.OperationalError as e:
            print("  %-20s 跳过 (%s)" % (t, e))

    print("\n=== 课程 65/66 ===")
    for r in conn.execute("select course_id, course_name, teacher_id, join_code "
                          "from t_course where course_id in (64,65,66) order by course_id"):
        print("  ", tuple(r))

    # --- 10. 明示未覆盖范围：避免「以为全并了」而漏掉用户内容 ---
    print("\n=== 未并入的表（远端同名数据不会进入本地库，以本地为准）===")
    for t in ("t_question", "t_answer_record", "t_student_favorite", "t_kp_embedding"):
        if conn.execute("select 1 from sqlite_master where type='table' and name=?",
                        (t,)).fetchone():
            print("  %-20s 本地 %d 行" % (t, conn.execute("select count(*) from %s" % t).fetchone()[0]))

    conn.close()
    rem.close()
    print("\n合并完成 ->", TARGET)


if __name__ == "__main__":
    main()
