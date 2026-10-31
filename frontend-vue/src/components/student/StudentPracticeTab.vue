<template>
  <div>
    <el-card v-if="!ctxKey" class="page-card">
      <el-empty description="请先选择课程和学习资料，开始做题练习" :image-size="90">
        <el-button type="primary" @click="emit('go-selector')">选择课程/文档</el-button>
      </el-empty>
    </el-card>

    <template v-else>
      <!-- 练习设置 + 我的练习统计 -->
      <el-card class="page-card">
        <div class="chart-title-line"><el-icon><Opportunity /></el-icon> 练习设置</div>
        <div class="table-toolbar">
          <el-radio-group v-model="practiceScope">
            <el-radio value="document">本学习资料</el-radio>
            <el-radio value="course">整门课程</el-radio>
          </el-radio-group>
          <el-select v-model="practiceQType" placeholder="全部题型（默认仅客观题）" clearable style="width: 170px">
            <el-option label="单选题" value="SINGLE" />
            <el-option label="多选题" value="MULTI" />
            <el-option label="判断题" value="JUDGE" />
            <el-option label="填空题（需教师批改）" value="FILL" />
            <el-option label="解答题（需教师批改）" value="ESSAY" />
          </el-select>
          <el-select v-model="practiceKpId" placeholder="全部知识点" clearable filterable style="width: 200px">
            <el-option v-for="n in practiceKpOptions" :key="n.id" :label="n.label" :value="n.id" />
          </el-select>
          <el-select v-model="practiceCount" style="width: 110px">
            <el-option :value="5" label="5 题" />
            <el-option :value="10" label="10 题" />
            <el-option :value="20" label="20 题" />
          </el-select>
          <el-button type="primary" :icon="Opportunity" :loading="practiceLoading" @click="startPractice">开始练习</el-button>
          <el-button :icon="MagicStick" :loading="practiceLoading" @click="startSmartPractice">智能推荐出题</el-button>
          <el-select v-model="practiceMode" style="width: 130px" :disabled="practiceLoading">
            <el-option v-for="m in PRACTICE_MODES" :key="m.value" :label="m.label" :value="m.value" />
          </el-select>
          <el-button :icon="MagicStick" :loading="practiceLoading" @click="practiceByRecommendation">按推荐知识点出题</el-button>
        </div>
        <div v-loading="practiceStatsLoading" class="practice-kpis">
          <div class="practice-kpi">
            <div class="practice-kpi-value">{{ practiceStats?.answer_count ?? 0 }}</div>
            <div class="practice-kpi-label">累计作答</div>
          </div>
          <div class="practice-kpi">
            <div class="practice-kpi-value">{{ practiceStats?.correct_rate ?? 0 }}%</div>
            <div class="practice-kpi-label">正确率</div>
          </div>
          <div class="practice-kpi">
            <div class="practice-kpi-value">{{ practiceStats?.wrong_question_count ?? 0 }}</div>
            <div class="practice-kpi-label">错题数</div>
          </div>
          <div class="practice-kpi">
            <div class="practice-kpi-value">{{ practiceStats?.favorite_count ?? 0 }}</div>
            <div class="practice-kpi-label">收藏题目</div>
          </div>
        </div>
      </el-card>

      <el-tabs v-model="practiceSubTab">
        <!-- 子页 1：答题 -->
        <el-tab-pane name="doing">
          <template #label><span class="tab-label"><el-icon><EditPen /></el-icon>练习答题</span></template>

          <el-card class="page-card">
            <div v-if="practiceRecommendHint" class="practice-reco-hint">
              <el-icon><DataAnalysis /></el-icon> {{ practiceRecommendHint }}
            </div>
            <el-empty
              v-if="!practiceList.length && !practiceLoading"
              description="还没有题目。请在上方设置出题条件后点击「开始练习」"
              :image-size="80"
            />

            <div v-else-if="currentPracticeQuestion" v-loading="practiceLoading" class="practice-card">
              <div class="practice-head">
                <el-tag size="small" effect="plain">{{ currentPracticeQuestion.q_type_label }}</el-tag>
                <el-tag size="small" type="info" effect="plain">难度 {{ '★'.repeat(currentPracticeQuestion.difficulty || 0) }}</el-tag>
                <el-tag
                  v-if="currentPracticeQuestion.bucket_label"
                  size="small"
                  type="warning"
                  effect="plain"
                >智能推荐 · {{ currentPracticeQuestion.bucket_label }}</el-tag>
                <el-tag
                  v-if="currentPracticeQuestion.kp_name"
                  size="small"
                  effect="plain"
                >{{ currentPracticeQuestion.kp_name }}</el-tag>
                <span class="practice-progress">第 {{ practiceIndex + 1 }} / {{ practiceList.length }} 题</span>
                <div class="practice-head-actions">
                  <el-button
                    size="small"
                    :icon="isPracticeFavorited(currentPracticeQuestion) ? StarFilled : Star"
                    @click="togglePracticeFavorite(currentPracticeQuestion)"
                  >{{ isPracticeFavorited(currentPracticeQuestion) ? '已收藏' : '收藏' }}</el-button>
                  <el-button size="small" @click="viewPracticeKp(currentPracticeQuestion)">查看知识点</el-button>
                </div>
              </div>

              <div v-if="currentPracticeQuestion.reason" class="practice-reason">
                <el-icon><MagicStick /></el-icon> {{ currentPracticeQuestion.reason }}
              </div>

              <div class="practice-stem">{{ currentPracticeQuestion.stem }}</div>

              <!-- 单选 -->
              <el-radio-group
                v-if="currentPracticeQuestion.q_type === 'SINGLE'"
                v-model="practiceAnswers[currentPracticeQuestion.question_id]"
                class="practice-options"
                :disabled="!!practiceResults[currentPracticeQuestion.question_id]"
              >
                <el-radio v-for="o in currentPracticeQuestion.options" :key="o.key" :value="o.key" class="practice-option">
                  {{ o.key }}. {{ o.text }}
                </el-radio>
              </el-radio-group>

              <!-- 多选 -->
              <el-checkbox-group
                v-else-if="currentPracticeQuestion.q_type === 'MULTI'"
                v-model="practiceAnswers[currentPracticeQuestion.question_id]"
                class="practice-options"
                :disabled="!!practiceResults[currentPracticeQuestion.question_id]"
              >
                <el-checkbox v-for="o in currentPracticeQuestion.options" :key="o.key" :value="o.key" class="practice-option">
                  {{ o.key }}. {{ o.text }}
                </el-checkbox>
              </el-checkbox-group>

              <!-- 判断 -->
              <el-radio-group
                v-else-if="currentPracticeQuestion.q_type === 'JUDGE'"
                v-model="practiceAnswers[currentPracticeQuestion.question_id]"
                class="practice-options"
                :disabled="!!practiceResults[currentPracticeQuestion.question_id]"
              >
                <el-radio value="true" class="practice-option">正确</el-radio>
                <el-radio value="false" class="practice-option">错误</el-radio>
              </el-radio-group>

              <!-- 填空（多空输入；提交后进入教师批改队列，批改前不下发参考答案） -->
              <div v-else-if="currentPracticeQuestion.q_type === 'FILL'" class="practice-blanks">
                <div v-for="b in currentPracticeQuestion.options" :key="b.key" class="practice-blank-row">
                  <span class="practice-blank-label">{{ b.label }}</span>
                  <el-input
                    v-model="practiceAnswers[currentPracticeQuestion.question_id][b.key]"
                    :placeholder="b.hint || '填写答案'"
                    :disabled="!!practiceResults[currentPracticeQuestion.question_id]"
                    style="width: 260px"
                  />
                </div>
              </div>

              <!-- 解答（教师批改后给分） -->
              <el-input
                v-else
                v-model="practiceAnswers[currentPracticeQuestion.question_id]"
                type="textarea"
                :rows="5"
                maxlength="4000"
                show-word-limit
                placeholder="请写出你的解答过程（提交后由教师批改）"
                :disabled="!!practiceResults[currentPracticeQuestion.question_id]"
              />

              <!-- 判定结果（客观题提交后即下发答案；主观题批改后才下发） -->
              <div
                v-if="practiceResults[currentPracticeQuestion.question_id]"
                class="practice-result"
                :class="resultClass(currentPracticeQuestion.question_id)"
              >
                <div class="practice-result-head">
                  <el-icon>
                    <component :is="resultIcon(currentPracticeQuestion.question_id)" />
                  </el-icon>
                  {{ resultText(currentPracticeQuestion.question_id) }}
                  <span
                    v-if="!practiceResults[currentPracticeQuestion.question_id].pending"
                    class="practice-result-answer"
                  >
                    正确答案：{{ formatAnswer(practiceResults[currentPracticeQuestion.question_id].correct_answer) }}
                  </span>
                </div>
                <div
                  v-if="practiceResults[currentPracticeQuestion.question_id].comment"
                  class="practice-analysis"
                >
                  教师评语：{{ practiceResults[currentPracticeQuestion.question_id].comment }}
                </div>
                <div v-if="practiceResults[currentPracticeQuestion.question_id].analysis" class="practice-analysis">
                  解析：{{ practiceResults[currentPracticeQuestion.question_id].analysis }}
                </div>
              </div>

              <div class="practice-actions">
                <el-button :disabled="practiceIndex === 0" @click="practiceIndex--">上一题</el-button>
                <el-button
                  v-if="!practiceResults[currentPracticeQuestion.question_id]"
                  type="primary"
                  :loading="practiceSubmitting"
                  @click="submitCurrent"
                >提交答案</el-button>
                <el-button
                  v-else
                  type="primary"
                  :disabled="practiceIndex >= practiceList.length - 1"
                  @click="practiceIndex++"
                >下一题</el-button>
                <el-button
                  v-if="practiceIndex >= practiceList.length - 1 && practiceResults[currentPracticeQuestion.question_id]"
                  @click="startPractice"
                >再练一组</el-button>
              </div>
            </div>
          </el-card>
        </el-tab-pane>

        <!-- 子页 2：错题本 -->
        <el-tab-pane name="wrong">
          <template #label><span class="tab-label"><el-icon><WarningFilled /></el-icon>错题本</span></template>
          <el-card class="page-card">
            <div class="table-toolbar">
              <el-button :icon="Refresh" @click="loadWrongBook">刷新</el-button>
              <span class="practice-tip">按题去重，取每题最近一次答错记录；答对后不会自动移除，便于复习巩固。</span>
            </div>
            <el-table :data="wrongList" v-loading="wrongLoading" row-key="question_id">
              <el-table-column prop="stem" label="题目" min-width="240" show-overflow-tooltip />
              <el-table-column label="题型" width="90">
                <template #default="{ row }"><el-tag size="small" effect="plain">{{ row.q_type_label }}</el-tag></template>
              </el-table-column>
              <el-table-column label="知识点" width="150">
                <template #default="{ row }">
                  <span v-if="row.kp_name">{{ row.kp_name }}</span>
                  <span v-else class="cell-empty">—</span>
                </template>
              </el-table-column>
              <el-table-column prop="wrong_count" label="错答次数" width="90" />
              <el-table-column label="最近错误作答" width="140">
                <template #default="{ row }">{{ formatAnswer(row.last_user_answer) }}</template>
              </el-table-column>
              <!-- 主观题批改结果对学生可见（教师给分与评语；客观题此处为 —） -->
              <el-table-column label="教师给分" width="100">
                <template #default="{ row }">
                  <span v-if="row.grade_source === 'TEACHER' && row.last_score !== null && row.last_score !== undefined">
                    {{ row.last_score }} 分
                  </span>
                  <span v-else class="cell-empty">—</span>
                </template>
              </el-table-column>
              <el-table-column label="教师评语" min-width="140" show-overflow-tooltip>
                <template #default="{ row }">
                  <span v-if="row.last_comment">{{ row.last_comment }}</span>
                  <span v-else class="cell-empty">—</span>
                </template>
              </el-table-column>
              <el-table-column label="正确答案" width="120">
                <template #default="{ row }">{{ formatAnswer(row.correct_answer) }}</template>
              </el-table-column>
              <el-table-column prop="last_wrong_at" label="最近错误时间" width="150" />
              <el-table-column label="操作" width="160" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" type="primary" link @click="redoQuestion(row)">重做</el-button>
                  <el-button size="small" link @click="viewPracticeKp(row)">知识点</el-button>
                </template>
              </el-table-column>
              <template #empty><el-empty description="还没有错题，继续保持！" :image-size="80" /></template>
            </el-table>
          </el-card>
        </el-tab-pane>

        <!-- 子页 3：我的收藏题目 -->
        <el-tab-pane name="fav">
          <template #label><span class="tab-label"><el-icon><StarFilled /></el-icon>收藏题目</span></template>
          <el-card class="page-card">
            <div class="table-toolbar">
              <el-button :icon="Refresh" @click="loadMyQuestionFavorites">刷新</el-button>
              <span class="practice-tip">收藏的题目可随时重做，也可取消收藏。</span>
            </div>
            <el-table :data="myQuestionFavs" v-loading="myQuestionFavLoading" row-key="question_id">
              <el-table-column prop="stem" label="题目" min-width="280" show-overflow-tooltip />
              <el-table-column label="题型" width="90">
                <template #default="{ row }"><el-tag size="small" effect="plain">{{ row.q_type_label }}</el-tag></template>
              </el-table-column>
              <el-table-column prop="favorited_at" label="收藏时间" width="160" />
              <el-table-column label="操作" width="180" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" type="primary" link @click="redoQuestion(row)">重做</el-button>
                  <el-button size="small" type="danger" link @click="togglePracticeFavorite(row)">取消收藏</el-button>
                </template>
              </el-table-column>
              <template #empty><el-empty description="还没有收藏题目" :image-size="80" /></template>
            </el-table>
          </el-card>
        </el-tab-pane>
      </el-tabs>
    </template>
  </div>
</template>

<script setup>
import { toRef } from 'vue'
import { ElMessage } from 'element-plus'
import {
  DataAnalysis, EditPen, MagicStick, Opportunity, Refresh, Star, StarFilled, WarningFilled,
} from '@element-plus/icons-vue'
import { useStudentPractice } from '../../composables/student/useStudentPractice'

const props = defineProps({
  active: { type: Boolean, default: false },
  ctxKey: { type: String, default: '' },
  courseId: { type: [String, Number], default: '' },
  documentId: { type: [String, Number], default: '' },
  graphNodes: { type: Array, default: () => [] },
})

const emit = defineEmits(['locate', 'go-selector'])

const {
  PRACTICE_MODES,
  practiceSubTab,
  practiceScope,
  practiceQType,
  practiceCount,
  practiceKpId,
  practiceKpOptions,
  practiceList,
  practiceIndex,
  practiceLoading,
  practiceSubmitting,
  practiceMode,
  practiceRecommendHint,
  practiceStats,
  practiceStatsLoading,
  practiceAnswers,
  practiceResults,
  wrongList,
  wrongLoading,
  myQuestionFavs,
  myQuestionFavLoading,
  currentPracticeQuestion,
  formatAnswer,
  resultText,
  resultIcon,
  resultClass,
  isPracticeFavorited,
  startPractice,
  startSmartPractice,
  practiceByRecommendation,
  submitCurrent,
  togglePracticeFavorite,
  loadWrongBook,
  loadMyQuestionFavorites,
  redoQuestion,
} = useStudentPractice({
  courseId: toRef(props, 'courseId'),
  documentId: toRef(props, 'documentId'),
  ctxKey: toRef(props, 'ctxKey'),
  active: toRef(props, 'active'),
  graphNodes: toRef(props, 'graphNodes'),
})

/** 查看该题关联的知识点（切到图谱浏览并打开详情抽屉） */
function viewPracticeKp(q) {
  const node = practiceKpOptions.value.find((n) => String(n.id) === String(q?.kp_id))
  if (!node) {
    ElMessage.info('该题未关联图谱知识点')
    return
  }
  emit('locate', node)
}
</script>

<style scoped>
/* ===== 做题练习（学生端题库） ===== */
.practice-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.practice-kpi {
  background: var(--bg-page, #f5f7fa);
  border-radius: 10px;
  padding: 12px 14px;
  text-align: center;
}
.practice-kpi-value {
  font-size: 22px;
  font-weight: 600;
}
.practice-kpi-label {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
}
.chart-title-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  margin-bottom: 12px;
}
.table-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.cell-empty { color: #c0c4cc; }
.practice-tip {
  font-size: 12px;
  color: #909399;
}
.practice-card { padding: 4px 2px; }
.practice-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}
.practice-reco-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
  padding: 8px 12px;
  border-radius: 8px;
  background: #ecf5ff;
  border: 1px solid #d9ecff;
  color: #3a71c1;
  font-size: 12px;
}
.practice-reason {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 4px 0 12px;
  padding: 8px 12px;
  border-radius: 8px;
  background: #fdf6ec;
  border: 1px solid #f5dab1;
  color: #b88230;
  font-size: 13px;
}
.practice-progress {
  color: #909399;
  font-size: 13px;
}
.practice-head-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}
.practice-stem {
  font-size: 16px;
  line-height: 1.7;
  font-weight: 600;
  margin-bottom: 14px;
  white-space: pre-wrap;
}
.practice-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}
/* 选项整行可点，长选项自动换行 */
.practice-option {
  display: flex;
  align-items: center;
  height: auto;
  padding: 8px 12px;
  margin-right: 0 !important;
  border: 1px solid var(--border-light, #ebeef5);
  border-radius: 8px;
  white-space: normal;
  line-height: 1.6;
}
.practice-option.is-checked {
  border-color: #4f6ef7;
  background: rgba(64, 158, 255, 0.06);
}
.practice-result {
  margin-top: 16px;
  padding: 12px 14px;
  border-radius: 8px;
  border-left: 4px solid #67c23a;
  background: rgba(103, 194, 58, 0.08);
}
.practice-result.bad {
  border-left-color: #f56c6c;
  background: rgba(245, 108, 108, 0.08);
}
/* 主观题待批改：中性色（既不是对也不是错） */
.practice-result.pending {
  border-left-color: #e6a23c;
  background: rgba(230, 162, 60, 0.08);
}
/* 填空题：多空输入 */
.practice-blanks {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}
.practice-blank-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.practice-blank-label {
  flex: 0 0 auto;
  min-width: 56px;
  color: var(--text-secondary);
  font-size: 13px;
}
.practice-result-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}
.practice-result-answer {
  margin-left: 8px;
  font-weight: 500;
  color: #606266;
}
.practice-analysis {
  margin-top: 8px;
  color: #606266;
  line-height: 1.7;
  white-space: pre-wrap;
}
.practice-actions {
  display: flex;
  gap: 10px;
  margin-top: 18px;
}
@media (max-width: 767px) {
  .practice-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .practice-head-actions { margin-left: 0; }
}

/* v2 视觉增强 */
.practice-kpi {
  background: #fff;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  transition: transform .22s;
}
.practice-kpi:hover { transform: translateY(-2px); }
.practice-kpi-value { color: var(--brand-600); font-family: var(--font-family-number); }
.practice-option {
  border-radius: var(--radius-sm);
  transition: all .18s;
  cursor: pointer;
}
.practice-option:hover { border-color: var(--brand-300); background: var(--brand-50); }
.practice-option.is-checked {
  border-color: var(--brand-500);
  background: rgba(79, 110, 247, .07);
}
.practice-result {
  border-radius: var(--radius-sm);
  border-left-width: 4px;
  border-left-color: var(--success);
  background: rgba(24, 184, 122, .08);
}
.practice-result.bad {
  border-left-color: var(--danger);
  background: rgba(244, 88, 122, .08);
}
</style>
