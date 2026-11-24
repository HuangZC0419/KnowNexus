<script setup>
/**
 * 登录成功后的「功能模块选择」门禁页。
 * 纯展示 + 事件上抛，不持有业务状态：
 *  - enter(moduleId) 交由 App.vue 决定进入哪个模块
 *  - logout 交由 App.vue 复用既有登出逻辑
 */
import { computed } from "vue";
import OceanBreath from "../OceanBreath.vue";

const props = defineProps({
  user: {
    type: Object,
    default: () => ({ name: "", username: "", role: "" }),
  },
});

const emit = defineEmits(["enter", "logout"]);

const roleLabel = computed(() => (props.user && props.user.role === "manager" ? "管理者" : "普通用户"));
const displayName = computed(() => props.user?.name || props.user?.username || "当前用户");
const accountName = computed(() => props.user?.username || "");

/**
 * 模块目录：图标用几何图元描述（circles / lines / paths），
 * 避免为图标写 v-if 分支或引入外部图标库，也保证不使用 emoji。
 */
const moduleCatalog = [
  {
    id: "organization",
    title: "知识组织",
    fullName: "装配工艺知识库软件工具知识组织功能模块",
    description: "导入装配工艺数据，梳理知识节点与关系，形成可复用的知识网络。",
    available: true,
    icon: {
      circles: [
        [18, 5, 3],
        [6, 12, 3],
        [18, 19, 3],
      ],
      lines: [
        [8.59, 13.51, 15.42, 17.49],
        [15.41, 6.51, 8.59, 10.49],
      ],
    },
  },
  {
    id: "modeling",
    title: "知识建模",
    fullName: "装配工艺知识库软件工具知识建模功能模块",
    description: "定义知识结构与约束规则，沉淀装配工艺领域模型。",
    available: false,
    icon: {
      paths: [
        "M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z",
        "M3.3 7l8.7 5 8.7-5",
        "M12 22V12",
      ],
    },
  },
  {
    id: "retrieval",
    title: "知识检索",
    fullName: "装配工艺知识库软件工具知识检索功能模块",
    description: "按语义与关系检索装配工艺知识，快速定位所需信息。",
    available: false,
    icon: {
      circles: [[11, 11, 7]],
      lines: [[21, 21, 16.65, 16.65]],
      paths: ["M11 8v6", "M8 11h6"],
    },
  },
];

function handleEnter(module) {
  if (!module.available) return;
  emit("enter", module.id);
}

function handleLogout() {
  emit("logout");
}
</script>

<template>
  <div class="module-hub">
    <div class="hub-backdrop" aria-hidden="true">
      <OceanBreath :speed="0.7" :intensity="0.6" theme="day" :density="1.0" />
    </div>

    <header class="hub-header">
      <div class="hub-brand">
        <span class="hub-logo">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <circle cx="18" cy="5" r="3" />
            <circle cx="6" cy="12" r="3" />
            <circle cx="18" cy="19" r="3" />
            <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
            <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
          </svg>
          SCU
        </span>
        <span class="hub-brand-title">装配工艺知识库软件工具</span>
      </div>

      <div class="hub-user">
        <span class="hub-avatar" aria-hidden="true">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
            <circle cx="12" cy="7" r="4" />
          </svg>
        </span>
        <span class="hub-user-meta">
          <span class="hub-user-name">{{ displayName }}</span>
          <span class="hub-user-sub">
            <span v-if="accountName && accountName !== displayName" class="hub-user-account">{{ accountName }}</span>
            <span class="hub-role-chip">{{ roleLabel }}</span>
          </span>
        </span>
        <button type="button" class="hub-logout" @click="handleLogout">退出登录</button>
      </div>
    </header>

    <main class="hub-main">
      <div class="hub-intro">
        <h1 class="hub-title">请选择功能模块</h1>
        <p class="hub-subtitle">登录成功，请选择需要进入的功能模块。未开放模块正在开发中。</p>
      </div>

      <div class="hub-grid">
        <button
          v-for="module in moduleCatalog"
          :key="module.id"
          type="button"
          class="module-card"
          :class="module.available ? 'is-available' : 'is-locked'"
          :disabled="!module.available"
          :aria-disabled="!module.available"
          @click="handleEnter(module)"
        >
          <span class="card-head">
            <span class="card-icon">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <circle
                  v-for="(circle, index) in module.icon.circles || []"
                  :key="`c-${index}`"
                  :cx="circle[0]"
                  :cy="circle[1]"
                  :r="circle[2]"
                />
                <line
                  v-for="(line, index) in module.icon.lines || []"
                  :key="`l-${index}`"
                  :x1="line[0]"
                  :y1="line[1]"
                  :x2="line[2]"
                  :y2="line[3]"
                />
                <path
                  v-for="(path, index) in module.icon.paths || []"
                  :key="`p-${index}`"
                  :d="path"
                />
              </svg>
            </span>
            <span v-if="!module.available" class="card-badge">开发中</span>
          </span>

          <span class="card-title">{{ module.title }}</span>
          <span class="card-fullname">{{ module.fullName }}</span>
          <span class="card-desc">{{ module.description }}</span>

          <span class="card-foot">
            <span v-if="module.available" class="card-enter">
              进入模块
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <path d="M5 12h12" />
                <path d="M13 6l6 6-6 6" />
              </svg>
            </span>
            <span v-else class="card-pending">即将开放</span>
          </span>
        </button>
      </div>
    </main>
  </div>
</template>

<style scoped>
.module-hub {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  width: 100%;
  background: #ffffff;
  color: #0f172a;
  font-family: "Inter", "Google Sans", system-ui, -apple-system, sans-serif;
  overflow-x: hidden;
}

.hub-backdrop {
  position: absolute;
  inset: 0;
  z-index: 0;
  opacity: 0.5;
  pointer-events: none;
}

/* ===== Header ===== */
.hub-header {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem 1.5rem;
  flex-wrap: wrap;
  padding: 1.25rem 2rem;
  border-bottom: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(8px);
}

.hub-brand {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-width: 0;
}

.hub-logo {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  height: 32px;
  padding: 0 0.75rem;
  border-radius: 6px;
  background: #0f172a;
  color: #ffffff;
  font-size: 0.95rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  flex-shrink: 0;
}

.hub-logo svg {
  width: 18px;
  height: 18px;
}

.hub-brand-title {
  font-size: 1rem;
  font-weight: 600;
  color: #0f172a;
  letter-spacing: -0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.hub-user {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  min-width: 0;
}

.hub-avatar {
  width: 34px;
  height: 34px;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #475569;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.hub-avatar svg {
  width: 18px;
  height: 18px;
}

.hub-user-meta {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
  min-width: 0;
}

.hub-user-name {
  font-size: 0.92rem;
  font-weight: 600;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 220px;
}

.hub-user-sub {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.78rem;
  color: #64748b;
}

.hub-user-account {
  white-space: nowrap;
}

.hub-user-account::before {
  content: "@";
  margin-right: 1px;
  color: #94a3b8;
}

.hub-role-chip {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 0.5rem;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #475569;
  font-size: 0.72rem;
  font-weight: 500;
}

.hub-logout {
  height: 34px;
  padding: 0 0.95rem;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #0f172a;
  font-family: inherit;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.18s ease, border-color 0.18s ease, transform 0.18s ease;
  flex-shrink: 0;
}

.hub-logout:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
  transform: translateY(-1px);
}

.hub-logout:focus-visible {
  outline: 3px solid rgba(15, 23, 42, 0.28);
  outline-offset: 2px;
}

/* ===== Main ===== */
.hub-main {
  position: relative;
  z-index: 2;
  flex: 1;
  width: 100%;
  max-width: 1200px;
  margin: 0 auto;
  padding: 3rem 2rem 3.5rem;
  display: flex;
  flex-direction: column;
  gap: 2.25rem;
}

.hub-intro {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.hub-title {
  margin: 0;
  font-size: clamp(1.75rem, 2.6vw, 2.4rem);
  font-weight: 700;
  letter-spacing: -0.025em;
  color: #0f172a;
  line-height: 1.2;
}

.hub-subtitle {
  margin: 0;
  font-size: 0.98rem;
  line-height: 1.6;
  color: #64748b;
  max-width: 46rem;
}

/* ===== Cards ===== */
.hub-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1.25rem;
}

.module-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.65rem;
  min-width: 0;
  min-height: 260px;
  padding: 1.5rem;
  border-radius: 20px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  text-align: left;
  font-family: inherit;
  color: inherit;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}

.module-card.is-available:hover {
  transform: translateY(-3px);
  border-color: #cbd5e1;
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.09);
}

.module-card:focus-visible {
  outline: 3px solid rgba(15, 23, 42, 0.32);
  outline-offset: 3px;
}

.module-card.is-locked {
  cursor: not-allowed;
  border-color: #e2e8f0;
  background: #ffffff;
  box-shadow: none;
}

.module-card.is-locked:hover {
  transform: none;
  border-color: #e2e8f0;
  box-shadow: none;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  width: 100%;
}

.card-icon {
  width: 44px;
  height: 44px;
  border-radius: 13px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #0f172a;
  color: #ffffff;
  flex-shrink: 0;
}

.card-icon svg {
  width: 22px;
  height: 22px;
}

.is-locked .card-icon {
  background: #f1f5f9;
  color: #94a3b8;
}

.card-badge {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 0.65rem;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  background: #f1f5f9;
  color: #475569;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  flex-shrink: 0;
}

.card-title {
  font-size: 1.22rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.015em;
  line-height: 1.3;
}

.is-locked .card-title {
  color: #334155;
}

.card-fullname {
  font-size: 0.8rem;
  line-height: 1.5;
  color: #64748b;
}

.is-locked .card-fullname {
  color: #94a3b8;
}

.card-desc {
  font-size: 0.92rem;
  line-height: 1.6;
  color: #475569;
}

.is-locked .card-desc {
  color: #64748b;
}

.card-foot {
  margin-top: auto;
  padding-top: 0.65rem;
  display: flex;
  align-items: center;
  min-height: 24px;
}

.card-enter {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.88rem;
  font-weight: 600;
  color: #0f172a;
}

.card-enter svg {
  width: 16px;
  height: 16px;
  transition: transform 0.2s ease;
}

.module-card.is-available:hover .card-enter svg {
  transform: translateX(3px);
}

.card-pending {
  font-size: 0.85rem;
  font-weight: 500;
  color: #94a3b8;
}

/* ===== Responsive ===== */
@media (max-width: 1024px) {
  .hub-header {
    padding: 1rem 1.25rem;
  }

  .hub-main {
    padding: 2.25rem 1.25rem 2.75rem;
  }

  .hub-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 820px) {
  .hub-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .module-card {
    min-height: 0;
  }
}

@media (max-width: 720px) {
  .hub-brand-title {
    display: none;
  }

  .hub-user {
    width: 100%;
    justify-content: space-between;
  }

  .hub-user-name {
    max-width: 150px;
  }
}
</style>
