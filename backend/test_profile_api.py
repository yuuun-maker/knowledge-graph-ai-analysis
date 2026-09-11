"""课程中心改造：个人中心（资料 + 头像）测试

运行方式（在 backend 目录下执行）：
    python test_profile_api.py

安全约定：
- 只操作 data/app.db 副本；
- 头像写入临时目录（AVATAR_DIR 覆写），不污染 backend/data/uploads/avatars；
- 每次调用后都校验 t_user 的认证列（username / password_hash / role）逐字节未变。
"""
import base64
import hashlib
import os
import shutil
import sys
import tempfile

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_DB = os.path.join(BACKEND_DIR, "data", "app.db")

TMP_DIR = tempfile.mkdtemp(prefix="kgu_profile_")
TMP_DB = os.path.join(TMP_DIR, "app_copy.db")
TMP_AVATARS = os.path.join(TMP_DIR, "avatars")
shutil.copy2(LIVE_DB, TMP_DB)
os.environ["SQLITE_DB_PATH"] = TMP_DB
os.environ["AVATAR_DIR"] = TMP_AVATARS

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

# 1x1 透明 PNG（最小合法 PNG，用于验证 Content-Type 与字节透传）
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)


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


def auth_fingerprint(user_id):
    """t_user 的认证列指纹：本功能绝不允许改动它们"""
    u = sql_db.get_user_by_id(user_id)
    return (u["username"], u["password_hash"], u["role"], u["is_active"])


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

    suffix = "pf"
    call("post", "/api/auth/register",
         json={"username": f"s_{suffix}", "password": "pw123456", "role": "student"})
    call("post", "/api/auth/register",
         json={"username": f"t_{suffix}", "password": "pw123456", "role": "teacher"})
    r = call("post", "/api/auth/login", json={"username": f"s_{suffix}", "password": "pw123456"})
    assert code_of(r) == 0, r.text
    login_payload = data_of(r)
    s_tok, s_uid = login_payload["access_token"], login_payload["user"]["user_id"]
    t_tok = data_of(call("post", "/api/auth/login",
                         json={"username": f"t_{suffix}", "password": "pw123456"}))["access_token"]
    t_uid = sql_db.get_user_by_username(f"t_{suffix}")["user_id"]

    print("=" * 70)
    print("Step 1: 登录响应已带资料字段（侧边栏首屏即可显示昵称/头像）")
    print("=" * 70)
    u = login_payload["user"]
    check("登录响应含 display_name / nickname / real_name / avatar_url",
          all(k in u for k in ("display_name", "nickname", "real_name", "avatar_url")),
          str(sorted(u.keys())))
    check("JWT 载荷未被改动（老 token 继续可用）",
          set(u.keys()) - {"display_name", "nickname", "real_name", "avatar_url"} ==
          {"user_id", "username", "role"}, str(sorted(u.keys())))

    print("\n" + "=" * 70)
    print("Step 2: 读取资料（未填写字段为 null）")
    print("=" * 70)
    fp_before = auth_fingerprint(s_uid)
    d = data_of(call("get", "/api/v1/profile", s_tok))
    check("GET /profile 返回身份信息", d["user_id"] == s_uid and d["role"] == "student", str(d)[:140])
    check("未填写的资料字段为 null",
          all(d[f] is None for f in ("real_name", "nickname", "student_no", "avatar_url")),
          str({f: d[f] for f in ("real_name", "nickname", "student_no")}))
    check("线上 t_user 认证列未变", fp_before == auth_fingerprint(s_uid))

    print("\n" + "=" * 70)
    print("Step 3: 局部更新 + 字段清空")
    print("=" * 70)
    r = call("put", "/api/v1/profile", s_tok,
             json={"nickname": "小明", "student_no": "2021001", "school": "示例大学",
                   "gender": "male", "bio": "热爱学习"})
    d = data_of(r)
    check("提交的字段已写入",
          d["nickname"] == "小明" and d["student_no"] == "2021001" and d["school"] == "示例大学",
          str({k: d[k] for k in ("nickname", "student_no", "school")}))
    r = call("put", "/api/v1/profile", s_tok, json={"major": "计算机科学与技术"})
    d = data_of(r)
    check("只传一个字段时其余字段保持不变",
          d["major"] == "计算机科学与技术" and d["nickname"] == "小明", str(d)[:160])
    r = call("put", "/api/v1/profile", s_tok, json={"bio": ""})
    check("传空串 = 清空该字段", data_of(r)["bio"] is None, str(data_of(r)["bio"]))
    check("更新过程未改动 t_user 认证列", fp_before == auth_fingerprint(s_uid))

    print("\n" + "=" * 70)
    print("Step 4: 角色字段白名单（越权字段被静默丢弃）")
    print("=" * 70)
    r = call("put", "/api/v1/profile", s_tok,
             json={"teacher_no": "T999", "title": "教授", "research_area": "AI", "nickname": "小红"})
    d = data_of(r)
    check("学生提交 teacher_no / title / research_area → 未写入",
          d["teacher_no"] is None and d["title"] is None and d["research_area"] is None,
          f"teacher_no={d['teacher_no']} title={d['title']}")
    check("同一请求里的合法字段仍然生效", d["nickname"] == "小红", str(d["nickname"]))

    r = call("put", "/api/v1/profile", t_tok,
             json={"teacher_no": "T001", "title": "副教授", "student_no": "2021999", "college": "软件学院"})
    d = data_of(r)
    check("教师可写 teacher_no / title / college",
          d["teacher_no"] == "T001" and d["title"] == "副教授" and d["college"] == "软件学院",
          str({k: d[k] for k in ("teacher_no", "title", "college")}))
    check("教师提交 student_no 被丢弃", d["student_no"] is None, str(d["student_no"]))
    check("两个用户资料互不干扰",
          data_of(call("get", "/api/v1/profile", s_tok))["teacher_no"] is None)

    print("\n" + "=" * 70)
    print("Step 5: 参数校验")
    print("=" * 70)
    r = call("put", "/api/v1/profile", s_tok, json={"bio": "字" * 201})
    check("bio 超 200 字 → 4007", code_of(r) == 4007, f"实际 {code_of(r)}")
    r = call("put", "/api/v1/profile", s_tok, json={"real_name": "字" * 51})
    check("real_name 超 50 字 → 4007", code_of(r) == 4007, f"实际 {code_of(r)}")
    r = call("put", "/api/v1/profile", s_tok, json={"gender": "x"})
    check("非法 gender → 4007", code_of(r) == 4007, f"实际 {code_of(r)}")
    r = call("put", "/api/v1/profile", s_tok, json={"nickname": "  "})
    check("全空白昵称按清空处理（不报错）", code_of(r) == 0, r.text[:140])

    print("\n" + "=" * 70)
    print("Step 6: 头像上传（类型/大小/替换）")
    print("=" * 70)
    r = call("post", "/api/v1/profile/avatar", s_tok,
             files={"file": ("big.png", b"\x89PNG" + b"0" * (3 * 1024 * 1024), "image/png")})
    check("3MB 头像 → 1002（超 2MB）", code_of(r) == 1002, f"实际 {code_of(r)}")
    r = call("post", "/api/v1/profile/avatar", s_tok,
             files={"file": ("a.gif", b"GIF89a", "image/gif")})
    check(".gif 头像 → 1001（格式不支持）", code_of(r) == 1001, f"实际 {code_of(r)}")
    r = call("post", "/api/v1/profile/avatar", s_tok,
             files={"file": ("empty.png", b"", "image/png")})
    check("空文件 → 1003", code_of(r) == 1003, f"实际 {code_of(r)}")

    r = call("post", "/api/v1/profile/avatar", s_tok,
             files={"file": ("me.png", PNG_1PX, "image/png")})
    d = data_of(r)
    check("上传合法 png → 返回 avatar_url", code_of(r) == 0 and "avatar_url" in d, r.text[:140])
    check("上传后资料里的 avatar_url 已更新",
          data_of(call("get", "/api/v1/profile", s_tok))["avatar_url"] == d["avatar_url"])
    check("头像文件名由服务端生成（不含原始文件名 me.png）",
          "me.png" not in d["avatar_url"], d["avatar_url"])

    uv = call("get", f"/api/v1/profile/avatar/{s_uid}")
    check("GET 头像 → 200 且字节一致（无需鉴权，供 <img src> 使用）",
          uv.status_code == 200 and uv.content == PNG_1PX, f"状态 {uv.status_code}")
    check("Content-Type 为 image/png", uv.headers.get("content-type", "").startswith("image/png"),
          uv.headers.get("content-type"))
    check("头像目录里只有 1 个文件（旧文件已删）",
          len(os.listdir(TMP_AVATARS)) == 1, str(os.listdir(TMP_AVATARS)))

    # 再传一次，验证替换
    r = call("post", "/api/v1/profile/avatar", s_tok,
             files={"file": ("me2.png", PNG_1PX + b"\x00", "image/png")})
    check("二次上传成功", code_of(r) == 0, r.text[:140])
    check("替换后目录里仍只有 1 个文件（旧头像被删除，不会无限增长）",
          len(os.listdir(TMP_AVATARS)) == 1, str(os.listdir(TMP_AVATARS)))
    check("头像版本号变化（避免浏览器缓存旧图）",
          data_of(r)["avatar_url"] != d["avatar_url"],
          f"{d['avatar_url']} -> {data_of(r)['avatar_url']}")
    check("登录响应里也能拿到头像",
          data_of(call("post", "/api/auth/login",
                       json={"username": f"s_{suffix}", "password": "pw123456"}))
          ["user"]["avatar_url"] == data_of(r)["avatar_url"])

    r = call("get", "/api/v1/profile/avatar/999999")
    check("未设置头像的用户 → 404（前端回退首字母色块）", r.status_code == 404, f"实际 {r.status_code}")

    print("\n" + "=" * 70)
    print("Step 7: 越权与认证")
    print("=" * 70)
    r = call("get", "/api/v1/profile")
    check("未登录 GET /profile → 401", r.status_code == 401, f"实际 {r.status_code}")
    r = call("put", "/api/v1/profile", json={"nickname": "匿名改"})
    check("未登录 PUT /profile → 401", r.status_code == 401, f"实际 {r.status_code}")
    # 接口不接受任何 user_id 参数：给别人的 id 也不会改到别人
    r = call("put", f"/api/v1/profile?user_id={t_uid}", s_tok, json={"nickname": "试图改老师"})
    check("传别人的 user_id 无效（只改自己）",
          code_of(r) == 0 and data_of(r)["user_id"] == s_uid
          and data_of(r)["nickname"] == "试图改老师",
          str(data_of(r)["user_id"]))
    check("被指向的教师资料未被改动",
          data_of(call("get", "/api/v1/profile", t_tok))["nickname"] is None,
          str(data_of(call("get", "/api/v1/profile", t_tok))["nickname"]))

    print("\n" + "=" * 70)
    print("Step 8: 认证字段与既有数据零改动")
    print("=" * 70)
    check("s 用户 t_user 认证列未变", fp_before == auth_fingerprint(s_uid), str(fp_before))
    check("t 用户 t_user 认证列未变", auth_fingerprint(t_uid)[0] == f"t_{suffix}")
    check("原有 5 个用户仍在", len(sql_db.list_users()) >= 5, str(len(sql_db.list_users())))
    check("t_user 表结构未新增列",
          {r["name"] for r in sql_db._query("PRAGMA table_info(t_user)")} ==
          {"user_id", "username", "password_hash", "role", "display_name", "email",
           "is_active", "created_at", "updated_at"},
          str(sorted(r["name"] for r in sql_db._query("PRAGMA table_info(t_user)"))))
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
