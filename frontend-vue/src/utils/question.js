/** 题库题型常量与答案展示（教师端 / 学生端共用） */

export const QUESTION_TYPES = [
  { value: 'SINGLE', label: '单选题' },
  { value: 'MULTI', label: '多选题' },
  { value: 'JUDGE', label: '判断题' },
  { value: 'FILL', label: '填空题' },
  { value: 'ESSAY', label: '解答题' },
]

export function questionTypeLabel(type) {
  return QUESTION_TYPES.find((x) => x.value === type)?.label || type || ''
}

/** 答案展示：单选→键；多选→"A、C"；判断→正确/错误；填空→各空参考答案；解答→文本 */
export function formatAnswer(answer) {
  if (answer === null || answer === undefined || answer === '') return '—'
  // 填空题作答/答案形如 {"1":"浮点数","2":"0.5"}
  if (typeof answer === 'object' && !Array.isArray(answer)) {
    const keys = Object.keys(answer).sort((a, b) => Number(a) - Number(b))
    const parts = keys.map((k) => `第${k}空：${String(answer[k] ?? '').trim() || '（未填）'}`)
    return parts.length ? parts.join('；') : '—'
  }
  if (Array.isArray(answer)) return answer.length ? answer.join('、') : '—'
  if (answer === true || String(answer) === 'true') return '正确'
  if (answer === false || String(answer) === 'false') return '错误'
  return String(answer)
}

/** 新建一道题的作答容器：多选=数组，填空=各空对象，其余=字符串 */
export function emptyAnswerFor(question) {
  if (!question) return ''
  if (question.q_type === 'MULTI') return []
  if (question.q_type === 'FILL') {
    const blanks = {}
    ;(question.options || []).forEach((b) => {
      blanks[b.key] = ''
    })
    return blanks
  }
  return ''
}
