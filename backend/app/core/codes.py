"""加课码 / 邀请令牌生成（课程中心改造）

放在 core/ 而非 services/：core/sql_database.py 的迁移回填需要生成加课码，
若放在 services/ 会造成 core -> services 的反向依赖。

安全约定（对应开发要求「加入码安全」「邀请机制」）：
- 加课码不重复、不使用连续数字、长度 6-8 位、字母+数字混排；
- 加课码与数据库主键无任何推导关系（随机生成，唯一索引兜底 + 冲突重试）；
- 邀请令牌为 URL 安全随机串，不暴露 course_id / user_id。
"""
import secrets

# 加课码字母表：剔除 0/O、1/I/L 等手抄易混字符，仅保留不易看错的字母与数字
JOIN_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
JOIN_CODE_LENGTH = 8


def gen_join_code(length: int = JOIN_CODE_LENGTH) -> str:
    """生成随机加课码（大写字母 + 数字，长度限制在 6-8 位）。

    唯一性由 t_course.join_code 的唯一索引兜底，调用方在插入冲突时重试。
    """
    length = min(max(int(length), 6), 8)
    return "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(length))


def normalize_join_code(raw: str) -> str:
    """归一化用户输入的加课码：去除所有空白并转大写。

    生成端字母表已剔除易混字符，故这里只需处理大小写与误输入的空格
    （例如教师从聊天软件复制时带上的空格）。
    """
    return "".join((raw or "").split()).upper()


def gen_invite_token(length: int = 32) -> str:
    """生成邀请令牌（URL 安全随机串，不可由 course_id / user_id 推导）"""
    return secrets.token_urlsafe(48)[:max(int(length), 16)]
