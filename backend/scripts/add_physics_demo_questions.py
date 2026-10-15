# -*- coding: utf-8 -*-
"""为「物理」课程（course_id=67）的每篇文档补一批演示题目。

用途
----
学生端「做题练习」需要一个可演示的题库。物理课程下的 5 篇文档（105/106/107/159/160）
原本一道题都没有，这里给每篇各补 4 道**客观题**（单选/多选/判断），每篇都覆盖到，
这样在物理课程里随便切哪篇资料都做得起来题。

为什么是客观题
--------------
客观题提交后由系统即时判分并下发答案与解析，适合现场演示；填空/解答题要进教师
批改队列，演示时看不到判定结果，所以这批演示题刻意不含主观题。

为什么要关联知识点
------------------
每题都挂到该文档图谱里**真实存在**的 kp_id（见下方 QUESTIONS，kp_id 取自
Neo4j 中 course_id=67 该文档的实际节点）。关联后练习页会显示知识点标签、也能从
题目「查看知识点」跳回图谱；不关联则这些入口全是空的。

为什么走 QuestionService.create_question 而不是直接写 SQL
--------------------------------------------------------
一题涉及 t_question 与 t_question_kp（含 is_primary 投影），两者必须一致；
create_question 是唯一保证这一点的写入口，并且会校验题型/答案格式/知识点归属。

写入结果
--------
source=MANUAL、is_active=1（学生可见）、created_by=教师账号、difficulty 1~3。

重跑与回滚
----------
按 (document_id, 题干) 判重，已存在的跳过，因此可安全重跑；
`--remove` 按同一份清单把这些题删掉（连同 t_question_kp 关联）。

用法
----
    cd backend
    python scripts/add_physics_demo_questions.py            # 写入（幂等）
    python scripts/add_physics_demo_questions.py --dry-run  # 只看要写什么
    python scripts/add_physics_demo_questions.py --remove   # 删除本清单的题
"""

import os
import sys

# 允许 `python scripts/xxx.py` 直接运行：把 backend/ 放进 import path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:  # Windows 控制台默认 GBK，中文输出会乱码
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.core.sql_database import sql_db            # noqa: E402
from app.services.question_service import QuestionService  # noqa: E402

COURSE_ID = 67      # 「物理」课程
TEACHER_ID = 2      # 课程创建者（t_course.teacher_id），create_question 要求课程归属人


def single(stem, options, answer, analysis, difficulty=2, kp_spec=None):
    return {"q_type": "SINGLE", "stem": stem, "options": options, "answer": answer,
            "analysis": analysis, "difficulty": difficulty, "kp_spec": kp_spec}


def multi(stem, options, answers, analysis, difficulty=3, kp_spec=None):
    return {"q_type": "MULTI", "stem": stem, "options": options, "answer": answers,
            "analysis": analysis, "difficulty": difficulty, "kp_spec": kp_spec}


def judge(stem, answer, analysis, difficulty=2, kp_spec=None):
    return {"q_type": "JUDGE", "stem": stem, "answer": answer,
            "analysis": analysis, "difficulty": difficulty, "kp_spec": kp_spec}


def _opts(*pairs):
    return [{"key": k, "text": t} for k, t in pairs]


# 每篇文档 4 题：单选 2~3 / 多选 0~1 / 判断 1，知识点均为该文档图谱中的真实节点
QUESTIONS = {
    # 第1章 物理导论 测试题与答案（中文版）—— 内容偏「物理学是什么」
    105: [
        single(
            "下列关于物理模型与理论的说法，正确的是？",
            _opts(("A", "模型和理论是同一个概念，可以互相替换"),
                  ("B", "理论比模型更系统，能解释和预测多种现象"),
                  ("C", "模型只用于教学，科研中不使用模型"),
                  ("D", "理论一旦提出就不会被实验否定")),
            "B",
            "模型是对某个系统或过程的简化表示；理论是更广泛、更系统的解释框架，"
            "包含基本原理和定律，能解释和预测多种现象。理论可被新实验否定。",
            difficulty=2,
            kp_spec=("kp_67_618db18b", "理论"),
        ),
        single(
            "下列情形中，用经典物理学的规律就能准确描述的是？",
            _opts(("A", "接近光速运动的电子"),
                  ("B", "宏观、低速运动的天体"),
                  ("C", "原子核内质子与中子之间的结合"),
                  ("D", "强引力场中光线的弯曲")),
            "B",
            "经典物理学在宏观、低速条件下能准确描述现象（经典力学、经典电磁学）；"
            "高速与微观情形需用相对论、量子力学或相对论量子力学。",
            difficulty=2,
            kp_spec=("kp_67_2baaa257", "经典物理学"),
        ),
        judge(
            "精密度高一定意味着准确度高。",
            "false",
            "精密度只反映多次测量结果彼此的一致程度，与真值无关。仪器存在系统偏差时，"
            "测量可以非常精密却依然不准确。",
            difficulty=3,
            kp_spec=("kp_67_869adc78", "精密度"),
        ),
        single(
            "某测量值为 20.0 cm，其不确定度为 0.2 cm，则百分不确定度约为？",
            _opts(("A", "0.1%"), ("B", "1%"), ("C", "2%"), ("D", "10%")),
            "B",
            "百分不确定度 = 不确定度 ÷ 测量值 × 100% = 0.2 / 20.0 × 100% = 1%。",
            difficulty=3,
            kp_spec=("kp_67_2a812267", "百分不确定度"),
        ),
    ],
    # 第1章 物理导论 测试题与答案（中文版，另一份上传）—— 侧重概念与单位
    106: [
        single(
            "物理模型的主要作用是？",
            _opts(("A", "完全复制真实系统，做到与原型一致"),
                  ("B", "通过合理简化解释现象并做出可检验的预测"),
                  ("C", "取代实验测量，直接给出结论"),
                  ("D", "只用于把计算结果写成公式")),
            "B",
            "模型是对真实系统的简化表示，目的是解释现象、做出预测；简化是它的特征而非缺陷。",
            difficulty=1,
            kp_spec=("kp_67_1b6d3b69", "模型"),
        ),
        single(
            "研究接近光速运动的微观粒子时，必须使用下列哪套理论？",
            _opts(("A", "经典力学"), ("B", "热力学"),
                  ("C", "相对论量子力学"), ("D", "几何光学")),
            "C",
            "同时涉及高速与微观两种条件时，经典物理学失效，必须使用相对论量子力学。",
            difficulty=2,
            kp_spec=("kp_67_0b7c8223", "相对论量子力学"),
        ),
        multi(
            "下列属于国际单位制（SI）基本单位的有？",
            _opts(("A", "米（m）"), ("B", "千克（kg）"),
                  ("C", "秒（s）"), ("D", "摄氏度（℃）")),
            ["A", "B", "C"],
            "米、千克、秒都是 SI 基本单位；摄氏度是导出单位，热力学温度的基本单位是开尔文（K）。",
            difficulty=3,
            kp_spec=("kp_67_3aa4d540", "公制单位"),
        ),
        judge(
            "准确度描述测量值与真值的接近程度，精密度描述多次测量结果彼此的一致程度。",
            "true",
            "这正是准确度与精密度的标准区分：一个对着真值，一个对着自身重复性。",
            difficulty=2,
            kp_spec=("kp_67_0d1aeaf5", "准确度"),
        ),
    ],
    # 第2章 运动学
    107: [
        single(
            "下列物理量中属于矢量的是？",
            _opts(("A", "路程"), ("B", "时间"), ("C", "位移"), ("D", "速率")),
            "C",
            "矢量既有大小又有方向。位移是矢量；路程、时间、速率都只有大小，是标量。",
            difficulty=1,
            kp_spec=("kp_67_6880917d", "矢量"),
        ),
        single(
            "平均速度的定义是？",
            _opts(("A", "总路程除以经过时间"),
                  ("B", "位移除以经过时间"),
                  ("C", "初速度与末速度的算术平均值"),
                  ("D", "各瞬时速度的平均值")),
            "B",
            "平均速度 v̄ = Δx/Δt，是位移与时间的比值（矢量）；总路程除以经过时间得到的是平均速率。",
            difficulty=2,
            kp_spec=("kp_67_73bdeec2", "平均速度"),
        ),
        multi(
            "下列属于匀加速（恒定加速度）直线运动基本运动学方程的有？",
            _opts(("A", "v = v₀ + at"),
                  ("B", "x = x₀ + v₀t + ½at²"),
                  ("C", "v² = v₀² + 2a(x − x₀)"),
                  ("D", "F = ma")),
            ["A", "B", "C"],
            "前三式是匀加速直线运动的运动学方程；F = ma 是牛顿第二定律，属于动力学，不属于运动学方程。",
            difficulty=3,
            kp_spec=("kp_67_a709cda7", "匀加速运动方程"),
        ),
        judge(
            "自由落体运动指忽略空气阻力和摩擦、仅由引力作用产生的运动。",
            "true",
            "自由落体是只受重力（忽略空气阻力）的运动，其加速度为重力加速度 g，方向向下。",
            difficulty=2,
            kp_spec=("kp_67_5793a102", "自由落体"),
        ),
    ],
    # 第4章 动力学：力与牛顿运动定律
    159: [
        single(
            "牛顿第一定律的内容是？",
            _opts(("A", "物体不受净外力时保持静止或匀速直线运动状态"),
                  ("B", "力是维持物体运动的原因"),
                  ("C", "物体的加速度与质量成正比"),
                  ("D", "作用力与反作用力大小相等")),
            "A",
            "牛顿第一定律（惯性定律）：除非受到净外力，静止物体保持静止、运动物体保持恒定速度。"
            "它同时说明力是改变运动状态的原因，而不是维持运动的原因。",
            difficulty=2,
            kp_spec=("kp_67_ddf33874", "牛顿第一定律"),
        ),
        single(
            "力的 SI 单位「牛顿」指的是？",
            _opts(("A", "使 1 kg 的物体产生 1 m/s² 加速度的力"),
                  ("B", "使 1 kg 的物体获得 1 m/s 速度的力"),
                  ("C", "1 kg 物体所受的重力"),
                  ("D", "使 1 g 的物体产生 1 m/s² 加速度的力")),
            "A",
            "1 N = 1 kg·m/s²，即使 1 kg 的系统产生 1 m/s² 加速度所需的力。"
            "1 kg 物体所受重力约为 9.8 N，不是 1 N。",
            difficulty=2,
            kp_spec=("kp_67_642852b2", "牛顿"),
        ),
        multi(
            "下列属于自然界四种基本力的有？",
            _opts(("A", "引力"), ("B", "电磁力"),
                  ("C", "强核力"), ("D", "摩擦力")),
            ["A", "B", "C"],
            "四种基本力是引力、电磁力、弱核力和强核力；摩擦力是宏观上由电磁相互作用"
            "派生出的接触力，不是基本力。",
            difficulty=3,
            kp_spec=("kp_67_f66c4941", "四种基本力"),
        ),
        judge(
            "作用力与反作用力大小相等、方向相反，且分别作用在两个不同的物体上。",
            "true",
            "牛顿第三定律：每当一个物体对另一个物体施加力，它同时也受到大小相等、方向相反的力；"
            "两个力分别作用在施力物体和受力物体上，因此不能相互抵消。",
            difficulty=2,
            kp_spec=("kp_67_954702b1", "牛顿第三定律"),
        ),
    ],
    # 第1章 物理导论 测试题 演示版（从文档导入演示所用的那篇）
    160: [
        single(
            "测量值与真值的接近程度称为？",
            _opts(("A", "精密度"), ("B", "准确度"),
                  ("C", "不确定度"), ("D", "有效数字")),
            "B",
            "准确度衡量测量值与真值的接近程度；精密度衡量多次测量彼此的一致程度。",
            difficulty=1,
            kp_spec=("kp_67_6fafb3be", "准确度"),
        ),
        single(
            "量纲分析在物理问题中的作用是？",
            _opts(("A", "直接给出精确的数值结果"),
                  ("B", "检验公式是否正确、推导未知关系的形式"),
                  ("C", "替代实验测量"),
                  ("D", "只用于单位换算")),
            "B",
            "量纲分析可检验等式两边量纲是否一致，从而判断公式有无问题，并能帮助确定"
            "物理量之间的依赖关系形式；它不给出精确数值。",
            difficulty=2,
            kp_spec=("kp_67_f772601f", "量纲分析"),
        ),
        judge(
            "多次测量结果彼此接近，说明这次测量的精密度高。",
            "true",
            "精密度就是测量结果的一致性或重复性；彼此接近即分散小，精密度高，"
            "但这并不保证准确度高。",
            difficulty=2,
            kp_spec=("kp_67_078a12ac", "精密度"),
        ),
        single(
            "在物理估算中做数量级近似的主要意义是？",
            _opts(("A", "得到尽可能精确的计算结果"),
                  ("B", "快速判断结果是否合理、检查计算有无出错"),
                  ("C", "取代量纲分析"),
                  ("D", "提高仪器的测量精度")),
            "B",
            "数量级近似用合理假设快速给出量级上的估计，用于判断结果合理性、检验单位与"
            "计算是否出错，是发现错误的重要手段。",
            difficulty=3,
            kp_spec=("kp_67_64f4ba72", "数量级近似"),
        ),
    ],
}


def _existing_by_stem(doc_id):
    """该文档已有题目的 {题干: question_id}（只取本篇，不含课程通用题）"""
    _total, rows = sql_db.list_questions(
        COURSE_ID, document_id=doc_id, page=1, page_size=500, include_course_level=False,
    )
    return {r["stem"]: r["question_id"] for r in rows}


def run(dry_run=False, remove=False):
    n_add = n_skip = n_fail = n_removed = 0
    for doc_id, specs in sorted(QUESTIONS.items()):
        existing = _existing_by_stem(doc_id)
        print(f"\n=== 文档 {doc_id}（{len(specs)} 题）已有 {len(existing)} 题 ===")
        for spec in specs:
            kp_id, kp_name = spec.get("kp_spec") or (None, None)
            payload = {k: v for k, v in spec.items() if k != "kp_spec"}
            payload["document_id"] = doc_id
            payload["kp_id"] = kp_id

            if remove:
                qid = existing.get(payload["stem"])
                if not qid:
                    print(f"  [跳过] 未找到，无需删除：{payload['stem'][:20]}…")
                    continue
                if dry_run:
                    print(f"  [预演] 将删除 #{qid}：{payload['stem'][:20]}…")
                    continue
                res = QuestionService.delete_question(TEACHER_ID, qid)
                ok = res.get("ok")
                n_removed += 1 if ok else 0
                print(f"  [{'删除' if ok else '失败'}] #{qid} {payload['stem'][:20]}…"
                      f"{'' if ok else ' → ' + str(res.get('message'))}")
                continue

            if payload["stem"] in existing:
                n_skip += 1
                print(f"  [跳过] 已存在：{payload['stem'][:22]}…")
                continue
            if dry_run:
                print(f"  [预演] 将新增 {payload['q_type']:6s} kp={kp_name}：{payload['stem'][:22]}…")
                n_add += 1
                continue

            res = QuestionService.create_question(TEACHER_ID, COURSE_ID, payload)
            if res.get("ok"):
                n_add += 1
                print(f"  [新增] #{res['data']['question_id']} {payload['q_type']:6s} "
                      f"kp={kp_name}：{payload['stem'][:22]}…")
            else:
                n_fail += 1
                print(f"  [失败] code={res.get('code')} {res.get('message')}："
                      f"{payload['stem'][:22]}…")

    print()
    if remove:
        print(f"汇总：删除 {n_removed} 题")
    elif dry_run:
        print(f"汇总（预演，未写库）：将新增 {n_add} 题，已存在跳过 {n_skip} 题")
    else:
        print(f"汇总：新增 {n_add} 题，已存在跳过 {n_skip} 题，失败 {n_fail} 题")
    return n_fail


if __name__ == "__main__":
    args = set(sys.argv[1:])
    sql_db.init_tables()
    failures = run(dry_run="--dry-run" in args, remove="--remove" in args)
    sys.exit(1 if failures else 0)
