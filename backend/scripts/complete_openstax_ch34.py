"""
OpenStax 化学/物理 第3-4章 缺失题目答案补全
读取 _work_translate 下的中文题目和教材答案, 用LLM补全缺失题答案
输出到 _work_translate 下的 补全_*.json
"""
import json, re, os, time
import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = os.path.join(BASE, 'data', 'sample_docs', '_work_translate')

env = {}
with open(os.path.join(BASE, '.env'), encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
API_URL = env.get('LLM_API_BASE', 'https://api.deepseek.com/v1').rstrip('/') + '/chat/completions'
HEADERS = {'Authorization': f"Bearer {env['LLM_API_KEY']}", 'Content-Type': 'application/json'}
MODEL = env.get('LLM_MODEL', 'deepseek-chat')

CHEM_SYS = """你是一位大学化学课程的助教，负责为《Chemistry 2e》教材章末习题补全参考答案。
要求：
1. 用中文回答，简洁直接，风格与教材标准答案一致；有 (a)(b)(c) 分项的题按分项作答
2. 计算题必须给出数值结果和单位，必要时保留简要计算过程
3. 概念题给出准确简明的判断与理由
4. 只输出 JSON 对象，键为题号字符串，值为答案字符串，不要输出任何其他内容"""

PHYS_SYS = """你是一位大学物理课程的助教，负责为《College Physics 2e》教材章末习题补全参考答案。
要求：
1. 用中文回答，简洁直接，风格与教材标准答案一致；有 (a)(b)(c) 分项的题按分项作答
2. 计算题必须给出数值结果和单位，必要时保留简要计算过程
3. 概念题给出准确简明的判断与理由
4. 只输出 JSON 对象，键为题号字符串，值为答案字符串，不要输出任何其他内容"""

def llm_json(system, questions):
    items = '\n'.join(f'{k}. {v}' for k, v in questions.items())
    for attempt in range(3):
        try:
            resp = requests.post(API_URL, headers=HEADERS, json={
                'model': MODEL,
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': f'请为以下题目给出参考答案（JSON 格式）：\n\n{items}'}
                ],
                'temperature': 0.1, 'max_tokens': 8192
            }, timeout=300)
            resp.raise_for_status()
            content = resp.json()['choices'][0]['message']['content'].strip()
            content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content)
            return json.loads(content)
        except Exception as e:
            print(f'  [retry {attempt+1}] {e}', flush=True)
            time.sleep(5)
    return None

def parse_nums(text):
    items, cur, buf = {}, None, []
    for line in text.split('\n'):
        m = re.match(r'^(\d+)\.\s*(.*)$', line)
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

def batch(nums, need, system, tag):
    results = {}
    for i in range(0, len(nums), 10):
        bn = nums[i:i+10]
        data = llm_json(system, {n: need[n] for n in bn})
        if data is None:
            print(f'[{tag}] 批次 {bn[0]}-{bn[-1]} 失败', flush=True)
            continue
        missing = set(bn) - {int(k) for k in data}
        if missing:
            print(f'[{tag}] 批次 {bn[0]}-{bn[-1]} 题号不齐: {sorted(missing)}', flush=True)
        results.update(data)
        print(f'[{tag}] 批次 {bn[0]}-{bn[-1]} 完成', flush=True)
        time.sleep(1)
    return results

def run():
    # ===== 化学 Ch3/Ch4: 单一题号序列 =====
    for ch in ['3', '4']:
        with open(os.path.join(T, f'chem_ch{ch}_questions_cn.txt'), encoding='utf-8') as f:
            q = f.read()
        with open(os.path.join(T, f'chem_ch{ch}_answer_cn.txt'), encoding='utf-8') as f:
            a = f.read()
        items = parse_nums(q)
        an = {int(m.group(1)) for m in re.finditer(r'^(\d+)\.\s', a, re.M)}
        need = {n: items[n] for n in sorted(items) if n not in an}
        print(f'化学Ch{ch}: 需补全 {len(need)} 道', flush=True)
        results = batch(sorted(need), need, CHEM_SYS, f'chem{ch}')
        with open(os.path.join(T, f'chem_ch{ch}_补全.json'), 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=1)
        print(f'化学Ch{ch}: 补全 {len(results)}/{len(need)}', flush=True)

    # ===== 物理 Ch3/Ch4: 概念题+习题两套编号 =====
    for ch in ['3', '4']:
        with open(os.path.join(T, f'phys_ch{ch}_questions_cn.txt'), encoding='utf-8') as f:
            q = f.read()
        with open(os.path.join(T, f'phys_ch{ch}_answer_cn.txt'), encoding='utf-8') as f:
            a = f.read()
        # 分区: 概念题区(含 概念性问题/概念题 标记) 和 习题区
        cq_m = re.search(r'^[#\s]*(概念性问题|概念题|Conceptual)', q, re.M)
        pe_m = re.search(r'^[#\s]*(习题|Problems)', q, re.M)
        if cq_m and pe_m and pe_m.start() > cq_m.start():
            cq_text, pe_text = q[cq_m.start():pe_m.start()], q[pe_m.start():]
        else:
            cq_text, pe_text = q, ''
        cq_items = parse_nums(cq_text)
        pe_items = parse_nums(pe_text)
        an = {int(m.group(1)) for m in re.finditer(r'^(\d+)\.\s', a, re.M)}
        # 概念题: 全部补
        cq_need = {n: cq_items[n] for n in sorted(cq_items)}
        # 习题: 补教材答案缺失的
        pe_need = {n: pe_items[n] for n in sorted(pe_items) if n not in an}
        print(f'物理Ch{ch}: 概念题补 {len(cq_need)}, 习题补 {len(pe_need)}', flush=True)
        cq_r = batch(sorted(cq_need), cq_need, PHYS_SYS, f'phys{ch}cq')
        pe_r = batch(sorted(pe_need), pe_need, PHYS_SYS, f'phys{ch}pe')
        with open(os.path.join(T, f'phys_ch{ch}_概念题补全.json'), 'w', encoding='utf-8') as f:
            json.dump(cq_r, f, ensure_ascii=False, indent=1)
        with open(os.path.join(T, f'phys_ch{ch}_习题补全.json'), 'w', encoding='utf-8') as f:
            json.dump(pe_r, f, ensure_ascii=False, indent=1)
        print(f'物理Ch{ch}: 概念题 {len(cq_r)}/{len(cq_need)}, 习题 {len(pe_r)}/{len(pe_need)}', flush=True)
    print('ALL_DONE')

if __name__ == '__main__':
    run()
