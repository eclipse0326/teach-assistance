<template>
    <div class="graph-container flex flex-col">
        <div class="self-start mb-4 flex items-center gap-3">
            <button @click="fetchGraphData"
                class="bg-blue-500 hover:bg-blue-700 text-white py-2 px-4 rounded transition duration-200 ease-in-out"
                :disabled="isLoading">
                <span v-if="isLoading" class="flex items-center">
                    <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg"
                        fill="none" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4">
                        </circle>
                        <path class="opacity-75" fill="currentColor"
                            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z">
                        </path>
                    </svg>
                    加载中...
                </span>
                <span v-else>生成知识图谱</span>
            </button>
            <button @click="toggleFullscreen"
                class="bg-slate-600 hover:bg-slate-700 text-white py-2 px-4 rounded transition duration-200 ease-in-out">
                {{ isFullscreen ? '退出全屏' : '全屏展示' }}
            </button>
        </div>
        <div class="self-start mb-4 px-3 py-2 bg-white border border-[#d9d9d9] rounded-md shadow-sm">
            <div class="text-sm text-gray-700 mb-2">图例（实体类型）</div>
            <div class="legend-list">
                <button
                    v-for="item in LEGEND_ITEMS"
                    :key="item.type"
                    class="legend-item"
                    :class="{ 'legend-item-inactive': !isTypeVisible(item.type) }"
                    type="button"
                    @click="toggleEntityType(item.type)"
                >
                    <span class="legend-color-dot" :style="{ backgroundColor: item.color }"></span>
                    <span class="text-xs text-gray-700">{{ item.label }}</span>
                </button>
            </div>
        </div>
        <div v-if="errorMessage" class="text-red-500 mb-4 p-3 bg-red-50 border border-red-200 rounded self-start">{{
            errorMessage
            }}</div>
        <div id="sigma-container" class="w-full h-[600px] bg-white rounded-lg border border-[#d9d9d9] shadow-md">
        </div>
    </div>
</template>

<script setup lang="ts">

import { useRoute } from 'vue-router';
import API_ENDPOINTS from '@/utils/apiConfig';


const route = useRoute();

// 定义props以接收知识库ID
const props = defineProps({
    kbId: {
        type: String,
        default: ''
    }
});


import { onMounted, ref } from 'vue';
import chroma from "chroma-js";
import Graph from "graphology";
import ForceSupervisor from "graphology-layout-force/worker";
import Sigma from "sigma";
import { v4 as uuid } from "uuid";

// 类型定义
interface GraphNode {
    id: string;
    label?: string;
    key?: string;
    type?: string;
    x?: number;
    y?: number;
    size?: number;
    color?: string;
}

interface GraphEdge {
    source: string;
    target: string;
    label?: string;
    relation?: string;
}

interface GraphData {
    nodes: GraphNode[];
    edges: GraphEdge[];
}

interface ApiResponse {
    message: string;
    graph_data: GraphData;
}

// 状态变量
let renderer: Sigma | null = null;
let layout: ForceSupervisor | null = null;
let graph = new Graph({ multi: true });
let layoutStopTimer: ReturnType<typeof setTimeout> | null = null;

const ENTITY_TYPE_COLORS: Record<string, string> = {
    Data_Structure: '#3B82F6',
    Algorithm: '#10B981',
    Operation: '#F59E0B',
    Complexity: '#EF4444',
    Concept: '#8B5CF6',
    Application: '#14B8A6',
    Code_Snippet: '#F97316',
    默认: '#90D8FF'
};
const LEGEND_ITEMS = [
    { type: 'Data_Structure', label: 'Data_Structure', color: ENTITY_TYPE_COLORS.Data_Structure },
    { type: 'Algorithm', label: 'Algorithm', color: ENTITY_TYPE_COLORS.Algorithm },
    { type: 'Operation', label: 'Operation', color: ENTITY_TYPE_COLORS.Operation },
    { type: 'Complexity', label: 'Complexity', color: ENTITY_TYPE_COLORS.Complexity },
    { type: 'Concept', label: 'Concept', color: ENTITY_TYPE_COLORS.Concept },
    { type: 'Application', label: 'Application', color: ENTITY_TYPE_COLORS.Application },
    { type: 'Code_Snippet', label: 'Code_Snippet', color: ENTITY_TYPE_COLORS.Code_Snippet },
    { type: '默认', label: '默认/其他', color: ENTITY_TYPE_COLORS['默认'] }
];

// 大图性能阈值（可按机器性能再调）
const LARGE_GRAPH_NODE_THRESHOLD = 250;
const LARGE_GRAPH_EDGE_THRESHOLD = 700;
const VERY_LARGE_GRAPH_NODE_THRESHOLD = 800;
const VERY_LARGE_GRAPH_EDGE_THRESHOLD = 2500;
const ENABLE_AUTO_FORCE_LAYOUT = false;

// 响应式状态
const isLoading = ref<boolean>(false);
const errorMessage = ref<string>('');
const isFullscreen = ref<boolean>(false);
const latestGraphData = ref<GraphData | null>(null);
const visibleEntityTypes = ref<string[]>(LEGEND_ITEMS.map(item => item.type));

const getNodeType = (node: GraphNode): string => (node.key || node.type || '默认').trim();
const isTypeVisible = (type: string): boolean => visibleEntityTypes.value.includes(type);
const toggleEntityType = (type: string): void => {
    if (isTypeVisible(type)) {
        visibleEntityTypes.value = visibleEntityTypes.value.filter(item => item !== type);
    } else {
        visibleEntityTypes.value = [...visibleEntityTypes.value, type];
    }
    if (latestGraphData.value) {
        updateGraph(latestGraphData.value);
    }
};

// 拖拽状态
let draggedNode: string | null = null;
let isDragging = false;

const toggleFullscreen = async (): Promise<void> => {
    const container = document.getElementById("sigma-container");
    if (!container) return;

    try {
        if (!document.fullscreenElement) {
            await container.requestFullscreen();
        } else {
            await document.exitFullscreen();
        }
    } catch (error) {
        console.error("切换全屏失败:", error);
        errorMessage.value = `切换全屏失败: ${error instanceof Error ? error.message : String(error)}`;
    }
};

// 实现获取图数据的函数
const fetchGraphData = async (): Promise<void> => {
    isLoading.value = true;
    errorMessage.value = '';

    try {
        // 确保我们有有效的知识库ID
        const folderPath = props.kbId || route.params.id;

        // 检查folderPath是否有效
        if (!folderPath) {
            throw new Error('未提供有效的知识库ID');
        }

        // 使用新的API端点并传递知识库ID
        console.log('Fetching graph data for folder ID:', folderPath);
        const response = await fetch(API_ENDPOINTS.KNOWLEDGE_GRAPH.PROCESS_KNOWLEDGE_BASE, {
            method: 'POST',
            headers: {
                'accept': 'application/json',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                // 从props或路由参数获取知识库ID
                "folder_path": folderPath
            })
        });

        if (!response.ok) {
            throw new Error(`API请求失败：${response.statusText}`);
        }

        const data = await response.json() as ApiResponse[];
        if (data && data.length > 0 && data[0].graph_data) {
            latestGraphData.value = data[0].graph_data;
            updateGraph(data[0].graph_data);
        } else {
            errorMessage.value = '返回的数据格式不正确/知识库为空';
        }
    } catch (error) {
        console.error('获取图数据出错:', error);
        errorMessage.value = `获取图数据出错: ${error instanceof Error ? error.message : String(error)}`;
    } finally {
        isLoading.value = false;
    }
};


// 更新图谱的函数
const updateGraph = (graphData: GraphData): void => {
    if (!graphData || !graphData.nodes || !graphData.edges) {
        console.error('无效的图谱数据');
        return;
    }

    // 数据预处理：处理重复节点ID（并统一为去首尾空格后的字符串）
    const uniqueNodes = new Map<string, GraphNode>();
    graphData.nodes.forEach(node => {
        const normalizedId = String(node.id ?? '').trim();
        if (!normalizedId) return;

        // 如果节点ID已存在，合并标签信息
        if (uniqueNodes.has(normalizedId)) {
            const existing = uniqueNodes.get(normalizedId)!;
            if (node.label && existing.label !== node.label) {
                existing.label = `${existing.label} | ${node.label}`;
            }
        } else {
            uniqueNodes.set(normalizedId, {
                ...node,
                id: normalizedId,
                label: (node.label || normalizedId).trim(),
                key: getNodeType(node)
            });
        }
    });
    
    // 更新节点列表并按图例筛选
    const processedNodes = Array.from(uniqueNodes.values());
    const nodeTypeById = new Map<string, string>();
    processedNodes.forEach(node => {
        nodeTypeById.set(node.id, getNodeType(node));
    });
    const visibleNodes = processedNodes.filter(node => isTypeVisible(getNodeType(node)));
    
    // 先处理边，再根据过滤结果收集需要的节点ID
    const rawEdges = graphData.edges.map(edge => {
        const source = String(edge.source ?? '').trim();
        const target = String(edge.target ?? '').trim();
        if (!source || !target) return null;

        // 安全地检查 relation 字段
        let label = (edge.label || '').trim();
        if (!label && edge.relation) {
            label = String(edge.relation).trim();
        }

        return {
            source,
            target,
            label: label
        };
    });
    const processedEdges = rawEdges
        .filter((edge): edge is { source: string; target: string; label: string } => !!edge)
        .filter((edge) => {
            const sourceType = nodeTypeById.get(edge.source) || '默认';
            const targetType = nodeTypeById.get(edge.target) || '默认';
            return isTypeVisible(sourceType) && isTypeVisible(targetType);
        });

    const allRequiredNodeIds = new Set<string>();
    visibleNodes.forEach(node => allRequiredNodeIds.add(node.id));
    processedEdges.forEach(edge => {
        allRequiredNodeIds.add(edge.source);
        allRequiredNodeIds.add(edge.target);
    });
    
    // 为缺失的节点创建占位节点
    const finalNodes = [...visibleNodes];
    allRequiredNodeIds.forEach(nodeId => {
        if (!uniqueNodes.has(nodeId)) {
            finalNodes.push({
                id: nodeId,
                label: nodeId,
                type: '默认'
            });
        }
    });

    const isLargeGraph = finalNodes.length >= LARGE_GRAPH_NODE_THRESHOLD || processedEdges.length >= LARGE_GRAPH_EDGE_THRESHOLD;
    const isVeryLargeGraph =
        finalNodes.length >= VERY_LARGE_GRAPH_NODE_THRESHOLD || processedEdges.length >= VERY_LARGE_GRAPH_EDGE_THRESHOLD;

    // 清空现有图谱
    graph.clear();

    // 使用大间距螺旋初始布局，确保节点天然分散
    const positionedNodes = new Map<string, { x: number; y: number }>();
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));
    const spacing = 180;
    finalNodes.forEach((node, index) => {
        const radius = spacing * Math.sqrt(index + 1);
        const angle = index * goldenAngle;
        positionedNodes.set(node.id, {
            x: Math.cos(angle) * radius,
            y: Math.sin(angle) * radius
        });
    });

    // 添加节点
    finalNodes.forEach((node) => {
        const pos = positionedNodes.get(node.id) || { x: 0, y: 0 };

        const nodeType = getNodeType(node);
        const color = ENTITY_TYPE_COLORS[nodeType] || ENTITY_TYPE_COLORS['默认'];

        graph.addNode(node.id, {
            x: pos.x,
            y: pos.y,
            size: 10,
            color: color,
            label: node.label || node.id,
        });
    });

    // 添加边
    processedEdges.forEach((edge, index) => {
        if (graph.hasNode(edge.source) && graph.hasNode(edge.target)) {
            try {
                graph.addEdgeWithKey(`${edge.source}->${edge.target}#${index}`, edge.source, edge.target, {
                    label: edge.label || '',
                    size: 1.5,
                    color: '#9CA3AF',
                    forceLabel: !isLargeGraph,
                });
            } catch (error) {
                console.warn(`添加边时出错 (${edge.source} -> ${edge.target}): `, error);
            }
        } else {
            console.warn(`跳过边: 源节点或目标节点不存在 (${edge.source} -> ${edge.target})`);
        }
    });

    // 重新应用力导向布局
    if (layout) {
        layout.kill();
        layout = null;
    }
    if (layoutStopTimer) {
        clearTimeout(layoutStopTimer);
        layoutStopTimer = null;
    }

    // 默认关闭自动力导，避免节点被边关系重新拉回中心变拥挤
    if (ENABLE_AUTO_FORCE_LAYOUT && !isVeryLargeGraph) {
        layout = new ForceSupervisor(graph, {
            isNodeFixed: (_, attr) => attr.highlighted,
            settings: {
                attraction: isLargeGraph ? 0.00003 : 0.00006,
                repulsion: isLargeGraph ? 0.55 : 0.75,
                gravity: 0.000005,
                inertia: 0.6,
                maxMove: isLargeGraph ? 70 : 120
            }
        });
        layout.start();
        layoutStopTimer = setTimeout(() => {
            if (layout) {
                layout.stop();
            }
        }, isLargeGraph ? 7000 : 10000);
    }

    // 如果已有渲染器，需要先销毁它
    if (renderer) {
        renderer.kill();
        renderer = null;
    }

    // 重新创建渲染器
    const container = document.getElementById("sigma-container");
    if (container) {
        renderer = new Sigma(graph, container, {
            minCameraRatio: 0.08,
            maxCameraRatio: 4,
            renderLabels: true,
            renderEdgeLabels: !isLargeGraph,
            labelRenderedSizeThreshold: 0,
            labelDensity: 3,
            labelGridCellSize: 40,
            edgeLabelSize: 12,
            edgeLabelWeight: "bold",
            defaultEdgeColor: "#9CA3AF",
            defaultNodeType: "circle"
        });

        // 重新绑定事件
        bindEvents();
    }
};

// 封装事件绑定函数
const bindEvents = (): void => {
    if (!renderer) return;

    // On mouse down on a node
    renderer.on("downNode", (e) => {
        isDragging = true;
        draggedNode = e.node;
        graph.setNodeAttribute(draggedNode, "highlighted", true);
        if (renderer && !renderer.getCustomBBox()) renderer.setCustomBBox(renderer.getBBox());
    });

    // On mouse move, if the drag mode is enabled, we change the position of the draggedNode
    renderer.on("moveBody", ({ event }) => {
        if (!isDragging || !draggedNode || !renderer) return;

        // Get new position of node
        const pos = renderer.viewportToGraph(event);

        graph.setNodeAttribute(draggedNode, "x", pos.x);
        graph.setNodeAttribute(draggedNode, "y", pos.y);

        // Prevent sigma to move camera:
        event.preventSigmaDefault();
        event.original.preventDefault();
        event.original.stopPropagation();
    });

    // On mouse up, we reset the dragging mode
    const handleUp = () => {
        if (draggedNode) {
            graph.removeNodeAttribute(draggedNode, "highlighted");
        }
        isDragging = false;
        draggedNode = null;
    };

    renderer.on("upNode", handleUp);
    renderer.on("upStage", handleUp);

    // When clicking on the stage, we add a new node and connect it to the closest node
    renderer.on("clickStage", ({ event }) => {
        if (!renderer) return;

        const coordForGraph = renderer.viewportToGraph({ x: event.x, y: event.y });

        // We create a new node
        const node = {
            ...coordForGraph,
            size: 10,
            color: chroma.random().hex(),
            label: "新节点"
        };

        // Searching the two closest nodes to auto-create an edge to it
        const closestNodes = graph
            .nodes()
            .map((nodeId) => {
                const attrs = graph.getNodeAttributes(nodeId);
                const distance = Math.pow(node.x - attrs.x, 2) + Math.pow(node.y - attrs.y, 2);
                return { nodeId, distance };
            })
            .sort((a, b) => a.distance - b.distance)
            .slice(0, 2);

        // We register the new node into graphology instance
        const id = uuid();
        graph.addNode(id, node);

        // We create the edges
        closestNodes.forEach((e) => graph.addEdge(id, e.nodeId, { label: "关联" }));
    });
};

// 生命周期钩子
onMounted(() => {
    // 在DOM渲染后再获取容器元素
    const container = document.getElementById("sigma-container");

    if (!container) {
        console.error("Container element not found!");
        return;
    }

    // 初始化示例图谱数据
    const initialNodes: GraphNode[] = [
        { id: "示例节点", label: "点击上方按钮生成知识图谱", x: 0, y: 0, size: 15, color: "#4B96FF" }
    ];

    initialNodes.forEach(node => {
        graph.addNode(node.id, {
            x: node.x,
            y: node.y,
            size: node.size,
            color: node.color,
            label: node.label,
        });
    });

    // 初始示例图仅做短时布局，避免空闲时持续占用
    layout = new ForceSupervisor(graph, { isNodeFixed: (_, attr) => attr.highlighted });
    layout.start();
    layoutStopTimer = setTimeout(() => {
        if (layout) {
            layout.stop();
        }
    }, 800);

    // Create the sigma with settings to enable edge labels
    renderer = new Sigma(graph, container, {
        minCameraRatio: 0.5,
        maxCameraRatio: 2,
        renderLabels: true,
        renderEdgeLabels: true,
        labelRenderedSizeThreshold: 0,
        labelDensity: 3,
        labelGridCellSize: 40,
        edgeLabelSize: 12,
        edgeLabelWeight: "bold"
    });

    // 绑定事件
    bindEvents();

    document.addEventListener("fullscreenchange", () => {
        const container = document.getElementById("sigma-container");
        isFullscreen.value = !!(document.fullscreenElement && container && document.fullscreenElement === container);
        renderer?.refresh();
    });
});
</script>

<style scoped>
.graph-container {
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    width: 100%;
}

button:disabled {
    background-color: #93c5fd;
    cursor: not-allowed;
}

#sigma-container {
    position: relative;
    /* 为绝对定位的子元素提供定位上下文 */
    width: 100%;
    height: 600px;
    /* 固定高度 */
    overflow: hidden;
    /* 隐藏溢出的内容 */
}

#sigma-container:fullscreen {
    width: 100vw !important;
    height: 100vh !important;
    border-radius: 0;
    border: none;
}

#sigma-container:fullscreen :deep(canvas) {
    width: 100% !important;
    height: 100% !important;
}

.legend-list {
    display: flex;
    flex-wrap: wrap;
    gap: 10px 14px;
}

.legend-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: transparent;
    border: 1px solid #e5e7eb;
    border-radius: 9999px;
    padding: 2px 8px;
    cursor: pointer;
}

.legend-item:hover {
    background: #f9fafb;
}

.legend-item-inactive {
    opacity: 0.35;
}

.legend-color-dot {
    width: 10px;
    height: 10px;
    border-radius: 9999px;
    border: 1px solid #d1d5db;
    flex-shrink: 0;
}



#sigma-container :deep(canvas) {
    position: absolute !important;
    top: 0;
    left: 0;
}
</style>
