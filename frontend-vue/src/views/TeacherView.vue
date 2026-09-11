<template>
  <div>
    <PageHeader title="课程管理" desc="管理课程、课程文档、知识图谱、题库与教学监测" />

    <el-tabs v-model="activeTab" @tab-change="onTabChange">
      <!-- ===================== Tab 0：课程列表 ===================== -->
      <el-tab-pane name="courses">
        <template #label><span class="tab-label"><el-icon><Notebook /></el-icon>课程管理</span></template>

        <div class="course-toolbar">
          <span class="stats-text">共 {{ store.courses.length }} 门课程</span>
          <el-button type="primary" :icon="Plus" @click="openCreateCourse">新建课程</el-button>
        </div>

        <div v-loading="store.isLoading" class="course-grid-wrap">
          <el-empty
            v-if="!store.isLoading && !store.courses.length"
            description="暂无课程，点击「新建课程」开始"
          >
            <el-button type="primary" :icon="Plus" @click="openCreateCourse">新建课程</el-button>
          </el-empty>

          <div v-else class="course-grid">
            <div v-for="c in store.courses" :key="c.course_id" class="course-card">
              <div class="course-card-head">
                <span class="course-name" :title="c.course_name">{{ c.course_name }}</span>
                <el-tag size="small" :type="c.status === 1 ? 'success' : 'info'">
                  {{ c.status === 1 ? '正常' : '停用' }}
                </el-tag>
              </div>
              <div class="course-desc" :title="c.description">
                {{ c.course_code ? `【${c.course_code}】` : '' }}{{ c.description || '暂无课程简介' }}
              </div>

              <div class="course-stats">
                <div class="course-stat">
                  <el-icon color="var(--color-primary)"><Document /></el-icon>
                  <span class="stat-num">{{ c.document_count ?? 0 }}</span>
                  <span class="stat-label">文档</span>
                </div>
                <div class="course-stat">
                  <el-icon color="var(--color-warning)"><DataAnalysis /></el-icon>
                  <span class="stat-num">{{ c.node_count ?? 0 }}</span>
                  <span class="stat-label">知识点</span>
                </div>
                <div class="course-stat">
                  <el-icon color="var(--color-success)"><Connection /></el-icon>
                  <span class="stat-num">{{ c.edge_count ?? 0 }}</span>
                  <span class="stat-label">关系</span>
                </div>
              </div>

              <div class="course-card-foot">
                <span class="course-updated"><el-icon><Clock /></el-icon> 更新于 {{ fmtTime(c.updated_at) }}</span>
                <div class="course-actions">
                  <el-button size="small" type="primary" plain :icon="Files" @click="manageDocuments(c)">管理文档</el-button>
                  <el-button size="small" type="danger" plain :icon="Delete" @click="deleteCourse(c)">删除</el-button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- ===================== Tab 1：课程文档 ===================== -->
      <el-tab-pane name="documents">
        <template #label><span class="tab-label"><el-icon><FolderOpened /></el-icon>课程文档</span></template>

        <!-- 未选择课程：页内引导选择（不再弹窗强制跳回课程列表） -->
        <el-card v-if="!currentCourseId" class="page-card">
          <el-empty description="请先选择要管理文档的课程">
            <div class="doc-course-pick">
              <el-select
                v-model="currentCourseId"
                placeholder="选择课程"
                filterable
                clearable
                style="width: 260px"
                @change="syncDocumentsRoute"
              >
                <el-option
                  v-for="c in store.courses"
                  :key="c.course_id"
                  :label="c.course_name"
                  :value="String(c.course_id)"
                />
              </el-select>
              <el-button :icon="Notebook" @click="goCourses">前往课程管理</el-button>
              <el-button type="primary" :icon="Plus" @click="openCreateCourse">新建课程</el-button>
            </div>
            <p v-if="!store.courses.length" class="doc-course-pick-tip">暂无课程，可先点击「新建课程」创建</p>
          </el-empty>
        </el-card>

        <template v-else>
        <div class="context-bar">
          <el-button text :icon="Back" @click="backToCourses">返回课程列表</el-button>
          <el-divider direction="vertical" />
          <span class="context-title">{{ currentCourseName }}</span>
          <el-tag v-if="currentCourse?.course_code" size="small" type="info">
            {{ currentCourse.course_code }}
          </el-tag>
          <el-select
            v-model="currentCourseId"
            class="course-switcher"
            size="small"
            filterable
            clearable
            placeholder="切换课程"
            @change="syncDocumentsRoute"
          >
            <el-option
              v-for="c in store.courses"
              :key="c.course_id"
              :label="c.course_name"
              :value="String(c.course_id)"
            />
          </el-select>
        </div>

        <!-- 上传入口（上传到当前课程，不再自动建课） -->
        <el-card class="page-card upload-card">
          <template #header><span class="panel-header">上传文档</span></template>
          <el-form label-width="80px">
            <el-form-item label="选择文件">
              <el-upload
                drag
                :auto-upload="false"
                :limit="1"
                :on-change="onFileChange"
                :on-remove="onFileRemove"
                accept=".pdf,.txt,.docx,.md"
                style="max-width: 520px"
              >
                <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
                <div class="el-upload__text">将文件拖到此处，或<em>点击选择</em></div>
                <template #tip>
                  <div class="el-upload__tip">上传到当前课程，支持 PDF / DOCX / TXT / MD，单文件不超过 50MB</div>
                </template>
              </el-upload>
            </el-form-item>
            <el-form-item>
              <el-button
                type="primary"
                :icon="Upload"
                :loading="uploading"
                :disabled="!selectedFile"
                @click="doUpload"
              >
                上传并构建知识图谱
              </el-button>
            </el-form-item>
          </el-form>
          <el-alert
            v-if="uploadResult"
            type="success"
            :closable="false"
            class="upload-result-alert"
            :title="`「${uploadResult.filename}」上传成功：知识点 ${uploadResult.entity_count ?? 0}，关系 ${uploadResult.relation_count ?? 0}`"
          />
          <el-alert
            v-if="uploadError"
            type="error"
            :closable="false"
            :title="uploadError"
            class="upload-result-alert"
          />
        </el-card>

        <!-- 文档列表 -->
        <el-card class="page-card">
          <template #header>
            <div class="doc-toolbar">
              <span class="panel-header">文档列表（{{ documents.length }}）</span>
              <el-button :icon="Refresh" circle size="small" aria-label="刷新文档列表" @click="loadDocuments" />
            </div>
          </template>
          <el-table :data="documents" v-loading="documentsLoading" class="doc-table">
            <el-table-column prop="file_name" label="文件名" min-width="180" show-overflow-tooltip />
            <el-table-column prop="file_type" label="类型" width="80" align="center" />
            <el-table-column label="大小" width="100" align="center">
              <template #default="{ row }">{{ fmtSize(row.file_size) }}</template>
            </el-table-column>
            <el-table-column label="解析状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="parseStatusType(row.parse_status)" size="small">{{ parseStatusText(row.parse_status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="抽取状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="extractStatusType(row.extract_status)" size="small">{{ extractStatusText(row.extract_status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="生成进度" min-width="180">
              <template #default="{ row }">
                <el-progress
                  :percentage="docProgress(row)"
                  :status="docProgressStatus(row)"
                  :stroke-width="10"
                  :striped="isDocInFlight(row)"
                  :striped-flow="isDocInFlight(row)"
                />
              </template>
            </el-table-column>
            <el-table-column prop="entity_count" label="知识点" width="80" align="center" />
            <el-table-column prop="relation_count" label="关系" width="70" align="center" />
            <el-table-column label="创建时间" width="150">
              <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="392" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="primary" :icon="Reading" :disabled="row.is_placeholder" @click="readDocument(row)">在线阅读</el-button>
                <el-button size="small" :icon="Download" plain :disabled="row.is_placeholder" @click="downloadDocument(row)">下载</el-button>
                <el-button size="small" type="primary" plain :icon="View" :disabled="row.is_placeholder" @click="viewDocumentGraph(row)">查看图谱</el-button>
                <el-button size="small" type="warning" plain :icon="EditPen" :disabled="row.is_placeholder" @click="editDocumentGraph(row)">编辑</el-button>
                <el-button size="small" type="success" plain :icon="UserFilled" :disabled="row.is_placeholder" @click="monitorDocument(row)">监测</el-button>
                <el-button size="small" type="danger" plain :icon="Delete" :disabled="row.is_placeholder" @click="deleteDocument(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无文档，请在上方上传" :image-size="80" />
            </template>
          </el-table>
        </el-card>
        </template>
      </el-tab-pane>

      <!-- ===================== Tab 2：文档图谱预览 ===================== -->
      <el-tab-pane name="preview">
        <template #label><span class="tab-label"><el-icon><View /></el-icon>图谱预览</span></template>

        <!-- 未选择课程/文档：页内引导选择（不再弹窗强制跳回） -->
        <el-card v-if="!currentCourseId || !currentDocumentId" class="page-card">
          <el-empty description="请先选择要预览图谱的课程和文档">
            <div class="doc-course-pick">
              <el-select v-model="currentCourseId" placeholder="选择课程" filterable clearable style="width: 220px" @change="onContextCourseChange">
                <el-option v-for="c in store.courses" :key="c.course_id" :label="c.course_name" :value="String(c.course_id)" />
              </el-select>
              <el-select v-model="currentDocumentId" placeholder="选择文档" filterable clearable style="width: 240px" :disabled="!currentCourseId" @change="onContextDocChange">
                <el-option v-for="d in documents" :key="d.doc_id" :label="d.file_name" :value="String(d.doc_id)" />
              </el-select>
              <el-button :icon="Notebook" @click="goCourses">前往课程管理</el-button>
            </div>
            <p v-if="currentCourseId && !documents.length" class="doc-course-pick-tip">该课程暂无文档，请先到「课程文档」上传</p>
          </el-empty>
        </el-card>

        <template v-else>
        <div class="context-bar">
          <el-button text :icon="Back" @click="backToDocuments">返回文档列表</el-button>
          <el-divider direction="vertical" />
          <span class="context-title">{{ currentCourseName }}</span>
          <el-tag size="small" type="info">{{ currentDocumentName || '文档' }}</el-tag>
        </div>

        <el-card class="page-card">
          <div class="toolbar">
            <el-input
              v-model="previewSearch"
              placeholder="搜索知识点…"
              clearable
              :prefix-icon="Search"
              style="width: 220px"
            />
            <el-button :icon="Refresh" circle title="刷新" @click="refreshPreview" />
            <el-button :icon="FullScreen" circle title="适配视图" @click="fitPreview" />
            <span v-if="previewStats" class="stats-text">
              节点 {{ previewStats.nodeCount }} · 关系 {{ previewStats.edgeCount }}
            </span>
          </div>
        </el-card>
        <el-card class="page-card graph-card">
          <GraphCanvas
            ref="previewGraphRef"
            :course-id="currentCourseId"
            :document-id="currentDocumentId"
            :search-text="previewSearch"
            @node-click="onNodeClick"
            @loaded="(s) => (previewStats = s)"
          />
        </el-card>
        </template>
      </el-tab-pane>

      <!-- ===================== Tab 3：编辑图谱（三栏审核） ===================== -->
      <el-tab-pane name="edit">
        <template #label><span class="tab-label"><el-icon><EditPen /></el-icon>编辑图谱</span></template>

        <!-- 未选择课程/文档：页内引导选择（不再弹窗强制跳回） -->
        <el-card v-if="!currentCourseId || !currentDocumentId" class="page-card">
          <el-empty description="请先选择要编辑图谱的课程和文档">
            <div class="doc-course-pick">
              <el-select v-model="currentCourseId" placeholder="选择课程" filterable clearable style="width: 220px" @change="onContextCourseChange">
                <el-option v-for="c in store.courses" :key="c.course_id" :label="c.course_name" :value="String(c.course_id)" />
              </el-select>
              <el-select v-model="currentDocumentId" placeholder="选择文档" filterable clearable style="width: 240px" :disabled="!currentCourseId" @change="onContextDocChange">
                <el-option v-for="d in documents" :key="d.doc_id" :label="d.file_name" :value="String(d.doc_id)" />
              </el-select>
              <el-button :icon="Notebook" @click="goCourses">前往课程管理</el-button>
            </div>
            <p v-if="currentCourseId && !documents.length" class="doc-course-pick-tip">该课程暂无文档，请先到「课程文档」上传</p>
          </el-empty>
        </el-card>

        <template v-else>
        <div class="context-bar">
          <el-button text :icon="Back" @click="backToDocuments">返回文档列表</el-button>
          <el-divider direction="vertical" />
          <span class="context-title">{{ currentCourseName }}</span>
          <el-tag size="small" type="info">{{ currentDocumentName || '文档' }}</el-tag>
        </div>

        <el-card class="page-card">
          <div class="toolbar">
            <el-button type="primary" :icon="Plus" @click="openAddNode">新增知识点</el-button>
            <el-button type="success" plain :icon="Connection" @click="openAddEdge">新增关系</el-button>
            <el-button :icon="Refresh" circle title="刷新" @click="refreshEdit" />
            <span v-if="currentCourseId" class="stats-text">节点 {{ editNodes.length }}</span>
          </div>
        </el-card>

        <!-- 三栏：知识点列表 | 图谱 | 详情面板 -->
        <el-row :gutter="12" class="workspace">
          <el-col :xs="24" :sm="5">
            <el-card class="panel-card">
              <template #header>
                <div class="panel-header">知识点列表（{{ filteredEditNodes.length }}）</div>
              </template>
              <el-input
                v-model="nodeListSearch"
                placeholder="搜索知识点…"
                clearable
                :prefix-icon="Search"
                size="small"
                class="list-search"
              />
              <div class="panel-scroll">
                <el-empty
                  v-if="!currentCourseId"
                  description="请先选择文档"
                  :image-size="60"
                />
                <el-empty
                  v-else-if="!filteredEditNodes.length"
                  description="暂未生成知识点"
                  :image-size="60"
                />
                <div
                  v-for="n in filteredEditNodes"
                  :key="n.id"
                  class="node-item"
                  :class="{ active: selectedNode?.id === n.id }"
                  @click="selectNode(n)"
                >
                  <i class="node-dot" :style="{ background: nodeColor(n.type) }"></i>
                  <span class="node-item-label">{{ n.label }}</span>
                  <el-tag size="small" type="info" effect="plain">{{ nodeTypeLabel(n.type) }}</el-tag>
                </div>
              </div>
            </el-card>
          </el-col>

          <el-col :xs="24" :sm="13">
            <el-card class="panel-card graph-panel">
              <GraphCanvas
                ref="editGraphRef"
                :course-id="currentCourseId"
                :document-id="currentDocumentId"
                :editable="true"
                @node-click="onEditNodeClick"
                @edge-click="onEditEdgeClick"
              />
            </el-card>
          </el-col>

          <el-col :xs="24" :sm="6">
            <el-card class="panel-card">
              <template #header>
                <div class="panel-header">知识点详情</div>
              </template>
              <div class="panel-scroll">
                <el-empty
                  v-if="!selectedNode"
                  description="点击左侧列表或图谱节点查看详情"
                  :image-size="60"
                />
                <template v-else>
                  <div class="detail-title">
                    <span class="detail-name">{{ selectedNode.label }}</span>
                    <el-tag size="small">{{ nodeTypeLabel(selectedNode.type) }}</el-tag>
                    <el-tag v-if="selectedNode.properties?.is_manual" size="small" type="warning" effect="plain">人工</el-tag>
                  </div>
                  <el-descriptions :column="1" border size="small">
                    <el-descriptions-item label="描述">
                      {{ selectedNode.description || '暂无描述' }}
                    </el-descriptions-item>
                    <el-descriptions-item v-if="selectedNode.properties?.confidence != null" label="置信度">
                      {{ selectedNode.properties.confidence }}
                    </el-descriptions-item>
                  </el-descriptions>

                  <el-divider content-position="left">编辑</el-divider>
                  <el-form label-position="top" size="small">
                    <el-form-item label="名称">
                      <el-input v-model="editForm.name" />
                    </el-form-item>
                    <el-form-item label="类别">
                      <el-select v-model="editForm.category" style="width: 100%">
                        <el-option label="概念" value="概念" />
                        <el-option label="定理" value="定理" />
                        <el-option label="公式" value="公式" />
                        <el-option label="方法" value="方法" />
                      </el-select>
                    </el-form-item>
                    <el-form-item label="描述">
                      <el-input v-model="editForm.description" type="textarea" :rows="3" />
                    </el-form-item>
                  </el-form>
                  <div class="detail-actions">
                    <el-button type="primary" size="small" :loading="savingNode" @click="saveNode">保存</el-button>
                    <el-button type="danger" size="small" plain :loading="deletingNode" @click="deleteNode">删除</el-button>
                  </div>

                  <el-divider content-position="left">前置知识</el-divider>
                  <el-button size="small" :loading="prereqLoading" @click="loadPrereqs">查询前置知识</el-button>
                  <el-empty
                    v-if="!prereqLoading && prereqLoaded && !prereqs.length"
                    description="未查询到前置知识"
                    :image-size="50"
                  />
                  <ul class="prereq-list">
                    <li v-for="p in prereqs" :key="p.name">
                      <el-tag size="small" type="info">{{ p.depth }} 级前置</el-tag>
                      <span class="prereq-name">{{ p.name }}</span>
                      <div class="prereq-desc">{{ p.description }}</div>
                    </li>
                  </ul>
                </template>
              </div>
            </el-card>
          </el-col>
        </el-row>
        </template>
      </el-tab-pane>

      <!-- ===================== Tab 4：教学监测 ===================== -->
      <el-tab-pane name="monitor">
        <template #label><span class="tab-label"><el-icon><UserFilled /></el-icon>教学监测</span></template>

        <!-- 未选择课程：页内引导选择（不再弹窗强制跳回） -->
        <el-card v-if="!currentCourseId" class="page-card">
          <el-empty description="请先选择要查看教学监测的课程">
            <div class="doc-course-pick">
              <el-select v-model="currentCourseId" placeholder="选择课程" filterable clearable style="width: 260px" @change="onContextCourseChange">
                <el-option v-for="c in store.courses" :key="c.course_id" :label="c.course_name" :value="String(c.course_id)" />
              </el-select>
              <el-button :icon="Notebook" @click="goCourses">前往课程管理</el-button>
            </div>
          </el-empty>
        </el-card>

        <template v-else>
        <div class="context-bar">
          <el-button text :icon="Back" @click="backToDocuments">返回文档列表</el-button>
          <el-divider direction="vertical" />
          <span class="context-title">{{ currentCourseName }}</span>
          <el-tag v-if="currentDocumentName" size="small" type="info">{{ currentDocumentName }}</el-tag>
        </div>

        <!-- 第一层：班级学习情况（真实学生数据） -->
        <el-card v-if="currentCourseId" class="page-card">
          <div class="chart-title-line">
            <el-icon><UserFilled /></el-icon> 班级学习情况
            <span class="class-note">（无选课关系表，班级学生 = 在该课程有学习记录的学生）</span>
          </div>

          <div v-loading="monitorLoading" class="class-summary">
            <div v-for="k in monitorKpis" :key="k.label" class="class-kpi">
              <div class="class-kpi-value" :style="{ color: k.color }">{{ k.value }}</div>
              <div class="class-kpi-label">{{ k.label }}</div>
            </div>
          </div>

          <el-empty
            v-if="!monitorLoading && monitorData && !monitorData.student_count"
            description="暂无学生学习记录（尚未有学生开始学习该课程）"
            :image-size="80"
          />
          <div v-else ref="progressDistRef" class="dist-chart"></div>
        </el-card>

        <!-- 第二层：学生学习情况表格 -->
        <el-card v-if="currentCourseId" class="page-card">
          <div class="chart-title-line"><el-icon><User /></el-icon> 学生学习情况</div>

          <div class="table-toolbar">
            <el-input
              v-model="monitorSearch"
              placeholder="搜索学生姓名 / 用户名"
              clearable
              :prefix-icon="Search"
              style="width: 240px"
            />
            <el-select v-model="monitorProgressFilter" placeholder="进度筛选" clearable style="width: 150px">
              <el-option
                v-for="b in progressBins"
                :key="b.value"
                :label="b.label"
                :value="b.value"
              />
            </el-select>
          </div>

          <el-table
            :data="pagedMonitorStudents"
            v-loading="monitorLoading"
            :default-sort="{ prop: 'progress', order: 'ascending' }"
            @sort-change="onMonitorSortChange"
          >
            <el-table-column prop="student_name" label="学生" sortable="custom" min-width="140">
              <template #default="{ row }">
                <span class="student-cell">
                  {{ row.student_name }}
                  <span v-if="row.username && row.username !== row.student_name" class="student-username">
                    @{{ row.username }}
                  </span>
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="total_knowledge" label="知识点总数" width="110" align="center" />
            <el-table-column prop="mastered_count" label="已掌握" width="90" align="center" />
            <el-table-column prop="progress" label="学习进度" sortable="custom" min-width="150">
              <template #default="{ row }">
                <el-progress
                  :percentage="row.progress"
                  :color="progressColor(row.progress)"
                  :stroke-width="10"
                />
              </template>
            </el-table-column>
            <el-table-column label="当前学习" min-width="160">
              <template #default="{ row }">
                <span v-if="row.current_name" class="current-name">{{ row.current_name }}</span>
                <span v-else class="cell-empty">—</span>
              </template>
            </el-table-column>
            <el-table-column label="推荐学习" min-width="180">
              <template #default="{ row }">
                <template v-if="row.recommended && row.recommended.length">
                  <el-tag
                    v-for="r in row.recommended.slice(0, 3)"
                    :key="r.kp_id || r.name"
                    size="small"
                    class="rec-tag"
                  >{{ r.name }}</el-tag>
                </template>
                <span v-else class="cell-empty">—</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90" align="center">
              <template #default="{ row }">
                <el-tag :type="statusType(row.progress)" size="small" effect="plain">
                  {{ statusText(row.progress) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="90" align="center" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="primary" link @click="openMonitorStudentDetail(row)">
                  查看
                </el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无学生学习记录" :image-size="80" />
            </template>
          </el-table>

          <el-pagination
            v-if="filteredMonitorStudents.length > monitorPageSize"
            class="table-pagination"
            v-model:current-page="monitorPage"
            v-model:page-size="monitorPageSize"
            :page-sizes="[10, 20, 50]"
            :total="filteredMonitorStudents.length"
            layout="total, sizes, prev, pager, next"
          />
        </el-card>
        </template>
      </el-tab-pane>

      <!-- ===================== Tab 5：题库管理（Scope A：单选/多选/判断，答案仅教师可见） ===================== -->
      <el-tab-pane name="questions">
        <template #label><span class="tab-label"><el-icon><Collection /></el-icon>题库管理</span></template>

        <!-- 未选择课程：页内引导选择（与教学监测一致，不弹窗强制跳回） -->
        <el-card v-if="!currentCourseId" class="page-card">
          <el-empty description="请先选择要管理题库的课程">
            <div class="doc-course-pick">
              <el-select v-model="currentCourseId" placeholder="选择课程" filterable clearable style="width: 260px" @change="onContextCourseChange">
                <el-option v-for="c in store.courses" :key="c.course_id" :label="c.course_name" :value="String(c.course_id)" />
              </el-select>
              <el-button :icon="Notebook" @click="goCourses">前往课程管理</el-button>
            </div>
          </el-empty>
        </el-card>

        <template v-else>
          <!-- 第一层：题库总览（题量 / 题型分布 / 作答正确率 / 收藏） -->
          <el-card class="page-card">
            <div class="chart-title-line">
              <el-icon><Collection /></el-icon> 题库总览
              <span class="class-note">（{{ currentCourseName }}）</span>
            </div>
            <div v-loading="questionsLoading" class="class-summary">
              <div class="class-kpi">
                <div class="class-kpi-value">{{ questionStats?.total ?? 0 }}</div>
                <div class="class-kpi-label">题目总数</div>
              </div>
              <div class="class-kpi">
                <div class="class-kpi-value">{{ questionStats?.active_count ?? 0 }}</div>
                <div class="class-kpi-label">启用中</div>
              </div>
              <div class="class-kpi">
                <div class="class-kpi-value">{{ questionStats?.by_type?.SINGLE ?? 0 }}</div>
                <div class="class-kpi-label">单选题</div>
              </div>
              <div class="class-kpi">
                <div class="class-kpi-value">{{ questionStats?.by_type?.MULTI ?? 0 }}</div>
                <div class="class-kpi-label">多选题</div>
              </div>
              <div class="class-kpi">
                <div class="class-kpi-value">{{ questionStats?.by_type?.JUDGE ?? 0 }}</div>
                <div class="class-kpi-label">判断题</div>
              </div>
              <div class="class-kpi">
                <div class="class-kpi-value">{{ questionStats?.answer_count ?? 0 }}</div>
                <div class="class-kpi-label">累计作答</div>
              </div>
              <div class="class-kpi">
                <div class="class-kpi-value">{{ questionStats?.correct_rate ?? 0 }}%</div>
                <div class="class-kpi-label">平均正确率</div>
              </div>
              <div class="class-kpi">
                <div class="class-kpi-value">{{ questionStats?.favorite_total ?? 0 }}</div>
                <div class="class-kpi-label">被收藏</div>
              </div>
            </div>
          </el-card>

          <!-- 第二层：题目列表 -->
          <el-card class="page-card">
            <div class="chart-title-line"><el-icon><Files /></el-icon> 题目列表</div>

            <div class="table-toolbar">
              <el-select v-model="questionDocFilter" placeholder="全部文档（含课程通用题）" clearable style="width: 210px" @change="loadQuestionsTab">
                <el-option v-for="d in documents" :key="d.doc_id" :label="d.file_name" :value="String(d.doc_id)" />
              </el-select>
              <el-select v-model="questionFilters.q_type" placeholder="全部题型" clearable style="width: 130px" @change="loadQuestionsTab">
                <el-option v-for="t in QUESTION_TYPES" :key="t.value" :label="t.label" :value="t.value" />
              </el-select>
              <el-select v-model="questionFilters.is_active" placeholder="全部状态" clearable style="width: 130px" @change="loadQuestionsTab">
                <el-option label="启用中" value="1" />
                <el-option label="已停用" value="0" />
              </el-select>
              <el-input
                v-model="questionFilters.keyword"
                placeholder="搜索题干"
                clearable
                :prefix-icon="Search"
                style="width: 190px"
                @keyup.enter="loadQuestionsTab"
                @clear="loadQuestionsTab"
              />
              <el-button :icon="Refresh" @click="loadQuestionsTab">刷新</el-button>
              <el-button type="primary" :icon="Plus" @click="openQuestionForm(null)">新增题目</el-button>
              <el-button :icon="Star" @click="openQuestionFavorites">题目收藏情况</el-button>
            </div>

            <el-table :data="questionList" v-loading="questionsLoading" row-key="question_id">
              <el-table-column prop="stem" label="题干" min-width="260" show-overflow-tooltip />
              <el-table-column label="题型" width="90">
                <template #default="{ row }">
                  <el-tag size="small" effect="plain">{{ row.q_type_label || questionTypeLabel(row.q_type) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="知识点" width="150">
                <template #default="{ row }">
                  <span v-if="row.kp_id">{{ kpNameById(row.kp_id) || row.kp_id }}</span>
                  <span v-else class="cell-empty">课程通用</span>
                </template>
              </el-table-column>
              <el-table-column label="难度" width="90">
                <template #default="{ row }">{{ '★'.repeat(row.difficulty || 0) || '—' }}</template>
              </el-table-column>
              <el-table-column label="作答 / 正确率" width="140">
                <template #default="{ row }">
                  <span v-if="row.attempts">{{ row.attempts }} 次 / {{ row.correct_rate }}%</span>
                  <span v-else class="cell-empty">—</span>
                </template>
              </el-table-column>
              <el-table-column prop="favorite_count" label="收藏" width="70" />
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="200" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" type="primary" link @click="openQuestionForm(row)">编辑</el-button>
                  <el-button size="small" link @click="toggleQuestionActive(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
                  <el-button size="small" type="danger" link @click="removeQuestion(row)">删除</el-button>
                </template>
              </el-table-column>
              <template #empty>
                <el-empty description="本课程还没有题目，点击「新增题目」开始" :image-size="80" />
              </template>
            </el-table>

            <el-pagination
              v-if="questionTotal > questionPageSize"
              class="table-pagination"
              v-model:current-page="questionPage"
              v-model:page-size="questionPageSize"
              :page-sizes="[10, 20, 50]"
              :total="questionTotal"
              layout="total, sizes, prev, pager, next"
              @current-change="loadQuestions"
              @size-change="loadQuestionsTab"
            />
          </el-card>

          <!-- 新增 / 编辑题目 -->
          <el-dialog
            v-model="questionFormVisible"
            :title="questionEditingId ? '编辑题目' : '新增题目'"
            width="720px"
            :close-on-click-modal="false"
          >
            <el-form label-width="96px">
              <el-form-item label="题型">
                <el-radio-group v-model="questionForm.q_type" :disabled="!!questionEditingId">
                  <el-radio v-for="t in QUESTION_TYPES" :key="t.value" :value="t.value">{{ t.label }}</el-radio>
                </el-radio-group>
              </el-form-item>
              <el-form-item label="题干">
                <el-input v-model="questionForm.stem" type="textarea" :rows="3" maxlength="1000" show-word-limit placeholder="请输入题干" />
              </el-form-item>

              <template v-if="questionForm.q_type !== 'JUDGE'">
                <el-form-item v-for="(opt, idx) in questionForm.options" :key="opt.key" :label="`选项 ${opt.key}`">
                  <div class="opt-row">
                    <el-input v-model="opt.text" placeholder="选项内容" />
                    <el-button :icon="Delete" text type="danger" :disabled="questionForm.options.length <= 2" @click="removeQuestionOption(idx)" />
                  </div>
                </el-form-item>
                <el-form-item label=" ">
                  <el-button :icon="Plus" size="small" :disabled="questionForm.options.length >= 8" @click="addQuestionOption">添加选项</el-button>
                </el-form-item>
                <el-form-item label="正确答案">
                  <el-radio-group v-if="questionForm.q_type === 'SINGLE'" v-model="questionForm.singleAnswer">
                    <el-radio v-for="o in questionForm.options" :key="o.key" :value="o.key">{{ o.key }}</el-radio>
                  </el-radio-group>
                  <el-checkbox-group v-else v-model="questionForm.multiAnswer">
                    <el-checkbox v-for="o in questionForm.options" :key="o.key" :value="o.key">{{ o.key }}</el-checkbox>
                  </el-checkbox-group>
                </el-form-item>
              </template>
              <el-form-item v-else label="正确答案">
                <el-radio-group v-model="questionForm.judgeAnswer">
                  <el-radio value="true">正确</el-radio>
                  <el-radio value="false">错误</el-radio>
                </el-radio-group>
              </el-form-item>

              <el-form-item label="解析">
                <el-input v-model="questionForm.analysis" type="textarea" :rows="2" maxlength="1000" placeholder="可选：答案解析（提交后展示给学生）" />
              </el-form-item>
              <el-form-item label="难度">
                <el-rate v-model="questionForm.difficulty" :max="5" />
              </el-form-item>
              <el-form-item label="所属文档">
                <el-select v-model="questionForm.document_id" placeholder="课程通用题（任意文档练习均可见）" clearable style="width: 100%">
                  <el-option v-for="d in documents" :key="d.doc_id" :label="d.file_name" :value="String(d.doc_id)" />
                </el-select>
              </el-form-item>
              <el-form-item label="关联知识点">
                <el-select v-model="questionForm.kp_id" placeholder="可选：关联图谱知识点（用于推荐练题）" clearable filterable style="width: 100%">
                  <el-option v-for="n in questionKpOptions" :key="n.id" :label="n.label" :value="n.id" />
                </el-select>
              </el-form-item>
            </el-form>
            <template #footer>
              <el-button @click="questionFormVisible = false">取消</el-button>
              <el-button type="primary" :loading="questionFormLoading" @click="submitQuestionForm">保存</el-button>
            </template>
          </el-dialog>

          <!-- 题目收藏情况（哪些学生收藏了哪道题） -->
          <el-dialog v-model="questionFavVisible" title="题目收藏情况" width="660px">
            <el-table :data="questionFavs" v-loading="questionFavLoading" max-height="420">
              <el-table-column prop="student_name" label="学生" width="140" />
              <el-table-column prop="stem" label="题目" min-width="240" show-overflow-tooltip />
              <el-table-column prop="q_type_label" label="题型" width="90" />
              <el-table-column prop="created_at" label="收藏时间" width="150" />
              <template #empty><el-empty description="暂无学生收藏题目" :image-size="70" /></template>
            </el-table>
          </el-dialog>
        </template>
      </el-tab-pane>
    </el-tabs>

    <!-- 预览 Tab 的节点详情抽屉（只读） -->
    <NodeDetailDrawer
      v-model="drawerVisible"
      :node="drawerNode"
      :course-id="currentCourseId"
      :document-id="currentDocumentId"
      @saved="afterNodeChanged"
      @deleted="afterNodeChanged"
    />

    <!-- 教学监测：学生详情抽屉 -->
    <el-drawer v-model="monitorDetailVisible" title="学生学习详情" direction="rtl" size="480px">
      <template v-if="monitorDetailStudent">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="学生">
            {{ monitorDetailStudent.student_name }}
            <span
              v-if="monitorDetailStudent.username && monitorDetailStudent.username !== monitorDetailStudent.student_name"
              class="detail-username"
            >@{{ monitorDetailStudent.username }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="当前课程">{{ currentCourseName }}</el-descriptions-item>
          <el-descriptions-item label="学习进度">
            <el-progress
              :percentage="monitorDetailStudent.progress"
              :color="progressColor(monitorDetailStudent.progress)"
              :stroke-width="10"
            />
          </el-descriptions-item>
          <el-descriptions-item label="已掌握数量">
            {{ monitorDetailStudent.mastered_count }} / {{ monitorDetailStudent.total_knowledge }}
          </el-descriptions-item>
          <el-descriptions-item label="未学习数量">{{ monitorDetailStudent.unmastered_count }}</el-descriptions-item>
          <el-descriptions-item label="当前学习知识点">
            {{ monitorDetailStudent.current_name || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="收藏数量">{{ monitorDetailStudent.favorite_count }}</el-descriptions-item>
        </el-descriptions>

        <el-divider content-position="left">推荐学习知识点</el-divider>
        <ul v-if="monitorDetailStudent.recommended && monitorDetailStudent.recommended.length" class="rec-list">
          <li v-for="r in monitorDetailStudent.recommended" :key="r.kp_id || r.name">
            <el-tag size="small" effect="plain">{{ r.category || '知识点' }}</el-tag>
            <span class="rec-name">{{ r.name }}</span>
            <div class="rec-reason">{{ r.reason }}</div>
          </li>
        </ul>
        <el-empty v-else description="暂无推荐" :image-size="60" />

        <div class="drawer-actions">
          <el-button type="primary" :disabled="!currentDocumentId" @click="goMonitorGraph">查看知识图谱</el-button>
        </div>
      </template>
    </el-drawer>

    <!-- 新增知识点对话框 -->
    <el-dialog v-model="addNodeVisible" title="新增知识点" width="480px">
      <el-form label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="addNodeForm.name" placeholder="知识点名称" />
        </el-form-item>
        <el-form-item label="类别">
          <el-select v-model="addNodeForm.category" style="width: 100%">
            <el-option label="概念" value="概念" />
            <el-option label="定理" value="定理" />
            <el-option label="公式" value="公式" />
            <el-option label="方法" value="方法" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="addNodeForm.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addNodeVisible = false">取消</el-button>
        <el-button type="primary" :loading="addNodeLoading" @click="submitAddNode">确定</el-button>
      </template>
    </el-dialog>

    <!-- 新增关系对话框 -->
    <el-dialog v-model="addEdgeVisible" title="新增关系" width="480px">
      <el-form label-width="80px">
        <el-form-item label="源知识点">
          <el-select v-model="addEdgeForm.source" filterable style="width: 100%">
            <el-option v-for="n in editNodes" :key="n.id" :label="n.label" :value="n.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="关系类型">
          <el-select v-model="addEdgeForm.type" style="width: 100%">
            <el-option label="前置知识（PRECEDES）" value="PRECEDES" />
            <el-option label="包含（CONTAINS）" value="CONTAINS" />
            <el-option label="相关概念（RELATED_TO）" value="RELATED_TO" />
            <el-option label="应用（APPLIES_TO）" value="APPLIES_TO" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标知识点">
          <el-select v-model="addEdgeForm.target" filterable style="width: 100%">
            <el-option v-for="n in editNodes" :key="n.id" :label="n.label" :value="n.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addEdgeVisible = false">取消</el-button>
        <el-button type="primary" :loading="addEdgeLoading" @click="submitAddEdge">确定</el-button>
      </template>
    </el-dialog>

    <!-- 关系详情/删除对话框 -->
    <el-dialog v-model="edgeDialogVisible" title="关系详情" width="440px">
      <template v-if="clickedEdge">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="源">{{ clickedEdge.sourceLabel || clickedEdge.source }}</el-descriptions-item>
          <el-descriptions-item label="关系">
            <el-tag size="small">{{ edgeLabel(clickedEdge) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="目标">{{ clickedEdge.targetLabel || clickedEdge.target }}</el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <el-button @click="edgeDialogVisible = false">关闭</el-button>
        <el-button type="danger" :loading="deleteEdgeLoading" @click="removeEdge">删除关系</el-button>
      </template>
    </el-dialog>

    <!-- 新建课程对话框 -->
    <el-dialog v-model="createCourseVisible" title="新建课程" width="440px">
      <el-form label-width="80px">
        <el-form-item label="课程名称" required>
          <el-input
            v-model="createCourseForm.name"
            placeholder="例如：数据结构"
            @keyup.enter="submitCreateCourse"
          />
        </el-form-item>
        <el-form-item label="课程简介">
          <el-input
            v-model="createCourseForm.description"
            type="textarea"
            :rows="3"
            placeholder="可选"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createCourseVisible = false">取消</el-button>
        <el-button type="primary" :loading="createCourseLoading" @click="submitCreateCourse">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, watch, computed, onMounted, onBeforeUnmount, nextTick, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  UploadFilled, Upload, View, EditPen, Refresh, FullScreen, Plus, Connection, ArrowRight, Search, SuccessFilled,
  Notebook, Document, Delete, DataAnalysis, Clock, User, UserFilled, Back, Files, FolderOpened,
  Reading, Download, Collection, Star,
} from '@element-plus/icons-vue'
import { api } from '../api'
import { fetchDocumentBuffer } from '../utils/documentContent'
import { useAppStore } from '../stores/app'
import PageHeader from '../components/PageHeader.vue'
import GraphCanvas from '../components/GraphCanvas.vue'
import NodeDetailDrawer from '../components/NodeDetailDrawer.vue'
import { edgeTypeLabel, nodeTypeLabel, nodeColor } from '../utils/graphStyle'

const store = useAppStore()
const route = useRoute()
const router = useRouter()
const TEACHER_TABS = ['courses', 'documents', 'preview', 'edit', 'monitor', 'questions']
const activeTab = ref(TEACHER_TABS.includes(route.query.tab) ? route.query.tab : 'courses')

// ===================== 当前上下文：课程 + 文档（教师端不搬 student learningContext） =====================
const currentCourseId = ref('')
const currentDocumentId = ref('')

const currentCourse = computed(() => store.courseById(currentCourseId.value) || null)
const currentCourseName = computed(() => {
  const c = currentCourse.value
  return c ? c.course_name : (currentCourseId.value ? `课程 #${currentCourseId.value}` : '')
})
const currentDocument = computed(() =>
  documents.value.find((d) => String(d.doc_id) === String(currentDocumentId.value)) || null
)
const currentDocumentName = computed(() => currentDocument.value?.file_name || '')

// ===================== 文档列表 / 上传 =====================
const documents = ref([])
const documentsLoading = ref(false)
const selectedFile = ref(null)
const uploading = ref(false)
const uploadResult = ref(null)
const uploadError = ref('')

function onFileChange(file) {
  selectedFile.value = file.raw
}
function onFileRemove() {
  selectedFile.value = null
}

async function loadDocuments() {
  if (!currentCourseId.value) {
    documents.value = []
    return
  }
  documentsLoading.value = true
  try {
    documents.value = await api.getDocuments(currentCourseId.value)
  } catch (e) {
    documents.value = []
    ElMessage.warning(`文档列表加载失败：${e.message}`)
  } finally {
    documentsLoading.value = false
  }
}

// ===================== 解析/抽取进度自动刷新（驱动下方进度条实时显示） =====================
let docPollTimer = null
const DOC_POLL_INTERVAL = 3000
const DOC_POLL_TIMEOUT = 10 * 60 * 1000
let docPollStartedAt = 0

// 存在待处理/处理中的文档时才需要轮询（图谱生成进度查看）
const hasInFlightDoc = computed(() =>
  documents.value.some(
    (d) =>
      ['UPLOADED', 'PARSING'].includes(d.parse_status) ||
      ['PENDING', 'EXTRACTING'].includes(d.extract_status),
  ),
)

function stopDocPolling() {
  if (docPollTimer) {
    clearInterval(docPollTimer)
    docPollTimer = null
  }
}

function startDocPolling() {
  if (docPollTimer) return
  docPollStartedAt = Date.now()
  docPollTimer = setInterval(() => {
    // 离开文档页、无进行中任务或超过 10 分钟兜底时自动停止
    if (
      activeTab.value !== 'documents' ||
      !currentCourseId.value ||
      !hasInFlightDoc.value ||
      Date.now() - docPollStartedAt > DOC_POLL_TIMEOUT
    ) {
      stopDocPolling()
      return
    }
    pollDocuments()
  }, DOC_POLL_INTERVAL)
}

// 静默刷新文档列表（不触发表格 loading 闪烁），状态进入终态时给出提示
async function pollDocuments() {
  if (!currentCourseId.value) return
  try {
    const prev = new Map(documents.value.map((d) => [d.doc_id, `${d.parse_status}|${d.extract_status}`]))
    const list = await api.getDocuments(currentCourseId.value)
    // 保留上传中的本地占位行（后端在解析完成前不会返回该记录，避免进度条被轮询刷掉）
    const placeholders = documents.value.filter((d) => d.is_placeholder)
    documents.value = [...placeholders, ...list]
    for (const d of list) {
      const key = `${d.parse_status}|${d.extract_status}`
      if (prev.get(d.doc_id) && prev.get(d.doc_id) !== key) {
        if (d.extract_status === 'COMPLETED') {
          ElMessage.success(`「${d.file_name}」知识图谱构建完成`)
        } else if (d.parse_status === 'FAILED' || d.extract_status === 'FAILED') {
          ElMessage.error(`「${d.file_name}」处理失败，请检查文件后重试`)
        }
      }
    }
  } catch {
    /* 轮询失败静默，下一轮自动重试 */
  }
}

// 出现进行中任务且正停留在文档页时自动开启轮询；任务全部结束后停止
watch(hasInFlightDoc, (v) => {
  if (v && activeTab.value === 'documents') startDocPolling()
  else if (!v) stopDocPolling()
})

// 切回文档页时若有进行中任务则继续轮询，切走即停止
watch(activeTab, (tab) => {
  if (tab === 'documents') {
    if (hasInFlightDoc.value) startDocPolling()
  } else {
    stopDocPolling()
  }
})

async function doUpload() {
  if (!selectedFile.value) return
  if (!currentCourseId.value) {
    ElMessage.warning('请先选择课程')
    return
  }
  uploading.value = true
  uploadResult.value = null
  uploadError.value = ''

  // 后端为同步处理（解析+抽取耗时较长，且文档记录在完成后才入库），
  // 请求返回前列表不会有任何变化。先插入一行本地占位行，让下方进度条立即显示。
  const placeholderId = `local-${Date.now()}`
  const placeholder = {
    doc_id: placeholderId,
    file_name: selectedFile.value.name,
    file_type: (selectedFile.value.name.split('.').pop() || '').toUpperCase(),
    file_size: selectedFile.value.size,
    parse_status: 'PARSING',
    extract_status: 'PENDING',
    entity_count: null,
    relation_count: null,
    created_at: new Date().toISOString(),
    local_stage: 'PARSING',
    is_placeholder: true,
  }
  documents.value = [placeholder, ...documents.value]

  // 处理期间把占位行进度从「解析中」推进到「抽取中」，让进度条持续走动
  const stageTimer = setTimeout(() => {
    documents.value = documents.value.map((d) =>
      d.doc_id === placeholderId ? { ...d, local_stage: 'EXTRACTING' } : d,
    )
  }, 8000)

  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)
    // 上传到当前课程：只传 course_id，不再传 course_name / 自动建课
    const result = await api.uploadCourse(formData, currentCourseId.value)
    uploadResult.value = result
    ElMessage.success('知识图谱构建完成')
    // 用真实文档替换占位行；若仍有处理中任务则由轮询继续驱动进度
    documents.value = documents.value.filter((d) => d.doc_id !== placeholderId)
    await loadDocuments()
    if (hasInFlightDoc.value) startDocPolling()
  } catch (e) {
    documents.value = documents.value.filter((d) => d.doc_id !== placeholderId)
    uploadError.value = e.message || '上传失败'
    ElMessage.error(`上传失败：${e.message}`)
  } finally {
    clearTimeout(stageTimer)
    uploading.value = false
  }
}

async function deleteDocument(doc) {
  try {
    await ElMessageBox.confirm(
      '删除该文档后，该文档对应的资源将被删除，是否继续？',
      '删除文档',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      }
    )
  } catch {
    return
  }
  try {
    await api.deleteDocument(doc.doc_id)
    ElMessage.success('文档已删除')
    await loadDocuments()
  } catch (e) {
    ElMessage.error(`删除失败：${e.message}`)
  }
}

// ===================== 预览 =====================
const previewGraphRef = ref(null)
const previewSearch = ref('')
const previewStats = ref(null)
const drawerVisible = ref(false)
const drawerNode = ref(null)

function refreshPreview() {
  previewGraphRef.value?.refresh()
}
function fitPreview() {
  previewGraphRef.value?.fitView()
}
function onNodeClick(node) {
  drawerNode.value = node
  drawerVisible.value = true
}
function afterNodeChanged() {
  drawerVisible.value = false
  refreshPreview()
}

// ===================== 编辑（三栏审核） =====================
const editGraphRef = ref(null)
const editNodes = ref([])
const nodeListSearch = ref('')
const selectedNode = ref(null)
const editForm = ref({ name: '', category: '概念', description: '' })
const savingNode = ref(false)
const deletingNode = ref(false)
const prereqs = ref([])
const prereqLoading = ref(false)
const prereqLoaded = ref(false)

const addNodeVisible = ref(false)
const addNodeForm = ref({ name: '', category: '概念', description: '' })
const addNodeLoading = ref(false)
const addEdgeVisible = ref(false)
const addEdgeForm = ref({ source: '', type: 'PRECEDES', target: '' })
const addEdgeLoading = ref(false)
const edgeDialogVisible = ref(false)
const clickedEdge = ref(null)
const deleteEdgeLoading = ref(false)

const filteredEditNodes = computed(() => {
  const kw = nodeListSearch.value.trim().toLowerCase()
  if (!kw) return editNodes.value
  return editNodes.value.filter(
    (n) =>
      (n.label || '').toLowerCase().includes(kw) ||
      (n.description || '').toLowerCase().includes(kw)
  )
})

async function loadEditNodes() {
  if (!currentCourseId.value) {
    editNodes.value = []
    return
  }
  try {
    const data = await api.getGraphV1(currentCourseId.value, currentDocumentId.value, { limit: 800 })
    editNodes.value = data.nodes || []
  } catch {
    editNodes.value = []
  }
}

// 选中节点后同步编辑表单
watch(selectedNode, (n) => {
  prereqs.value = []
  prereqLoaded.value = false
  if (n) {
    editForm.value = {
      name: n.label || '',
      category: n.properties?.category || '概念',
      description: n.description || '',
    }
  }
})

function selectNode(node) {
  selectedNode.value = node
  editGraphRef.value?.focusNode(node.id)
}

function onEditNodeClick(node) {
  selectedNode.value = node
}

function onEditEdgeClick(edge) {
  if (!edge) {
    edgeDialogVisible.value = false
    return
  }
  clickedEdge.value = {
    ...edge,
    sourceLabel: editNodes.value.find((n) => n.id === edge.source)?.label || edge.source,
    targetLabel: editNodes.value.find((n) => n.id === edge.target)?.label || edge.target,
  }
  edgeDialogVisible.value = true
}

async function saveNode() {
  if (!selectedNode.value) return
  if (!editForm.value.name.trim()) {
    ElMessage.warning('名称不能为空')
    return
  }
  savingNode.value = true
  try {
    await api.updateNode(currentCourseId.value, currentDocumentId.value, selectedNode.value.id, {
      name: editForm.value.name.trim(),
      category: editForm.value.category,
      description: editForm.value.description,
    })
    ElMessage.success('保存成功')
    selectedNode.value = null
    refreshEdit()
  } catch (e) {
    ElMessage.error(`保存失败：${e.message}`)
  } finally {
    savingNode.value = false
  }
}

async function deleteNode() {
  const node = selectedNode.value
  if (!node) return
  try {
    await ElMessageBox.confirm(
      `确定删除知识点「${node.label}」及其全部关系吗？`,
      '删除确认',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      }
    )
  } catch {
    return
  }
  deletingNode.value = true
  try {
    await api.deleteNode(currentCourseId.value, currentDocumentId.value, node.id)
    ElMessage.success('已删除')
    selectedNode.value = null
    refreshEdit()
  } catch (e) {
    ElMessage.error(`删除失败：${e.message}`)
  } finally {
    deletingNode.value = false
  }
}

async function loadPrereqs() {
  if (!selectedNode.value) return
  prereqLoading.value = true
  try {
    const res = await api.getPrerequisites(selectedNode.value.label, currentCourseId.value, currentDocumentId.value)
    prereqs.value = res.prerequisites || []
  } catch (e) {
    ElMessage.warning(`查询失败：${e.message}`)
  } finally {
    prereqLoading.value = false
    prereqLoaded.value = true
  }
}

function openAddNode() {
  if (!currentCourseId.value) {
    ElMessage.warning('请先选择文档')
    return
  }
  addNodeForm.value = { name: '', category: '概念', description: '' }
  addNodeVisible.value = true
}

async function submitAddNode() {
  if (!addNodeForm.value.name.trim()) {
    ElMessage.warning('名称不能为空')
    return
  }
  addNodeLoading.value = true
  try {
    await api.createNode(currentCourseId.value, currentDocumentId.value, {
      name: addNodeForm.value.name.trim(),
      category: addNodeForm.value.category,
      description: addNodeForm.value.description,
    })
    ElMessage.success('新增成功')
    addNodeVisible.value = false
    refreshEdit()
  } catch (e) {
    ElMessage.error(`新增失败：${e.message}`)
  } finally {
    addNodeLoading.value = false
  }
}

function openAddEdge() {
  if (!currentCourseId.value) {
    ElMessage.warning('请先选择文档')
    return
  }
  if (!editNodes.value.length) loadEditNodes()
  addEdgeForm.value = { source: '', type: 'PRECEDES', target: '' }
  addEdgeVisible.value = true
}

async function submitAddEdge() {
  const { source, type, target } = addEdgeForm.value
  if (!source || !target) {
    ElMessage.warning('请选择源和目标知识点')
    return
  }
  if (source === target) {
    ElMessage.warning('源和目标不能相同')
    return
  }
  addEdgeLoading.value = true
  try {
    await api.createEdge(currentCourseId.value, currentDocumentId.value, { source, type, target })
    ElMessage.success('关系创建成功')
    addEdgeVisible.value = false
    refreshEdit()
  } catch (e) {
    ElMessage.error(`创建失败：${e.message}`)
  } finally {
    addEdgeLoading.value = false
  }
}

async function removeEdge() {
  if (!clickedEdge.value) return
  try {
    await ElMessageBox.confirm('确定删除该关系吗？', '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }
  deleteEdgeLoading.value = true
  try {
    await api.deleteEdge(currentCourseId.value, currentDocumentId.value, clickedEdge.value.id)
    ElMessage.success('关系已删除')
    edgeDialogVisible.value = false
    refreshEdit()
  } catch (e) {
    ElMessage.error(`删除失败：${e.message}`)
  } finally {
    deleteEdgeLoading.value = false
  }
}

function refreshEdit() {
  editGraphRef.value?.refresh()
  loadEditNodes()
}

function edgeLabel(edge) {
  return edgeTypeLabel(edge?.type, edge?.label)
}

// ===================== 课程管理 =====================
const createCourseVisible = ref(false)
const createCourseForm = ref({ name: '', description: '' })
const createCourseLoading = ref(false)

function openCreateCourse() {
  createCourseForm.value = { name: '', description: '' }
  createCourseVisible.value = true
}

async function submitCreateCourse() {
  const name = createCourseForm.value.name.trim()
  if (!name) {
    ElMessage.warning('课程名称不能为空')
    return
  }
  createCourseLoading.value = true
  try {
    const created = await store.createCourse(name, { description: createCourseForm.value.description.trim() })
    createCourseVisible.value = false
    ElMessage.success(`课程「${name}」创建成功`)
    // 在文档页空状态新建课程后，直接进入该课程的文档管理，省去一次手动选课
    if (activeTab.value === 'documents' && created?.course_id != null) {
      router.replace({ path: '/teacher', query: { tab: 'documents', course_id: String(created.course_id) } })
    }
  } catch (e) {
    ElMessage.error(`创建失败：${e.message}`)
  } finally {
    createCourseLoading.value = false
  }
}

async function deleteCourse(c) {
  const id = String(c.course_id)
  try {
    await ElMessageBox.confirm(
      `确定删除课程「${c.course_name}」吗？将同时删除该课程下的文档、图谱数据及学习记录，此操作不可恢复。`,
      '删除课程',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      }
    )
  } catch {
    return
  }
  try {
    await store.deleteCourse(id)
    ElMessage.success('课程已删除')
    if (String(currentCourseId.value) === id) {
      currentCourseId.value = ''
      currentDocumentId.value = ''
    }
  } catch (e) {
    ElMessage.error(`删除失败：${e.message}`)
  }
}

// ===================== 教学监测 =====================
const monitorData = ref(null)
const monitorLoading = ref(false)
const monitorSearch = ref('')
const monitorProgressFilter = ref('')
const monitorPage = ref(1)
const monitorPageSize = ref(10)
const monitorSort = ref({ prop: 'progress', order: 'ascending' })
const monitorDetailVisible = ref(false)
const monitorDetailStudent = ref(null)
const progressDistRef = ref(null)
let progressDistChart = null

const progressBins = [
  { value: '0', label: '0–20%' },
  { value: '20', label: '20–40%' },
  { value: '40', label: '40–60%' },
  { value: '60', label: '60–80%' },
  { value: '80', label: '80–100%' },
]

const monitorKpis = computed(() => {
  const d = monitorData.value
  return [
    { label: '已开始学习人数', value: d?.student_count ?? 0, color: '#409eff' },
    { label: '平均学习进度', value: (d?.avg_progress ?? 0) + '%', color: '#e6a23c' },
    { label: '课程知识点总数', value: d?.total_knowledge ?? 0, color: '#67c23a' },
  ]
})

const filteredMonitorStudents = computed(() => {
  let list = monitorData.value?.students || []
  const kw = monitorSearch.value.trim().toLowerCase()
  if (kw) {
    list = list.filter(
      (s) =>
        (s.student_name || '').toLowerCase().includes(kw) ||
        (s.username || '').toLowerCase().includes(kw)
    )
  }
  if (monitorProgressFilter.value !== '') {
    const min = Number(monitorProgressFilter.value)
    list = list.filter((s) =>
      min === 80 ? s.progress >= 80 : s.progress >= min && s.progress < min + 20
    )
  }
  const { prop, order } = monitorSort.value
  const dir = order === 'descending' ? -1 : 1
  return [...list].sort((a, b) => {
    const av = prop === 'student_name' ? a.student_name : a[prop]
    const bv = prop === 'student_name' ? b.student_name : b[prop]
    if (av === bv) return 0
    return (av > bv ? 1 : -1) * dir
  })
})

const pagedMonitorStudents = computed(() => {
  const start = (monitorPage.value - 1) * monitorPageSize.value
  return filteredMonitorStudents.value.slice(start, start + monitorPageSize.value)
})

function onMonitorSortChange({ prop, order }) {
  monitorSort.value = { prop: prop || 'progress', order: order || 'ascending' }
}

async function loadMonitorData() {
  if (!currentCourseId.value) {
    monitorData.value = null
    return
  }
  monitorLoading.value = true
  try {
    monitorData.value = await api.getTeacherStudentsProgress(currentCourseId.value)
    if (activeTab.value === 'monitor') {
      await nextTick()
      renderProgressDist()
    }
  } catch (e) {
    ElMessage.warning(`班级学习情况加载失败：${e.message}`)
    monitorData.value = null
  } finally {
    monitorLoading.value = false
  }
}

function openMonitorStudentDetail(row) {
  monitorDetailStudent.value = row
  monitorDetailVisible.value = true
}

function goMonitorGraph() {
  if (!currentCourseId.value || !currentDocumentId.value) return
  router.push({
    path: '/teacher',
    query: { tab: 'preview', course_id: currentCourseId.value, document_id: currentDocumentId.value },
  })
}

function progressColor(p) {
  if (p >= 80) return '#67c23a'
  if (p >= 40) return '#e6a23c'
  return '#f56c6c'
}

function statusText(p) {
  if (p >= 100) return '已完成'
  if (p > 0) return '进行中'
  return '未开始'
}

function statusType(p) {
  if (p >= 100) return 'success'
  if (p > 0) return 'primary'
  return 'info'
}

function renderProgressDist() {
  if (!progressDistRef.value) {
    progressDistChart?.dispose()
    progressDistChart = null
    return
  }
  if (progressDistChart && progressDistChart.getDom() !== progressDistRef.value) {
    progressDistChart.dispose()
    progressDistChart = null
  }
  if (!progressDistChart) progressDistChart = echarts.init(progressDistRef.value)
  const students = monitorData.value?.students || []
  const labels = progressBins.map((b) => b.label)
  const counts = progressBins.map((b) => {
    const min = Number(b.value)
    return students.filter((s) =>
      min === 80 ? s.progress >= 80 : s.progress >= min && s.progress < min + 20
    ).length
  })
  const option = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '4%', bottom: '8%', top: '10%', containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      name: '学习进度',
      nameTextStyle: { color: '#909399', fontSize: 11 },
      axisLabel: { color: '#606266', fontSize: 11 },
      axisLine: { lineStyle: { color: '#dcdfe6' } },
    },
    yAxis: {
      type: 'value',
      name: '学生数',
      nameTextStyle: { color: '#909399', fontSize: 11 },
      minInterval: 1,
      axisLabel: { color: '#909399' },
      splitLine: { lineStyle: { color: '#f0f0f0', type: 'dashed' } },
    },
    series: [{
      type: 'bar',
      barWidth: '50%',
      itemStyle: {
        borderRadius: [6, 6, 0, 0],
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: '#409eff' },
          { offset: 1, color: '#79bbff' },
        ]),
      },
      data: counts,
    }],
  }
  if (counts.every((v) => v === 0)) option.graphic = {
    type: 'text', left: 'center', top: 'middle',
    style: { text: '暂无数据', fill: '#909399', fontSize: 14 },
  }
  progressDistChart.setOption(option)
}

function handleMonitorResize() {
  progressDistChart?.resize()
}

// ===================== 导航 =====================
function goCourses() {
  router.push({ path: '/teacher', query: { tab: 'courses' } })
}
function manageDocuments(course) {
  // 入参是课程卡片对象 c（非 id）：必须取 course.course_id，否则 String(对象) 会得到 "[object Object]"
  router.push({ path: '/teacher', query: { tab: 'documents', course_id: String(course.course_id) } })
}
function backToCourses() {
  goCourses()
}
function backToDocuments() {
  if (currentCourseId.value) {
    router.push({ path: '/teacher', query: { tab: 'documents', course_id: currentCourseId.value } })
  } else {
    goCourses()
  }
}
function viewDocumentGraph(doc) {
  router.push({
    path: '/teacher',
    query: { tab: 'preview', course_id: String(doc.course_id), document_id: String(doc.doc_id) },
  })
}
/** 在线阅读：进入独立的文档阅读器整页（from=teacher 决定返回时回到课程管理） */
function readDocument(doc) {
  router.push({
    name: 'reader',
    params: { docId: String(doc.doc_id) },
    query: { course_id: String(doc.course_id), from: 'teacher' },
  })
}
/** 下载原文件：内容接口需要 JWT，地址栏直达会 401，因此取回字节后用 Blob 触发下载 */
async function downloadDocument(doc) {
  try {
    const buffer = await fetchDocumentBuffer(doc.doc_id)
    const url = URL.createObjectURL(new Blob([buffer]))
    const a = document.createElement('a')
    a.href = url
    a.download = doc.file_name || `document-${doc.doc_id}`
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 10000)
  } catch (e) {
    ElMessage.error(`下载失败：${e.message}`)
  }
}
function editDocumentGraph(doc) {
  router.push({
    path: '/teacher',
    query: { tab: 'edit', course_id: String(doc.course_id), document_id: String(doc.doc_id) },
  })
}
function monitorDocument(doc) {
  router.push({
    path: '/teacher',
    query: { tab: 'monitor', course_id: String(doc.course_id), document_id: String(doc.doc_id) },
  })
}

// 文档页内选择/切换/清空课程：同步路由，由路由守卫统一落地上下文并触发文档加载
function syncDocumentsRoute(id) {
  router
    .replace({
      path: '/teacher',
      query: { tab: 'documents', course_id: id ? String(id) : undefined },
    })
    .catch(() => {})
}

// 图谱预览/编辑/监测页内选择课程：清空已选文档并重置各页内部状态，避免残留上一个上下文的选中项
function onContextCourseChange(id) {
  currentDocumentId.value = ''
  drawerVisible.value = false
  drawerNode.value = null
  selectedNode.value = null
  prereqs.value = []
  prereqLoaded.value = false
  router
    .replace({
      path: '/teacher',
      query: { tab: activeTab.value, course_id: id || undefined },
    })
    .catch(() => {})
  // 监测数据是课程级：选好课程即可加载；题库为课程级；图谱类页面等选好文档后由组件挂载时自加载
  if (activeTab.value === 'monitor' && id) loadMonitorData()
  if (activeTab.value === 'questions' && id) {
    questionDocFilter.value = ''
    loadQuestionsTab()
  }
}

// 图谱预览/编辑页内选择文档：重置内部状态并同步路由；编辑页需主动拉取知识点列表
function onContextDocChange(id) {
  drawerVisible.value = false
  drawerNode.value = null
  selectedNode.value = null
  prereqs.value = []
  prereqLoaded.value = false
  router
    .replace({
      path: '/teacher',
      query: { tab: activeTab.value, course_id: currentCourseId.value || undefined, document_id: id || undefined },
    })
    .catch(() => {})
  if (activeTab.value === 'edit' && id) loadEditNodes()
}

// 用户直接点击 Tab 头：同步路由（缺失参数的守卫统一由 route watcher 处理）
function onTabChange(name) {
  if (name === 'courses') {
    router.replace({ path: '/teacher', query: { tab: 'courses' } })
  } else if (name === 'documents') {
    router.replace({
      path: '/teacher',
      query: { tab: 'documents', course_id: currentCourseId.value || undefined },
    })
  } else {
    router.replace({
      path: '/teacher',
      query: {
        tab: name,
        course_id: currentCourseId.value || undefined,
        document_id: currentDocumentId.value || undefined,
      },
    })
  }
}

// ===================== 路由同步 + 守卫 =====================
// 深链 /teacher?tab=xxx&course_id=yyy&document_id=zzz：同步上下文并守卫缺失参数
watch(
  () => [route.query.tab, route.query.course_id, route.query.document_id],
  ([tab, cid, did]) => {
    if (!tab) {
      activeTab.value = 'courses'
      currentCourseId.value = ''
      currentDocumentId.value = ''
      return
    }
    if (!TEACHER_TABS.includes(tab)) {
      activeTab.value = 'courses'
      return
    }
    if (['preview', 'edit', 'monitor'].includes(tab)) {
      // 缺少课程/文档时停留在当前页，由页内级联选择器引导，不再弹窗强制跳回
      currentCourseId.value = cid ? String(cid) : ''
      currentDocumentId.value = did ? String(did) : ''
    } else if (tab === 'documents') {
      // 未指定课程时停留在文档页，由页内课程选择器引导，不再弹窗强制跳回课程列表
      currentCourseId.value = cid ? String(cid) : ''
      currentDocumentId.value = ''
    } else {
      currentCourseId.value = ''
      currentDocumentId.value = ''
    }
    activeTab.value = tab
  },
  { immediate: true }
)

// 课程上下文变化 → 加载文档列表
watch(currentCourseId, (cid) => {
  if (cid) loadDocuments()
  else documents.value = []
})

// ===================== 题库管理（Scope A：单选/多选/判断；答案与解析仅教师可见） =====================
const QUESTION_TYPES = [
  { value: 'SINGLE', label: '单选题' },
  { value: 'MULTI', label: '多选题' },
  { value: 'JUDGE', label: '判断题' },
]
const questionTypeLabel = (t) => QUESTION_TYPES.find((x) => x.value === t)?.label || t || ''

const questionList = ref([])
const questionsLoading = ref(false)
const questionTotal = ref(0)
const questionPage = ref(1)
const questionPageSize = ref(10)
const questionStats = ref(null)
const questionDocFilter = ref('')
const questionFilters = reactive({ q_type: '', keyword: '', is_active: '' })

const questionFormVisible = ref(false)
const questionFormLoading = ref(false)
const questionEditingId = ref(null)
const questionKpOptions = ref([])
const questionForm = reactive({
  q_type: 'SINGLE', stem: '', analysis: '', difficulty: 3, kp_id: '', document_id: '',
  options: [], singleAnswer: 'A', multiAnswer: [], judgeAnswer: 'true',
})

const questionFavVisible = ref(false)
const questionFavLoading = ref(false)
const questionFavs = ref([])

/** 默认选项 A-D（教师可在表单内增删，最多 8 个） */
function emptyOptions() {
  return ['A', 'B', 'C', 'D'].map((k) => ({ key: k, text: '' }))
}

/** 关联知识点下拉数据：来自当前文档图谱（图谱不可用时降级为空，不影响新增课程通用题） */
async function loadQuestionKpOptions() {
  if (!currentCourseId.value || !currentDocumentId.value) {
    questionKpOptions.value = []
    return
  }
  try {
    const g = await api.getGraphV1(currentCourseId.value, currentDocumentId.value, { limit: 500 })
    questionKpOptions.value = (g.nodes || []).map((n) => ({ id: n.id, label: n.label }))
  } catch {
    questionKpOptions.value = []
  }
}

function kpNameById(id) {
  return questionKpOptions.value.find((n) => n.id === id)?.label
}

async function loadQuestions() {
  if (!currentCourseId.value) {
    questionList.value = []
    questionTotal.value = 0
    return
  }
  questionsLoading.value = true
  try {
    const data = await api.listQuestions({
      course_id: currentCourseId.value,
      document_id: questionDocFilter.value || undefined,
      q_type: questionFilters.q_type || undefined,
      keyword: questionFilters.keyword || undefined,
      is_active: questionFilters.is_active === '' ? undefined : questionFilters.is_active === '1',
      page: questionPage.value,
      page_size: questionPageSize.value,
    })
    questionList.value = data.items || []
    questionTotal.value = data.total || 0
  } catch (e) {
    questionList.value = []
    questionTotal.value = 0
    ElMessage.warning(`题库加载失败：${e.message}`)
  } finally {
    questionsLoading.value = false
  }
}

async function loadQuestionStats() {
  if (!currentCourseId.value) {
    questionStats.value = null
    return
  }
  try {
    questionStats.value = await api.getQuestionStats(currentCourseId.value)
  } catch {
    questionStats.value = null
  }
}

/** 进入题库 Tab / 切换筛选时统一刷新（列表 + 总览 + 知识点下拉） */
async function loadQuestionsTab() {
  questionPage.value = 1
  // 题库的「所属文档」下拉与知识点下拉都依赖文档列表；用户可能从未进过文档 Tab
  if (currentCourseId.value && !documents.value.length) loadDocuments()
  loadQuestionKpOptions()
  await Promise.all([loadQuestions(), loadQuestionStats()])
}

/** 打开新增（row=null）或编辑表单：回填题型/选项/答案/文档/知识点 */
function openQuestionForm(row) {
  questionEditingId.value = row ? row.question_id : null
  questionForm.q_type = row ? row.q_type : 'SINGLE'
  questionForm.stem = row ? row.stem : ''
  questionForm.analysis = row ? (row.analysis || '') : ''
  questionForm.difficulty = row ? (row.difficulty || 3) : 3
  questionForm.kp_id = row ? (row.kp_id || '') : ''
  questionForm.document_id = row
    ? (row.document_id ? String(row.document_id) : '')
    : (currentDocumentId.value || '')

  const isJudge = row && row.q_type === 'JUDGE'
  questionForm.options = isJudge || !row
    ? (row ? [] : emptyOptions())
    : (Array.isArray(row.options) ? row.options.map((o) => ({ key: String(o.key), text: o.text })) : emptyOptions())

  const ans = row ? row.answer : null
  questionForm.singleAnswer = row && row.q_type === 'SINGLE' ? String(ans) : (questionForm.options[0]?.key || 'A')
  questionForm.multiAnswer = row && row.q_type === 'MULTI' && Array.isArray(ans)
    ? ans.map((x) => String(x).toUpperCase())
    : []
  questionForm.judgeAnswer = row && row.q_type === 'JUDGE'
    ? (String(ans) === 'false' ? 'false' : 'true')
    : 'true'

  if (!questionForm.options.length && !isJudge) questionForm.options = emptyOptions()
  questionFormVisible.value = true
  if (!questionKpOptions.value.length) loadQuestionKpOptions()
}

/** 添加选项：取 A-H 中第一个未使用的编号（不重排已有编号，避免答案键错位） */
function addQuestionOption() {
  const used = new Set(questionForm.options.map((o) => o.key))
  const next = 'ABCDEFGH'.split('').find((k) => !used.has(k))
  if (next) questionForm.options.push({ key: next, text: '' })
}

/** 删除选项：同步剔除该键在答案中的引用 */
function removeQuestionOption(idx) {
  if (questionForm.options.length <= 2) return
  const [removed] = questionForm.options.splice(idx, 1)
  questionForm.multiAnswer = questionForm.multiAnswer.filter((k) => k !== removed.key)
  if (questionForm.singleAnswer === removed.key) {
    questionForm.singleAnswer = questionForm.options[0]?.key || ''
  }
}

/** 组装提交体：空选项被过滤；document_id 留空即「课程通用题」 */
function buildQuestionPayload() {
  const base = {
    q_type: questionForm.q_type,
    stem: questionForm.stem,
    analysis: questionForm.analysis || null,
    difficulty: questionForm.difficulty,
    kp_id: questionForm.kp_id || null,
    document_id: questionForm.document_id || null,
  }
  if (questionForm.q_type === 'JUDGE') {
    return { ...base, options: [], answer: questionForm.judgeAnswer }
  }
  const options = questionForm.options
    .filter((o) => (o.text || '').trim())
    .map((o) => ({ key: o.key, text: o.text.trim() }))
  return {
    ...base,
    options,
    answer: questionForm.q_type === 'MULTI' ? questionForm.multiAnswer : questionForm.singleAnswer,
  }
}

async function submitQuestionForm() {
  const payload = buildQuestionPayload()
  if (!payload.stem || !payload.stem.trim()) {
    ElMessage.warning('请填写题干')
    return
  }
  if (payload.q_type !== 'JUDGE' && payload.options.length < 2) {
    ElMessage.warning('选择题至少需要 2 个非空选项')
    return
  }
  if (payload.q_type === 'MULTI' && !payload.answer.length) {
    ElMessage.warning('请勾选多选题的正确答案')
    return
  }
  questionFormLoading.value = true
  try {
    if (questionEditingId.value) {
      await api.updateQuestion(questionEditingId.value, payload)
      ElMessage.success('题目已更新')
    } else {
      await api.createQuestion({ course_id: currentCourseId.value, ...payload })
      ElMessage.success('题目已新增')
    }
    questionFormVisible.value = false
    await loadQuestionsTab()
  } catch (e) {
    ElMessage.error(`保存失败：${e.message}`)
  } finally {
    questionFormLoading.value = false
  }
}

async function toggleQuestionActive(row) {
  try {
    await api.setQuestionActive(row.question_id, !row.is_active)
    ElMessage.success(row.is_active ? '题目已停用（移出出题池）' : '题目已启用')
    await loadQuestionsTab()
  } catch (e) {
    ElMessage.error(`操作失败：${e.message}`)
  }
}

async function removeQuestion(row) {
  try {
    await ElMessageBox.confirm(
      '删除后学生将无法再做该题；若已有作答记录，系统会自动改为「停用」以保护答题数据。是否继续？',
      '删除题目',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    const data = await api.deleteQuestion(row.question_id)
    ElMessage.success(data?.soft_deleted ? '该题已有作答记录，已停用（未物理删除）' : '题目已删除')
    await loadQuestionsTab()
  } catch (e) {
    ElMessage.error(`删除失败：${e.message}`)
  }
}

/** 题目收藏情况：哪些学生收藏了本课程的题 */
async function openQuestionFavorites() {
  questionFavVisible.value = true
  questionFavLoading.value = true
  try {
    const data = await api.getQuestionFavorites(currentCourseId.value)
    questionFavs.value = data.items || []
  } catch (e) {
    questionFavs.value = []
    ElMessage.warning(`收藏情况加载失败：${e.message}`)
  } finally {
    questionFavLoading.value = false
  }
}

// Tab 变化 → 按需加载数据
watch(activeTab, (tab) => {
  if (tab === 'courses') store.fetchCourses(true).catch(() => {})
  if (tab === 'documents' && currentCourseId.value) loadDocuments()
  if (tab === 'preview') {
    drawerVisible.value = false
    drawerNode.value = null
  }
  if (tab === 'edit') {
    selectedNode.value = null
    prereqs.value = []
    prereqLoaded.value = false
    if (currentCourseId.value) loadEditNodes()
  }
  if (tab === 'monitor' && currentCourseId.value) loadMonitorData()
  if (tab === 'questions' && currentCourseId.value) loadQuestionsTab()
})

onMounted(() => {
  store.fetchCourses(true).catch(() => {})
  window.addEventListener('resize', handleMonitorResize)
  // 深链直达时 activeTab 初始即等于目标 tab，activeTab watcher 不会触发，需在此补一次加载
  if (activeTab.value === 'documents' && currentCourseId.value) loadDocuments()
  if (activeTab.value === 'edit' && currentCourseId.value) loadEditNodes()
  if (activeTab.value === 'monitor' && currentCourseId.value) loadMonitorData()
  if (activeTab.value === 'questions' && currentCourseId.value) loadQuestionsTab()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleMonitorResize)
  progressDistChart?.dispose()
  stopDocPolling()
})

// ===================== 工具函数 =====================
function fmtTime(t) {
  return t ? String(t).slice(0, 16) : '—'
}
function fmtSize(bytes) {
  if (bytes == null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
function parseStatusType(s) {
  return s === 'PARSED' ? 'success' : s === 'FAILED' ? 'danger' : s === 'PARSING' ? 'warning' : 'info'
}
function parseStatusText(s) {
  return { UPLOADED: '待解析', PARSING: '解析中', PARSED: '已解析', FAILED: '解析失败' }[s] || s
}
function extractStatusType(s) {
  return s === 'COMPLETED' ? 'success' : s === 'FAILED' ? 'danger' : s === 'EXTRACTING' ? 'warning' : 'info'
}
function extractStatusText(s) {
  return { PENDING: '待抽取', EXTRACTING: '抽取中', COMPLETED: '已完成', FAILED: '抽取失败' }[s] || s
}

// 图谱生成进度百分比：排队 5% → 解析中 30% → 已解析 50% → 抽取中 75% → 完成 100%
function docProgress(doc) {
  if (doc.parse_status === 'FAILED') return 30
  if (doc.extract_status === 'FAILED') return 75
  if (doc.extract_status === 'COMPLETED') return 100
  // 上传请求挂起期间的本地占位行：按阶段推进进度
  if (doc.local_stage === 'UPLOADING') return 15
  if (doc.local_stage === 'PARSING') return 30
  if (doc.local_stage === 'EXTRACTING') return 75
  if (doc.extract_status === 'EXTRACTING') return 75
  if (doc.parse_status === 'PARSED') return 50
  if (doc.parse_status === 'PARSING') return 30
  return 5
}

function docProgressStatus(doc) {
  if (doc.parse_status === 'FAILED' || doc.extract_status === 'FAILED') return 'exception'
  if (doc.extract_status === 'COMPLETED') return 'success'
  return ''
}

// 是否处于处理中（进度条条纹流动动画依据）
function isDocInFlight(doc) {
  return (
    ['UPLOADING', 'PARSING', 'EXTRACTING'].includes(doc.local_stage) ||
    ['UPLOADED', 'PARSING'].includes(doc.parse_status) ||
    ['PENDING', 'EXTRACTING'].includes(doc.extract_status)
  )
}
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.stats-text {
  color: var(--color-text-secondary);
  font-size: var(--font-size-label);
}
.graph-card {
  height: 620px;
}
.graph-card :deep(.el-card__body) {
  height: 100%;
  padding: 12px;
}

/* ===== 上下文栏（课程/文档） ===== */
.context-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  margin-bottom: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--color-bg-soft);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
}
.context-title {
  font-size: var(--font-size-section);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

/* ===== 文档列表 / 上传 ===== */
.upload-card {
  margin-bottom: var(--space-3);
}
.upload-result-alert {
  margin-top: var(--space-3);
}
.doc-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.doc-table :deep(.el-table__header th) {
  background: var(--color-bg-soft);
  color: var(--color-text-regular);
  font-weight: var(--font-weight-semibold);
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.result-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}
.result-card {
  border-left: 4px solid #67c23a;
}
.uploading-alert {
  margin-top: 16px;
}

/* ===== 三栏审核工作区 ===== */
.workspace {
  margin-top: 0;
}
.panel-card {
  height: 640px;
  display: flex;
  flex-direction: column;
}
.panel-card :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 12px;
}
.panel-header {
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-body);
}
.panel-scroll {
  flex: 1;
  overflow-y: auto;
  margin-top: 10px;
}
.list-search {
  margin-bottom: 8px;
}
.node-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}
.node-item:hover {
  background: #f5f9ff;
}
.node-item.active {
  background: #ecf5ff;
}
.node-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.node-item-label {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 图谱面板：body 铺满 */
.graph-panel :deep(.el-card__body) {
  padding: 0;
}

/* 详情面板 */
.detail-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.detail-name {
  font-size: 16px;
  font-weight: 700;
  color: #303133;
}
.detail-actions {
  display: flex;
  gap: 12px;
  margin-top: 12px;
}
.prereq-list {
  list-style: none;
  padding: 0;
  margin: 12px 0 0;
}
.prereq-list li {
  padding: 8px 0;
  border-bottom: 1px dashed #e4e7ed;
}
.prereq-name {
  font-weight: 600;
  margin-left: 8px;
}
.prereq-desc {
  color: #909399;
  font-size: 12px;
  margin-top: 4px;
}

/* ===== 课程管理 ===== */
.course-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  flex-wrap: wrap;
  margin-bottom: var(--space-3);
}
.course-grid-wrap {
  min-height: 200px;
}
.course-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--space-4);
}
.course-card {
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  box-shadow: var(--shadow-card);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  transition: transform 0.2s, box-shadow 0.2s;
}
.course-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-hover);
}
.course-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.course-name {
  font-size: var(--font-size-section);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.course-desc {
  font-size: var(--font-size-caption);
  color: var(--color-text-secondary);
  line-height: 1.5;
  min-height: 36px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.course-stats {
  display: flex;
  gap: var(--space-2);
}
.course-stat {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: var(--space-2);
  border-radius: var(--radius-md);
  background: var(--color-bg-soft);
  border: 1px solid var(--color-border-light);
}
.stat-num {
  font-size: 16px;
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  font-family: var(--font-family-number);
}
.stat-label {
  font-size: 11px;
  color: var(--color-text-secondary);
}
.course-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  flex-wrap: wrap;
  border-top: 1px solid var(--color-border-light);
  padding-top: 10px;
}
.course-updated {
  font-size: var(--font-size-caption);
  color: var(--color-text-muted);
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}
.course-actions {
  display: flex;
  gap: var(--space-1);
}

/* ===== 教学监测 ===== */
.chart-title-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
}
.class-note {
  margin-left: auto;
  font-size: 12px;
  font-weight: 400;
  color: #c0c4cc;
}
.class-summary {
  display: flex;
  gap: 16px;
  margin-bottom: 8px;
}
.class-kpi {
  flex: 1;
  padding: 14px 16px;
  border-radius: 10px;
  background: #fafbfc;
  border: 1px solid #f0f2f5;
}
.class-kpi-value {
  font-size: 24px;
  font-weight: 700;
  font-family: 'DIN Alternate', 'Helvetica Neue', sans-serif;
}
.class-kpi-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.dist-chart {
  height: 220px;
}
.table-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.student-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}
.student-username {
  font-size: 12px;
  color: #909399;
  font-weight: 400;
}
.current-name {
  color: #409eff;
}
.cell-empty {
  color: #c0c4cc;
}
/* 题库表单：选项输入 + 删除按钮同一行（右侧按钮不挤压输入框） */
.opt-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.rec-tag {
  margin: 2px 4px 2px 0;
}
.table-pagination {
  margin-top: 12px;
  justify-content: flex-end;
}
.detail-username {
  font-size: 12px;
  color: #909399;
  margin-left: 6px;
}
.rec-list {
  list-style: none;
  padding: 0;
  margin: 12px 0 0;
}
.rec-list li {
  padding: 8px 0;
  border-bottom: 1px dashed #e4e7ed;
}
.rec-name {
  font-weight: 600;
  margin-left: 8px;
}
.rec-reason {
  color: #909399;
  font-size: 12px;
  margin-top: 4px;
}
.drawer-actions {
  margin-top: 16px;
}

/* ===== 文档页课程选择引导 ===== */
.doc-course-pick {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  flex-wrap: wrap;
}
.doc-course-pick-tip {
  margin: 12px 0 0;
  font-size: 12px;
  color: #909399;
}
.course-switcher {
  margin-left: auto;
  width: 200px;
}

/* ===== 响应式：三栏工作区窄屏堆叠 ===== */
@media (max-width: 768px) {
  .workspace :deep(.el-col) {
    margin-bottom: var(--space-3);
  }
}
</style>
