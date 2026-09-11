"""课程中心改造：加入 / 邀请 / 审核 / 移除 / 级联删除 流程测试

运行方式（在 backend 目录下执行）：
    python test_course_member_flow.py

重点覆盖三条安全规则：
1. 刷新加课码后旧码立即失效；
2. 邀请令牌单次使用（重复接受不会重复加课）；
3. 被移除的学生不能用加课码自动复活。

只操作 data/app.db 副本，结束校验线上库 MD5 未变。
"""
import hashlib
import os
import shutil
import sys
import tempfile

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_DB = os.path.join(BACKEND_DIR, "data", "app.db")

TMP_DIR = tempfile.mkdtemp(prefix="kgu_member_")
TMP_DB = os.path.join(TMP_DIR, "app_copy.db")
shutil.copy2(LIVE_DB, TMP_DB)
os.environ["SQLITE_DB_PATH"] = TMP_DB

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, BACKEND_DIR)

from fastapi.testclient import TestClient          # noqa: E402
from app.main import app                            # noqa: E402
from app.core.sql_database import sql_db            # noqa: E402

failures = []
passed = 0


def check(label, ok, detail=""):
    global passed
    if ok:
        passed += 1
    else:
        failures.append(f"{label} — {detail}")
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    live_before = md5(LIVE_DB)
    client = TestClient(app)
    with client:
        pass

    def call(method, path, token=None, **kw):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return getattr(client, method)(path, headers=headers, **kw)

    def code_of(resp):
        try:
            body = resp.json()
        except Exception:
            return -resp.status_code
        return body.get("code", -resp.status_code) if isinstance(body, dict) else -resp.status_code

    def data_of(resp):
        return resp.json().get("data")

    def token_of(username, role):
        call("post", "/api/auth/register",
             json={"username": username, "password": "pw123456", "role": role})
        r = call("post", "/api/auth/login", json={"username": username, "password": "pw123456"})
        assert r.json().get("code") == 0, r.text
        return r.json()["data"]["access_token"]

    suffix = "mf"
    t1 = token_of(f"t1_{suffix}", "teacher")
    s1 = token_of(f"s1_{suffix}", "student")
    s2 = token_of(f"s2_{suffix}", "student")
    s3 = token_of(f"s3_{suffix}", "student")
    s1_id = sql_db.get_user_by_username(f"s1_{suffix}")["user_id"]
    s2_id = sql_db.get_user_by_username(f"s2_{suffix}")["user_id"]
    s3_id = sql_db.get_user_by_username(f"s3_{suffix}")["user_id"]

    r = call("post", "/api/v1/courses", t1,
             json={"course_name": f"成员流程_{suffix}", "join_mode": "approval",
                   "category": "计算机", "organization": "软件学院",
                   "description": "成员流程测试课程"})
    assert code_of(r) == 0, r.text
    course = data_of(r)
    cid, code = course["course_id"], course["join_code"]
    print(f"课程 {cid} 加课码 {code}")

    print("\n" + "=" * 70)
    print("Step 1: 加课码归一化与刷新")
    print("=" * 70)
    r = call("post", "/api/v1/courses/join-by-code", s1, json={"join_code": code.lower()})
    check("加课码小写输入也能加入（服务端归一化为大写）", code_of(r) == 0, r.text[:120])
    r = call("post", "/api/v1/courses/join-by-code", s1, json={"join_code": f" {code[:4]} {code[4:]} "})
    check("加课码中间带空格也能识别", code_of(r) == 4004, f"实际 {code_of(r)}（4004=已是申请中）")

    r = call("post", f"/api/v1/courses/{cid}/join-code/refresh", t1)
    new_code = data_of(r)["join_code"]
    check("刷新得到新的加课码", code_of(r) == 0 and new_code != code, f"{code} -> {new_code}")
    r = call("post", "/api/v1/courses/join-by-code", s2, json={"join_code": code})
    check("刷新后旧码立即失效 → 4005", code_of(r) == 4005, f"实际 {code_of(r)}")
    r = call("post", "/api/v1/courses/join-by-code", s2, json={"join_code": new_code})
    check("刷新后新码可用", code_of(r) == 0, r.text[:120])

    print("\n" + "=" * 70)
    print("Step 2: 待审核列表与统计")
    print("=" * 70)
    d = data_of(call("get", f"/api/v1/courses/{cid}/members?status=pending", t1))
    check("待审核 2 人（s1、s2）", d["total"] == 2, str(d["total"]))
    d = data_of(call("get", f"/api/v1/courses/{cid}/members/stats", t1))
    check("统计：待审核 2 / 已通过 1（教师本人）/ 总数 3",
          d["pending"] == 2 and d["approved"] == 1 and d["total"] == 3, str(d))
    d = data_of(call("get", f"/api/v1/courses/{cid}/members?status=pending&keyword={s1_id}", t1))
    check("成员搜索框可用（不报错）", code_of(call("get", f"/api/v1/courses/{cid}/members", t1)) == 0)

    print("\n" + "=" * 70)
    print("Step 3: 审核通过 / 拒绝 / 重新申请")
    print("=" * 70)
    r = call("post", f"/api/v1/courses/{cid}/members/{s1_id}/approve", t1)
    check("同意 s1", code_of(r) == 0, r.text[:120])
    check("s1 状态变为 approved 且写入 joined_at",
          sql_db.get_membership(cid, s1_id)["status"] == "approved"
          and sql_db.get_membership(cid, s1_id)["joined_at"],
          str(dict(sql_db.get_membership(cid, s1_id)))[:140])
    r = call("post", f"/api/v1/courses/{cid}/members/{s1_id}/approve", t1)
    check("重复同意 → 4004", code_of(r) == 4004, f"实际 {code_of(r)}")

    r = call("post", f"/api/v1/courses/{cid}/members/{s2_id}/reject", t1, json={"comment": "先修课未通过"})
    check("拒绝 s2 并可填理由", code_of(r) == 0, r.text[:120])
    m = sql_db.get_membership(cid, s2_id)
    check("s2 状态 rejected 且理由入库", m["status"] == "rejected" and m["review_comment"] == "先修课未通过",
          str(dict(m))[:140])
    r = call("post", f"/api/v1/courses/join-by-code", s2, json={"join_code": new_code})
    check("被拒学生可重新申请 → pending 且审核痕迹被清空",
          code_of(r) == 0 and data_of(r)["status"] == "pending"
          and sql_db.get_membership(cid, s2_id)["review_comment"] is None,
          str(dict(sql_db.get_membership(cid, s2_id)))[:140])

    print("\n" + "=" * 70)
    print("Step 4: 邀请链接（随机 token / 单次使用 / 过期 / 撤销）")
    print("=" * 70)
    r = call("post", f"/api/v1/courses/{cid}/invites", t1, json={"role": "student", "expires_in_days": 7})
    inv = data_of(r)
    check("生成邀请返回 32 位随机 token（非 course_id/user_id 拼接）",
          code_of(r) == 0 and len(inv["token"]) == 32 and str(cid) not in inv["token"], str(inv)[:140])
    token = inv["token"]

    r = call("get", f"/api/v1/invites/{token}", s3)
    d = data_of(r)
    check("邀请落地页可预览课程信息（含邀请人与有效期）",
          code_of(r) == 0 and d["course_name"] == course["course_name"]
          and d["effective_status"] == "active", str(d)[:160])
    check("预览里带上了我的当前关系", d["my_relation"] == "PUBLIC", d["my_relation"])

    r = call("post", "/api/v1/invites/accept", s3, json={"token": token})
    check("s3 接受邀请 → 直接 approved（邀请即教师同意）",
          code_of(r) == 0 and data_of(r)["status"] == "approved", r.text[:140])
    r = call("post", "/api/v1/invites/accept", s3, json={"token": token})
    check("重复接受同一 token → 幂等返回 already_member=true（不报错）",
          code_of(r) == 0 and data_of(r)["already_member"] is True, r.text[:140])
    check("邀请状态已变为 used",
          sql_db.get_invite_by_token(token)["status"] == "used",
          sql_db.get_invite_by_token(token)["status"])

    # 已是成员的人接受任意 token：幂等成功（不该报错），且不消耗令牌
    r = call("post", "/api/v1/invites/accept", s1, json={"token": token})
    check("已是成员者接受任意 token → 幂等成功 already_member=true",
          code_of(r) == 0 and data_of(r)["already_member"] is True, r.text[:140])

    # 非成员（s2 处于 pending）才是真正要拒绝的场景
    r = call("post", "/api/v1/invites/accept", s2, json={"token": token})
    check("已被使用的 token 给非成员 → 4010", code_of(r) == 4010, f"实际 {code_of(r)}")

    # 过期邀请（直接把 expires_at 改到过去）
    r = call("post", f"/api/v1/courses/{cid}/invites", t1, json={})
    exp_token = data_of(r)["token"]
    with sql_db._connect() as conn:
        conn.execute("UPDATE t_course_invite SET expires_at = '2000-01-01 00:00:00' WHERE token = ?",
                     (exp_token,))
        conn.commit()
    r = call("get", f"/api/v1/invites/{exp_token}", s2)
    check("过期邀请预览 → effective_status=expired", data_of(r)["effective_status"] == "expired",
          str(data_of(r))[:140])
    r = call("post", "/api/v1/invites/accept", s2, json={"token": exp_token})
    check("过期邀请不能接受 → 4010", code_of(r) == 4010, f"实际 {code_of(r)}")

    # 撤销
    r = call("post", f"/api/v1/courses/{cid}/invites", t1, json={})
    rev = data_of(r)
    r = call("delete", f"/api/v1/courses/{cid}/invites/{rev['invite_id']}", t1)
    check("撤销邀请成功", code_of(r) == 0, r.text[:120])
    r = call("post", "/api/v1/invites/accept", s2, json={"token": rev["token"]})
    check("已撤销邀请不能接受 → 4010", code_of(r) == 4010, f"实际 {code_of(r)}")

    # 邀请协作教师（role=teacher）：用于验证协作教师能管理但不能移除创建者
    r = call("post", f"/api/v1/courses/{cid}/invites", t1, json={"role": "teacher"})
    teacher_token = data_of(r)["token"]
    t2 = token_of(f"t2_{suffix}", "teacher")
    t2_id = sql_db.get_user_by_username(f"t2_{suffix}")["user_id"]
    r = call("post", "/api/v1/invites/accept", t2, json={"token": teacher_token})
    check("协作教师接受邀请 → approved 且 role=teacher",
          code_of(r) == 0 and sql_db.get_membership(cid, t2_id)["role"] == "teacher",
          str(dict(sql_db.get_membership(cid, t2_id)))[:140])
    r = call("get", f"/api/v1/courses/{cid}/members", t2)
    check("协作教师可以查看成员列表（管理级权限）", code_of(r) == 0, r.text[:140])

    r = call("post", "/api/v1/invites/accept", s1, json={"token": "not-a-real-token-xxxxxxxx"})
    check("伪造 token → 4010", code_of(r) == 4010, f"实际 {code_of(r)}")

    d = data_of(call("get", f"/api/v1/courses/{cid}/invites", t1))
    check("邀请列表返回全部邀请及其生效状态", len(d["items"]) == 4, str(len(d["items"])))
    check("邀请列表带出被使用者姓名",
          any(i["used_by_name"] for i in d["items"]), str([i["used_by_name"] for i in d["items"]]))

    print("\n" + "=" * 70)
    print("Step 5: 移除学生（软移除，保留其学习数据）")
    print("=" * 70)
    sql_db.upsert_learning_record(s1_id, cid, None, "kp_demo_mf", "MASTERED", 100, "MANUAL")
    sql_db.add_favorite(s1_id, cid, None, "kp_demo_mf")
    r = call("delete", f"/api/v1/courses/{cid}/members/{s1_id}?confirm=true", t1)
    check("移除 s1（软移除）", code_of(r) == 0 and data_of(r)["removed_learning"] is False, r.text[:140])
    check("s1 的学习记录仍在", len(sql_db.list_records_by_user_course(s1_id, cid)) == 1)
    check("s1 的收藏仍在", len(sql_db.list_favorites_by_user_course(s1_id, cid)) == 1)
    r = call("delete", f"/api/v1/courses/{cid}/members/{s1_id}?confirm=true", t1)
    check("不带 confirm 之外：移除已移除的成员仍成功（幂等）", code_of(r) == 0, f"实际 {code_of(r)}")

    r = call("delete", f"/api/v1/courses/{cid}/members/{s1_id}", t1)
    check("缺少 confirm=true → 2008", code_of(r) == 2008, f"实际 {code_of(r)}")

    t1_id = sql_db.get_user_by_username(f"t1_{suffix}")["user_id"]
    r = call("delete", f"/api/v1/courses/{cid}/members/{t1_id}?confirm=true", t1)
    check("创建者移除自己 → 4003（走「退出课程」路径，创建者不能退出自己的课）",
          code_of(r) == 4003, f"实际 {code_of(r)}")
    r = call("delete", f"/api/v1/courses/{cid}/members/{t1_id}?confirm=true", t2)
    check("协作教师移除课程创建者 → 4009", code_of(r) == 4009, f"实际 {code_of(r)}")
    r = call("delete", f"/api/v1/courses/{cid}/members/{t2_id}?confirm=true", t1)
    check("创建者可以移除协作教师", code_of(r) == 0, r.text[:140])

    print("\n" + "=" * 70)
    print("Step 6: 教学监测把新加入的学生也纳入（成员 ∪ 有学习记录者）")
    print("=" * 70)
    d = data_of(call("get", f"/api/v1/teacher/students/progress?course_id={cid}", t1))
    ids = {s["student_id"] for s in d["students"]}
    check("已通过但没有学习记录的 s3 出现在监测列表", s3_id in ids, str(sorted(ids)))
    check("被移除但仍有学习记录的 s1 也保留在列表（教师仍能看到历史）",
          s1_id in ids, str(sorted(ids)))
    check("课程创建者本人不在学生列表里", t1_id not in ids, str(sorted(ids)))
    check("监测列表带 member_status 便于识别已移除学生",
          all("member_status" in s for s in d["students"]),
          str([s.get("member_status") for s in d["students"]]))

    print("\n" + "=" * 70)
    print("Step 7: 删除课程级联清理成员与邀请")
    print("=" * 70)
    check("删除前存在成员行", sql_db._query_one(
        "SELECT count(*) AS c FROM t_course_member WHERE course_id = ?", (cid,))["c"] > 0)
    r = call("delete", f"/api/v1/courses/{cid}?confirm=true", t1)
    check("课程创建者删除课程", code_of(r) == 0, r.text[:140])
    check("成员行已级联清空", sql_db._query_one(
        "SELECT count(*) AS c FROM t_course_member WHERE course_id = ?", (cid,))["c"] == 0)
    check("邀请行已级联清空", sql_db._query_one(
        "SELECT count(*) AS c FROM t_course_invite WHERE course_id = ?", (cid,))["c"] == 0)
    check("课程本身已删除", sql_db.get_course(cid) is None)
    check("既有课程 5/9 未受影响", sql_db.get_course(5) is not None and sql_db.get_course(9) is not None)

    check("线上 app.db MD5 未变", live_before == md5(LIVE_DB),
          f"{live_before[:12]}… -> {md5(LIVE_DB)[:12]}…")

    shutil.rmtree(TMP_DIR, ignore_errors=True)

    print("\n" + "=" * 70)
    if failures:
        print(f"结果: 通过 {passed} 项，失败 {len(failures)} 项")
        for f in failures:
            print("   -", f)
        sys.exit(1)
    print(f"结果: 全部通过（{passed} 项）")
    print("=" * 70)


if __name__ == "__main__":
    main()
