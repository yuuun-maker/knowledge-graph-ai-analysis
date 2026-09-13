"""
OpenStax 化学/物理 第3-4章 最终文件组装
读取 _work_translate 的翻译与补全结果, 生成最终中文版文件到各 openstax_* 目录
"""
import json, re, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = os.path.join(BASE, 'data', 'sample_docs', '_work_translate')
CHEM = os.path.join(BASE, 'data', 'sample_docs', 'openstax_化学')
PHYS = os.path.join(BASE, 'data', 'sample_docs', 'openstax_物理')

def read(p):
    with open(p, encoding='utf-8') as f:
        return f.read()

def write(p, c):
    with open(p, 'w', encoding='utf-8') as f:
        f.write(c)

def norm_headers(c):
    """裸行结构标记加 ## """
    for kw in ['本章大纲', '引言', '关键术语', '术语表', '本章小结', '章节小结']:
        c = re.sub(rf'^(?!#)({kw})\s*$', r'## \1', c, flags=re.M)
    return c

def drop_dup_title(c):
    """删除第一行标题后的孤行(被拆行的标题)"""
    lines = c.split('\n')
    if not lines: return c
    # 第2行若是短行(拆行标题)且第3行为空, 删除
    if len(lines) > 2 and lines[1].strip() and lines[2].strip() == '' and len(lines[1].strip()) < 40 and not re.match(r'^(图|##|#|>|\d)', lines[1].strip()):
        lines.pop(1)
        if lines[1].strip() == '':
            lines.pop(1)
    return '\n'.join(lines)

def parse_nums(text):
    items, cur, buf = {}, None, []
    for line in text.split('\n'):
        # 题号行: 数字+点后必须是空白或行尾(避免 "30.8 m" 这类数值行被误判为题号)
        m = re.match(r'^(\d+)\.(?=\s|$)\s*(.*)$', line)
        if m:
            if cur is not None:
                items[cur] = '\n'.join(buf).strip()
            cur = int(m.group(1))
            buf = [m.group(2).strip()] if m.group(2).strip() else []
        elif cur is not None:
            buf.append(line.strip() if line.strip() else '')
    if cur is not None:
        items[cur] = '\n'.join(buf).strip()
    return items

def fmt_answers(items, total, extra=None):
    """按 1..total 顺序输出答案; items=教材答案(翻译), extra=补全json dict(str键)"""
    lines = []
    for n in range(1, total + 1):
        if n in items and items[n]:
            a = items[n]
        elif extra and str(n) in extra:
            a = extra[str(n)]
        else:
            a = '（暂无答案）'
        lines.append(f'{n}. {a}')
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'

# ================= 化学 =================
chem_meta = {
    '3': dict(en='Composition of Substances and Solutions', cn='物质组成与溶液',
              total=80, answer='chem_ch3_answer_cn.txt', extra='chem_ch3_补全.json',
              qsrc='chem_ch3_questions_cn.txt', bsrc='chem_ch3_body_cn.txt'),
    '4': dict(en='Stoichiometry of Chemical Reactions', cn='化学反应计量',
              total=95, answer='chem_ch4_answer_cn.txt', extra='chem_ch4_补全.json',
              qsrc='chem_ch4_questions_cn.txt', bsrc='chem_ch4_body_cn.txt'),
}
for ch, m in chem_meta.items():
    # 正文
    body = read(os.path.join(T, m['bsrc']))
    body = norm_headers(body)
    body = drop_dup_title(body)
    body = body.replace(f'# 第{ch}章：', f'# 第{ch}章：{m["cn"]}（{m["en"]}）', 1) if '（' not in body.split('\n')[0] else body
    # 保证第一行是最终标题
    body = re.sub(r'^#.*$', f'# 第{ch}章：{m["cn"]}（{m["en"]}）', body, count=1, flags=re.M)
    header = f'''# 第{ch}章：{m["cn"]}（{m["en"]}）

> 原文：Chemistry 2e (OpenStax, CC BY 4.0)，第{ch}章 {m["en"]}
> 本书免费获取地址：http://cnx.org/content/col26069/1.5
> 本译文为中文翻译版，章节结构与原文一致；原文中的页码页脚已省略。

'''
    body = re.sub(r'^#.*\n\n', '', body)  # 去掉翻译自带标题行
    write(os.path.join(CHEM, f'第{ch}章_{m["cn"]}_中文版.txt'), header + body)

    # 测试题
    q = read(os.path.join(T, m['qsrc']))
    q = re.sub(r'^\s*(Exercises|习题)\s*$', '', q, flags=re.M)  # 去掉分区标题行(化学单一序列)
    a = read(os.path.join(T, m['answer']))
    items = parse_nums(a)
    with open(os.path.join(T, m['extra']), encoding='utf-8') as f:
        extra = json.load(f)
    ans = fmt_answers(items, m['total'], extra)
    qhead = f'''# 第{ch}章 {m["cn"]}（{m["en"]}）—— 测试题与答案（中文版）

> 教材：Chemistry 2e (OpenStax, CC BY 4.0)
> 题目来源：本章章末 Exercises（教材自带，共 {m["total"]} 道）
> 答案来源：书末 Answer Key（教材原书仅选答部分题目，未提供答案的题目已附参考解答）
> 本文件为中文翻译版，题目与答案均已译成中文；化学式、数值与符号保留原文。

## 一、题目（按小节分类）

'''
    write(os.path.join(CHEM, f'第{ch}章_{m["cn"]}_测试题与答案_中文版.txt'),
          qhead + q.strip() + '\n\n## 二、参考答案\n\n' + ans)
    print(f'化学Ch{ch}: 已组装 正文+测试题')

# ================= 物理 =================
phys_meta = {
    '3': dict(en='Two-Dimensional Kinematics', cn='二维运动学',
              cq=21, pe=71, answer='phys_ch3_answer_cn.txt',
              cq_extra='phys_ch3_概念题补全.json', pe_extra='phys_ch3_习题补全.json',
              qsrc='phys_ch3_questions_cn.txt', bsrc='phys_ch3_body_cn.txt'),
    '4': dict(en='Dynamics: Force and Newton\'s Laws of Motion', cn='动力学_力与牛顿运动定律',
              cq=27, pe=55, answer='phys_ch4_answer_cn.txt',
              cq_extra='phys_ch4_概念题补全.json', pe_extra='phys_ch4_习题补全.json',
              qsrc='phys_ch4_questions_cn.txt', bsrc='phys_ch4_body_cn.txt'),
}
for ch, m in phys_meta.items():
    # 正文
    body = read(os.path.join(T, m['bsrc']))
    body = norm_headers(body)
    body = drop_dup_title(body)
    header = f'''# 第{ch}章：{m["cn"]}（{m["en"]}）

> 原文：College Physics 2e (OpenStax, CC BY 4.0)，第{ch}章 {m["en"]}
> 免费获取地址：https://openstax.org/details/books/college-physics-2e
> 本译文为中文翻译版，章节结构与原文一致；原文中的页码页脚已省略。
> 说明：原书公式以图片形式排版，文本提取后公式本体缺失；译文中以【公式 3.x】保留公式编号位置，公式内容请对照原书。个别按上下文可直接确定的公式以标准形式写出。

'''
    body = re.sub(r'^#.*\n\n', '', body)
    write(os.path.join(PHYS, f'第{ch}章_{m["cn"]}_中文版.txt'), header + body)

    # 测试题: 分区
    q = read(os.path.join(T, m['qsrc']))
    cq_m = re.search(r'^[#\s]*(概念性问题|概念题|Conceptual)[^\n]*\n', q, re.M)
    pe_m = re.search(r'^[#\s]*(习题|Problems)[^\n]*\n', q, re.M)
    if cq_m and pe_m and pe_m.start() > cq_m.start():
        cq_text = q[cq_m.end():pe_m.start()]
        pe_text = q[pe_m.end():]
    else:
        # 找不到分区标题则全归习题
        cq_text, pe_text = '', q
    # 概念题内的小节标题保留
    a = read(os.path.join(T, m['answer']))
    items = parse_nums(a)
    with open(os.path.join(T, m['cq_extra']), encoding='utf-8') as f:
        cq_extra = json.load(f)
    with open(os.path.join(T, m['pe_extra']), encoding='utf-8') as f:
        pe_extra = json.load(f)
    cq_ans = fmt_answers({}, m['cq'], cq_extra)
    pe_ans = fmt_answers(items, m['pe'], pe_extra)
    qhead = f'''# 第{ch}章 {m["cn"]}（{m["en"]}）—— 测试题与答案（中文版）

> 教材：College Physics 2e (OpenStax, CC BY 4.0)
> 题目来源：本章章末 Conceptual Questions + Problems & Exercises（教材自带，共 {m["cq"]} 道概念题 + {m["pe"]} 道习题）
> 本文件为中文翻译版，题目与答案均已译成中文；数值、单位与符号保留原文。
> 答案来源：书末 Answer Key（教材原书仅选答部分题目，未提供答案的题目已附参考解答）

## 一、题目（按题型分类）

### 概念题（Conceptual Questions）

{cq_text.strip()}

### 习题（Problems & Exercises）

{pe_text.strip()}

## 二、参考答案

### 概念题答案

{cq_ans}
### 习题答案

{pe_ans}
'''
    write(os.path.join(PHYS, f'第{ch}章_{m["cn"]}_测试题与答案_中文版.txt'), qhead)
    print(f'物理Ch{ch}: 已组装 正文+测试题')
print('ALL_DONE')
