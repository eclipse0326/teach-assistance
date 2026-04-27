<template>
  <div class="max-w-[800px] mx-auto py-8 px-4">
    <div class="mb-8 flex flex-col md:flex-row md:justify-between md:items-center">
      <div>
        <h1 class="text-[24px] font-bold text-[#111827]">{{ titleText }}</h1>
        <p class="text-[14px] text-[#6B7280] mt-1">基于聊天记录自动统计</p>
      </div>
      <p class="text-[12px] text-[#6B7280] mt-2 md:mt-0">最后更新：{{ lastUpdated }}</p>
    </div>
    <div v-if="isTeacher" class="mb-6 bg-white rounded-lg p-4 shadow flex flex-col md:flex-row md:items-center gap-3">
      <label class="text-sm text-[#374151] min-w-[88px]">选择用户记录</label>
      <select
        v-model="selectedUsername"
        class="border border-[#D1D5DB] rounded px-3 py-2 text-sm text-[#111827] bg-white"
        @change="fetchKeywordTop"
      >
        <option value="">全部用户（全部会话）</option>
        <option v-for="name in usernames" :key="name" :value="name">
          {{ name }}
        </option>
      </select>
      <template v-if="viewMode === 'rank'">
        <label class="text-sm text-[#374151]">显示范围</label>
        <select
          v-model="selectedTopN"
          class="border border-[#D1D5DB] rounded px-3 py-2 text-sm text-[#111827] bg-white"
          @change="fetchKeywordTop"
        >
          <option v-for="option in topOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </template>
      <button
        type="button"
        class="px-3 py-2 rounded bg-[#0EA5E9] text-white text-sm hover:bg-[#0284C7]"
        @click="toggleViewMode"
      >
        {{ viewMode === 'rank' ? '切换词云' : '切换排行' }}
      </button>
      <button
        type="button"
        class="px-3 py-2 rounded bg-[#165DFF] text-white text-sm hover:bg-[#0F4BD8]"
        @click="fetchKeywordTop"
      >
        刷新统计
      </button>
    </div>
    <div v-else class="mb-6 bg-white rounded-lg p-4 shadow flex flex-col md:flex-row md:items-center gap-2">
      <label class="text-sm text-[#374151] whitespace-nowrap">当前用户</label>
      <div class="text-sm text-[#111827] px-3 py-2 border border-[#D1D5DB] rounded bg-[#F9FAFB]">
        {{ currentUsername || '未知用户' }}
      </div>
      <template v-if="viewMode === 'rank'">
        <label class="text-sm text-[#374151]">显示范围</label>
        <select
          v-model="selectedTopN"
          class="border border-[#D1D5DB] rounded px-3 py-2 text-sm text-[#111827] bg-white"
          @change="fetchKeywordTop"
        >
          <option v-for="option in topOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </template>
      <button
        type="button"
        class="px-3 py-2 rounded bg-[#0EA5E9] text-white text-sm hover:bg-[#0284C7]"
        @click="toggleViewMode"
      >
        {{ viewMode === 'rank' ? '切换词云' : '切换排行' }}
      </button>
      <button
        type="button"
        class="px-3 py-2 rounded bg-[#165DFF] text-white text-sm hover:bg-[#0F4BD8]"
        @click="fetchKeywordTop"
      >
        刷新统计
      </button>
    </div>

    <div v-if="loading" class="text-[#6B7280]">加载中...</div>
    <div v-else-if="errorMessage" class="text-[#EF4444]">{{ errorMessage }}</div>
    <div v-else-if="keywords.length === 0" class="text-[#6B7280]">暂无关键词统计数据</div>

    <div v-else>
      <div v-if="viewMode === 'rank'" class="space-y-4 max-h-[60vh] overflow-y-auto pr-1">
        <div
          v-for="(item, index) in keywords"
          :key="item.keyword"
          class="card-hover bg-white rounded-lg p-4 flex items-start shadow"
        >
          <div
            :class="rankClass(index)"
            class="w-10 h-10 rounded-full flex items-center justify-center font-bold text-lg mr-4 flex-shrink-0"
          >
            {{ index + 1 }}
          </div>
          <div class="flex-1">
            <h3 class="text-[16px] font-medium text-[#111827]">{{ item.keyword }}</h3>
            <p class="text-[14px] text-[#6B7280] mt-1">被提问 {{ item.count }} 次</p>
          </div>
        </div>
      </div>
      <div v-else class="bg-white rounded-lg shadow p-3">
        <div ref="cloudContainerRef" class="cloud-container"></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import axios from 'axios';
import type { AxiosError } from 'axios';
import { MessagePlugin } from 'tdesign-vue-next';
import * as echarts from 'echarts';
import API_ENDPOINTS from '@/utils/apiConfig';

interface KeywordItem {
  keyword: string;
  count: number;
}

interface KeywordTopResponse {
  session_id: string | null;
  username?: string | null;
  top_n?: number | null;
  total_questions: number;
  unique_keywords: number;
  llm_fail_count: number;
  top_keywords: KeywordItem[];
}

interface ChatSession {
  id: string;
  username?: string;
  title?: string;
}

interface AllUsersResponse {
  status: string;
  data: Array<{
    id?: number;
    username?: string;
    name?: string;
    role?: string;
    email?: string;
    created_at?: string;
  } | [number, string, string, string]>;
}

const topOptions = [
  { label: 'Top 5', value: '5' },
  { label: 'Top 10', value: '10' },
  { label: 'Top 20', value: '20' },
  { label: 'Top 50', value: '50' },
];
const loading = ref(false);
const keywords = ref<KeywordItem[]>([]);
const errorMessage = ref('');
const lastUpdated = ref('-');
const sessions = ref<ChatSession[]>([]);
const selectedUsername = ref('');
const usernames = ref<string[]>([]);
const currentUsername = ref('');
const currentRole = ref('student');
const selectedTopN = ref('10');
const viewMode = ref<'rank' | 'cloud'>('rank');
const cloudContainerRef = ref<HTMLDivElement | null>(null);
let cloudChart: echarts.ECharts | null = null;

const isTeacher = computed(() => currentRole.value === 'teacher');
const titleText = computed(() =>
  viewMode.value === 'cloud'
    ? '高频问题关键词（全部）'
    : `高频问题关键词TOP${selectedTopN.value}`
);

const toggleViewMode = async () => {
  viewMode.value = viewMode.value === 'rank' ? 'cloud' : 'rank';
  await fetchKeywordTop();
};

const parseJwtPayload = (token: string): Record<string, unknown> => {
  try {
    const parts = token.split('.');
    if (parts.length < 2) return {};
    const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4);
    return JSON.parse(atob(padded));
  } catch {
    return {};
  }
};

const initCurrentUserFromToken = () => {
  const token = localStorage.getItem('jwt') || '';
  const payload = token ? parseJwtPayload(token) : {};
  currentUsername.value = String(payload?.sub || '').trim();
  const role = String(payload?.role || '').trim().toLowerCase();
  currentRole.value = role === 'teacher' ? 'teacher' : 'student';
  // 学生模式下固定只能看自己的统计
  if (currentRole.value === 'student' && currentUsername.value) {
    selectedUsername.value = currentUsername.value;
  }
};

const rankClass = (index: number): string => {
  if (index === 0) return 'rank-1';
  if (index === 1) return 'rank-2';
  if (index === 2) return 'rank-3';
  return 'rank-4';
};

const fetchSessions = async () => {
  try {
    const response = await axios.get<ChatSession[]>(API_ENDPOINTS.CHAT.SESSIONS);
    sessions.value = Array.isArray(response.data) ? response.data : [];
  } catch (error) {
    console.error('获取会话列表失败:', error);
    sessions.value = [];
  }
};

const fetchAllUsers = async () => {
  if (!isTeacher.value) {
    usernames.value = currentUsername.value ? [currentUsername.value] : [];
    return;
  }
  try {
    const response = await axios.get<AllUsersResponse>(API_ENDPOINTS.USER.ALL_USERS);
    const rawUsers = Array.isArray(response.data?.data) ? response.data.data : [];
    usernames.value = Array.from(
      new Set(
        rawUsers
          .map((item) => {
            let role = '';
            let name = '';
            if (Array.isArray(item)) {
              name = String(item[1] || '').trim();
              role = String(item[2] || '').trim().toLowerCase();
            } else {
              name = String(item.username || item.name || item.email || '').trim();
              role = String(item.role || '').trim().toLowerCase();
            }
            return role === 'teacher' ? '' : name;
          })
          .filter((name) => !!name)
      )
    );
  } catch (error) {
    console.error('获取全部用户失败:', error);
    // 用户接口失败时兜底：从会话里提取用户名
    usernames.value = Array.from(
      new Set(
        sessions.value
          .map((s) => (s.username || '').trim())
          .filter((name) => !!name && name !== '未知用户')
      )
    );
  }
};

const fetchKeywordTop = async () => {
  loading.value = true;
  errorMessage.value = '';
  try {
    const requestUsername = isTeacher.value
      ? (selectedUsername.value || null)
      : (currentUsername.value || null);
    const response = await axios.post<KeywordTopResponse>(API_ENDPOINTS.CHAT.KEWWORD_TOP, {
      session_id: null,
      username: requestUsername,
      top_n: viewMode.value === 'cloud' ? null : Number(selectedTopN.value),
      use_llm: true,
      per_question_max_keywords: 5
    });
    keywords.value = response.data.top_keywords || [];
    lastUpdated.value = new Date().toLocaleString('zh-CN');
  } catch (error) {
    console.error('获取关键词统计失败:', error);
    const axiosError = error as AxiosError<{ detail?: string }>;
    errorMessage.value = axiosError.response?.data?.detail || '获取关键词统计失败，请稍后重试';
    MessagePlugin.error('获取关键词统计失败');
  } finally {
    loading.value = false;
  }
};

const renderWordCloud = async () => {
  if (viewMode.value !== 'cloud') return;
  await nextTick();
  if (!cloudContainerRef.value) return;

  if (cloudChart && cloudChart.getDom() !== cloudContainerRef.value) {
    cloudChart.dispose();
    cloudChart = null;
  }
  if (!cloudChart) {
    cloudChart = echarts.init(cloudContainerRef.value);
  }

  const counts = keywords.value.map((item) => item.count);
  const minCount = counts.length ? Math.min(...counts) : 0;
  const maxCount = counts.length ? Math.max(...counts) : 0;
  const range = maxCount - minCount || 1;
  const minSize = 16;
  const maxSize = 56;
  const centerX = 50;
  const centerY = 50;
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  const step = 4.8;

  const cloudData = keywords.value.map((item, index) => {
    const radius = step * Math.sqrt(index + 1);
    const angle = index * goldenAngle;
    return {
    name: item.keyword,
    value: item.count,
    x: centerX + Math.cos(angle) * radius,
    y: centerY + Math.sin(angle) * radius,
    size: minSize + ((item.count - minCount) / range) * (maxSize - minSize),
    };
  });

  cloudChart.setOption({
    tooltip: {
      formatter: (params: { data: { name: string; value: [number, number, number] } }) =>
        `${params.data.name}: ${params.data.value[2]} 次`,
    },
    xAxis: { show: false, min: 0, max: 100 },
    yAxis: { show: false, min: 0, max: 100 },
    grid: { left: 0, right: 0, top: 0, bottom: 0 },
    series: [{
      type: 'scatter',
      data: cloudData.map((d) => ({
        name: d.name,
        value: [d.x, d.y, d.value],
        symbolSize: d.size,
      })),
      label: {
        show: true,
        formatter: (params: { data: { name: string } }) => params.data.name,
        color: '#111827',
        fontSize: 13,
      },
      itemStyle: {
        color: () => {
          const colors = ['#93C5FD', '#C4B5FD', '#FDBA74', '#99F6E4', '#FCA5A5', '#A5B4FC'];
          return colors[Math.floor(Math.random() * colors.length)];
        },
        opacity: 0.85,
      },
      emphasis: {
        scale: true,
      },
    }],
  });
};

const handleResize = () => {
  cloudChart?.resize();
};

onMounted(() => {
  initCurrentUserFromToken();
  fetchSessions().then(fetchAllUsers);
  fetchKeywordTop();
  window.addEventListener('resize', handleResize);
});

onUnmounted(() => {
  window.removeEventListener('resize', handleResize);
  if (cloudChart) {
    cloudChart.dispose();
    cloudChart = null;
  }
});

watch(
  () => [keywords.value, viewMode.value],
  () => {
    if (viewMode.value === 'cloud') {
      renderWordCloud();
    }
  },
  { deep: true }
);
</script>

<style scoped>
  /* 自定义排名色和hover动画 */
  .rank-1 { background-color: #FFD700; color: #111827; }
  .rank-2 { background-color: #C0C0C0; color: #111827; }
  .rank-3 { background-color: #CD7F32; color: #fff; }
  .rank-4, .rank-5 { background-color: #E5E7EB; color: #111827; }
  .card-hover { transition: transform 0.2s, box-shadow 0.2s; }
  .card-hover:hover { transform: translateY(-4px); box-shadow: 0 8px 16px rgba(0,0,0,0.1); }
  .cloud-container { width: 100%; height: 62vh; min-height: 420px; }
</style>