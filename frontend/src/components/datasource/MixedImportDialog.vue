<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

// 使用相对路径：开发模式下由 Vite dev server 的 proxy 在服务器本机代转到后端，
// 打包后前后端同源。硬编码主机名会导致局域网其他电脑请求 http://<服务器IP>:8000 而超时。
const API_BASE = import.meta.env.VITE_API_BASE || "";

const emit = defineEmits(["close", "imported"]);

// 记忆上次成功读取的本地项目文件夹路径
const STORAGE_KEY = "kb.mixed.projectPath";

function readSavedPath() {
  try {
    return localStorage.getItem(STORAGE_KEY) || "";
  } catch (e) {
    return "";
  }
}

// ---------- 状态 ----------
const projectPath = ref(readSavedPath());
const pathInput = ref(null);
const projects = ref([]); // [{ dir, name, labels, relation_types, file_count, file_names }]
const selectedDir = ref("");
const loading = ref(false); // 正在扫描本地目录
const importing = ref(false); // 正在导入
const listLoaded = ref(false); // 是否已成功读取过一次（区分“未读取”和“空列表”）
const errorText = ref("");

// 成功读取项目列表时对应的规范化路径。
// 只有“当前路径 === loadedPath”才允许导入，避免用户改动路径后
// 仍用上一个目录扫描出的项目发起导入（目录已不是列表来源）。
const loadedPath = ref("");

const selectedProject = computed(
  () => projects.value.find((p) => p.dir === selectedDir.value) || null
);
const canImport = computed(
  () =>
    !loading.value &&
    !importing.value &&
    !!selectedProject.value &&
    !!loadedPath.value &&
    normalizePath(projectPath.value) === loadedPath.value
);

// ---------- 请求取消与竞态控制 ----------
const IMPORT_TIMEOUT_MS = 90000;

// 请求序号：任何一次新读取都会自增，过期响应据此丢弃
let listSeq = 0;
let listAbort = null;
let importAbort = null;
let importTimer = null;

// 路径规范化：仅用于“列表是否仍对应当前输入”的比较。
// 统一分隔符与末尾斜杠，避免 C:\a\b\ 与 C:/a/b 被判为不同路径而误清列表。
function normalizePath(raw) {
  let p = String(raw || "").trim().replace(/\\/g, "/");
  if (!p) return "";
  const isUnc = p.startsWith("//"); // 保留 \\server\share 的 UNC 前缀
  p = p.replace(/\/{2,}/g, "/");
  if (isUnc) p = "/" + p;
  p = p.replace(/\/+$/, "");
  if (/^[A-Za-z]:$/.test(p)) p += "/"; // 盘符根目录 C: → C:/
  return p;
}

function abortListRequest() {
  if (listAbort) {
    listAbort.abort();
    listAbort = null;
  }
}

function abortImportRequest() {
  // 先置空再 abort：catch 通过 importAbort === controller 判断
  // 当前导入是否仍然有效，卸载场景下不再写回组件状态。
  const controller = importAbort;
  importAbort = null;
  if (importTimer) {
    clearTimeout(importTimer);
    importTimer = null;
  }
  if (controller) controller.abort();
}

// 路径变更即视为旧列表失效：立即清空、置 loading 为 false 并中止进行中的扫描。
// loading.value 一并复位，保证即使扫描请求尚未返回，界面也已回到可重试状态。
function invalidateProjectList() {
  listSeq++;
  abortListRequest();
  loading.value = false;
  projects.value = [];
  selectedDir.value = "";
  listLoaded.value = false;
  loadedPath.value = "";
  errorText.value = "";
}

// 同步 flush：路径一变更就立即清理，不会出现“修改路径后旧请求回写列表”的窗口期
watch(
  projectPath,
  (value) => {
    // 仅末尾斜杠 / 分隔符风格差异不改变目录身份，保留已读取的列表与选择
    if (
      listLoaded.value &&
      loadedPath.value &&
      normalizePath(value) === loadedPath.value
    ) {
      return;
    }
    invalidateProjectList();
  },
  { flush: "sync" }
);

function persistPath(path) {
  try {
    localStorage.setItem(STORAGE_KEY, path);
  } catch (e) {
    // localStorage 不可用时静默降级，不影响导入
  }
}

// 后端错误以 {"detail": "..."} 返回；detail 可能是字符串或校验错误对象
async function extractError(resp, fallback) {
  try {
    const data = await resp.json();
    const detail = data && (data.detail || data.message);
    if (typeof detail === "string" && detail.trim()) return detail;
    if (detail) return JSON.stringify(detail);
  } catch (e) {
    // 响应体不是 JSON 时回退到通用文案
  }
  return fallback;
}

function fileCount(project) {
  return Number.isFinite(project.file_count) ? project.file_count : 0;
}

function labelCount(project) {
  return Array.isArray(project.labels) ? project.labels.length : 0;
}

function relationCount(project) {
  return Array.isArray(project.relation_types) ? project.relation_types.length : 0;
}

// ---------- 读取本地项目文件夹 ----------
async function readProjects() {
  if (loading.value || importing.value) return;
  const path = projectPath.value.trim();
  if (!path) {
    errorText.value = "请输入混合标注项目文件夹路径";
    return;
  }

  const seq = ++listSeq;
  abortListRequest();
  const controller = new AbortController();
  listAbort = controller;

  loading.value = true;
  errorText.value = "";
  projects.value = [];
  selectedDir.value = "";
  listLoaded.value = false;
  loadedPath.value = "";

  try {
    const resp = await fetch(`${API_BASE}/api/mixed/scan-local`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
      signal: controller.signal,
    });
    if (seq !== listSeq) return; // 已被新请求 / 路径变更取代
    if (!resp.ok) {
      throw new Error(await extractError(resp, `读取项目失败（HTTP ${resp.status}）`));
    }
    const data = await resp.json();
    if (seq !== listSeq) return; // 过期响应直接丢弃，不写回状态
    const list = Array.isArray(data.projects)
      ? data.projects.filter((p) => p && typeof p === "object" && p.dir)
      : [];
    projects.value = list;
    listLoaded.value = true;
    // 列表对应的就是本次提交的路径（后端可能规范化路径，比较以输入为准）
    loadedPath.value = normalizePath(path);
    // 仅一个项目时自动选中；多个项目时清空选择，交由用户点选
    selectedDir.value = list.length === 1 ? list[0].dir : "";
    persistPath(path);
  } catch (err) {
    // 被新请求 / 路径变更 / 卸载中断的响应不参与状态更新
    if (seq !== listSeq || controller.signal.aborted) return;
    errorText.value = err.message || "读取项目失败，请检查项目文件夹路径是否正确";
    listLoaded.value = false;
    loadedPath.value = "";
  } finally {
    if (listAbort === controller) listAbort = null;
    if (seq === listSeq) loading.value = false;
  }
}

// ---------- 导入并打开 ----------
async function confirmImport() {
  const project = selectedProject.value;
  if (!project || importing.value) return;

  // 提交前再校验一次：列表必须仍对应当前路径
  if (!loadedPath.value || normalizePath(projectPath.value) !== loadedPath.value) {
    errorText.value = "项目文件夹路径已变更，请重新读取项目";
    return;
  }

  importing.value = true;
  errorText.value = "";

  const controller = new AbortController();
  importAbort = controller;
  importTimer = setTimeout(() => {
    if (importAbort === controller) {
      // 超时中断请求；catch 中恢复可关闭 / 可重试状态
      controller.abort("timeout");
    }
  }, IMPORT_TIMEOUT_MS);

  try {
    const resp = await fetch(`${API_BASE}/api/mixed/import-local`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dir: project.dir,
        project_name: project.name,
      }),
      signal: controller.signal,
    });
    if (!resp.ok) {
      throw new Error(await extractError(resp, `导入失败（HTTP ${resp.status}）`));
    }
    const data = await resp.json();
    persistPath(projectPath.value.trim());
    // 生命周期交由父组件：父组件收到 imported 后关闭本弹窗
    emit("imported", data);
  } catch (err) {
    if (controller.signal.aborted) {
      // 组件已卸载时 importAbort 被置空，不再把状态写回已销毁的组件
      if (importAbort === controller) {
        errorText.value = "导入超时，请检查项目文件夹后重试";
        importing.value = false;
      }
      return;
    }
    errorText.value = err.message || "导入失败，请稍后重试";
    importing.value = false;
  } finally {
    if (importTimer) {
      clearTimeout(importTimer);
      importTimer = null;
    }
    if (importAbort === controller) importAbort = null;
  }
}

// ---------- 关闭 ----------
function requestClose() {
  if (importing.value) return; // 导入中不可关闭
  emit("close");
}

function onKeydown(event) {
  if (event.key !== "Escape") return;
  if (importing.value) return;
  emit("close");
}

onMounted(() => {
  window.addEventListener("keydown", onKeydown);
  nextTick(() => pathInput.value && pathInput.value.focus());
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKeydown);
  // 卸载时中断进行中的读取 / 导入，避免请求悬挂与状态写回
  abortListRequest();
  abortImportRequest();
});
</script>

<template>
  <div class="mi-overlay" @click.self="requestClose">
    <div
      class="mi-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="mi-dialog-title"
      @click.stop
    >
      <!-- 头部 -->
      <div class="mi-header">
        <div class="mi-header-left">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
            <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
          </svg>
          <h2 id="mi-dialog-title">导入混合标注</h2>
        </div>
        <button class="mi-close" type="button" title="关闭" :disabled="importing" @click="requestClose">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      <!-- 体部 -->
      <div class="mi-body">
        <p class="mi-desc">读取本地混合标注项目文件夹（含 project.json），全量生成文件、章节、图表与实体图谱。无需启动混合标注服务。</p>

        <label class="mi-label" for="mi-project-path">项目文件夹路径</label>
        <div class="mi-path-row">
          <input
            id="mi-project-path"
            ref="pathInput"
            v-model="projectPath"
            class="mi-input"
            type="text"
            placeholder="H:\...\mixed_annotation\backend\data\projects"
            spellcheck="false"
            autocomplete="off"
            :disabled="importing || loading"
            @keydown.enter="readProjects"
          />
          <button
            class="mi-btn mi-btn-outline"
            type="button"
            :disabled="loading || importing || !projectPath.trim()"
            @click="readProjects"
          >
            {{ loading ? "读取中..." : "读取项目" }}
          </button>
        </div>

        <!-- 错误就地显示（文案优先来自后端 detail） -->
        <div v-if="errorText" class="mi-error-box">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <span>{{ errorText }}</span>
        </div>

        <div class="mi-list-header">
          <span>项目列表</span>
          <span v-if="projects.length > 0" class="mi-list-count">{{ projects.length }} 个项目</span>
        </div>

        <div class="mi-list-area">
          <div v-if="loading" class="mi-state">
            <span class="mi-spinner"></span>
            <span>正在读取项目列表...</span>
          </div>
          <div v-else-if="!listLoaded" class="mi-state">
            尚未读取项目列表
          </div>
          <div v-else-if="projects.length === 0" class="mi-state">
            该路径下没有找到混合标注项目（缺少 project.json）
          </div>
          <div v-else class="mi-project-list">
            <button
              v-for="project in projects"
              :key="project.dir"
              class="mi-project-item"
              :class="{ selected: selectedDir === project.dir }"
              type="button"
              :disabled="importing"
              @click="selectedDir = project.dir"
            >
              <span class="mi-radio" aria-hidden="true"></span>
              <span class="mi-project-text">
                <span class="mi-project-name">{{ project.name || project.dir }}</span>
                <span class="mi-project-meta">
                  {{ fileCount(project) }} 个文件 · {{ labelCount(project) }} 个标签 · {{ relationCount(project) }} 种关系
                </span>
              </span>
            </button>
          </div>
        </div>

        <!-- 导入进度 -->
        <div v-if="importing" class="mi-progress-box">
          <span class="mi-spinner"></span>
          <span>正在导入文件、章节、图表与实体，请稍候...</span>
        </div>
      </div>

      <!-- 底部 -->
      <div class="mi-footer">
        <button class="mi-btn mi-btn-ghost" type="button" :disabled="importing" @click="requestClose">
          取消
        </button>
        <button class="mi-btn mi-btn-primary" type="button" :disabled="!canImport" @click="confirmImport">
          {{ importing ? "导入中..." : "导入并打开" }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ======================== 变量（沿用数据源面板视觉） ======================== */
.mi-overlay {
  --color-primary: #2563eb;
  --color-primary-dark: #1d4ed8;
  --color-primary-bg: #eff6ff;
  --color-success: #10b981;
  --color-danger: #dc2626;
  --color-danger-bg: #fef2f2;
  --color-text: #0f172a;
  --color-text-secondary: #475569;
  --color-text-muted: #64748b;
  --color-border: #e2e8f0;
  --color-border-light: #f1f5f9;
  --color-bg: #f8fafc;
  --color-surface: #ffffff;
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
  --shadow-xl: 0 20px 40px -8px rgba(0,0,0,0.12), 0 10px 15px -3px rgba(0,0,0,0.08);
  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --ease-out: cubic-bezier(0.4, 0, 0.2, 1);
}

/* ---------- 遮罩 ---------- */
.mi-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 150;
  padding: 24px;
  box-sizing: border-box;
  animation: mi-overlay-in 0.15s ease-out;
}

@keyframes mi-overlay-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* ---------- 弹窗卡片 ---------- */
.mi-dialog {
  background: #ffffff;
  border-radius: var(--radius-xl);
  width: 560px;
  max-width: 95vw;
  max-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-xl);
  animation: mi-dialog-in 0.2s ease-out;
}

@keyframes mi-dialog-in {
  from { opacity: 0; transform: scale(0.95) translateY(10px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

/* ---------- 头部 ---------- */
.mi-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 22px 26px 18px 26px;
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.mi-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  color: #7c3aed;
}

.mi-header-left h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
  letter-spacing: -0.01em;
}

.mi-close {
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.mi-close:hover:not(:disabled) {
  background: #f1f5f9;
  border-color: var(--color-border);
  color: var(--color-text-secondary);
}

.mi-close:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ---------- 体部 ---------- */
.mi-body {
  padding: 22px 26px 24px 26px;
  overflow-y: auto;
}

.mi-desc {
  margin: 0 0 20px 0;
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--color-text-secondary);
}

.mi-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: 8px;
}

.mi-path-row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}

.mi-input {
  flex: 1;
  min-width: 0;
  height: 40px;
  padding: 0 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: 13.5px;
  font-family: inherit;
  color: var(--color-text);
  background: #ffffff;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
  box-sizing: border-box;
}

.mi-input:focus {
  outline: none;
  border-color: #93c5fd;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.mi-input:disabled {
  background: #f8fafc;
  color: var(--color-text-muted);
  cursor: not-allowed;
}

/* ---------- 错误 ---------- */
.mi-error-box {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 16px;
  padding: 12px 14px;
  background: var(--color-danger-bg);
  border: 1px solid #fecaca;
  border-radius: var(--radius-md);
  color: var(--color-danger);
  font-size: 13px;
  font-weight: 500;
  line-height: 1.5;
  word-break: break-word;
}

.mi-error-box svg {
  flex-shrink: 0;
  margin-top: 1px;
}

/* ---------- 项目列表 ---------- */
.mi-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--color-text-muted);
  margin-bottom: 8px;
}

.mi-list-count {
  font-weight: 500;
  color: #94a3b8;
}

.mi-list-area {
  border: 1px solid var(--color-border-light);
  background: var(--color-bg);
  border-radius: var(--radius-lg);
  padding: 8px;
  min-height: 108px;
  max-height: 264px;
  overflow-y: auto;
  box-sizing: border-box;
}

.mi-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 92px;
  font-size: 13px;
  color: var(--color-text-muted);
  text-align: center;
  padding: 0 12px;
}

.mi-project-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.mi-project-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 11px 12px;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  background: #ffffff;
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  transition: all 0.15s var(--ease-out);
  box-sizing: border-box;
}

.mi-project-item:hover:not(:disabled) {
  border-color: #bfdbfe;
  background: var(--color-primary-bg);
}

.mi-project-item.selected {
  border-color: #93c5fd;
  background: var(--color-primary-bg);
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.08);
}

.mi-project-item:disabled {
  cursor: not-allowed;
  opacity: 0.65;
}

.mi-radio {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  border: 1.5px solid #cbd5e1;
  border-radius: 50%;
  background: #ffffff;
  position: relative;
  transition: all 0.15s var(--ease-out);
}

.mi-project-item.selected .mi-radio {
  border-color: var(--color-primary);
}

.mi-project-item.selected .mi-radio::after {
  content: "";
  position: absolute;
  top: 50%;
  left: 50%;
  width: 8px;
  height: 8px;
  margin: -4px 0 0 -4px;
  border-radius: 50%;
  background: var(--color-primary);
}

.mi-project-text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.mi-project-name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mi-project-meta {
  font-size: 12px;
  font-weight: 500;
  color: #94a3b8;
}

/* ---------- 导入进度 ---------- */
.mi-progress-box {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  background: var(--color-primary-bg);
  color: var(--color-primary-dark);
  font-size: 13px;
  font-weight: 600;
}

/* ---------- 底部 ---------- */
.mi-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 26px 20px 26px;
  border-top: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

/* ---------- 按钮 ---------- */
.mi-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 9px 20px;
  border-radius: var(--radius-md);
  font-size: 13.5px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.2s ease;
  border: 1px solid transparent;
  outline: none;
  white-space: nowrap;
}

.mi-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.mi-btn-primary {
  background: var(--color-primary);
  color: #ffffff;
  border-color: var(--color-primary);
}

.mi-btn-primary:hover:not(:disabled) {
  background: var(--color-primary-dark);
  border-color: var(--color-primary-dark);
}

.mi-btn-outline {
  background: #ffffff;
  color: var(--color-primary);
  border-color: #bfdbfe;
}

.mi-btn-outline:hover:not(:disabled) {
  background: var(--color-primary-bg);
}

.mi-btn-ghost {
  background: transparent;
  color: var(--color-text-secondary);
  border-color: var(--color-border);
}

.mi-btn-ghost:hover:not(:disabled) {
  background: #f1f5f9;
  color: var(--color-text);
}

/* ---------- 加载指示 ---------- */
.mi-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(37, 99, 235, 0.2);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: mi-spin 0.7s linear infinite;
  flex-shrink: 0;
}

@keyframes mi-spin {
  to { transform: rotate(360deg); }
}
</style>
