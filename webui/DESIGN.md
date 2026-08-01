# WebUI 设计文档

## 设计理念

WebUI 是 Control Plane 的纯前端界面，通过 Control Plane HTTP API 实现对所有管理操作的可视化。它不直接调用 Agent、dnsmasq 或其他底层组件——一切经由 Control Plane 代理。

设计遵循 **极简黑白工业风**：克制色彩、细边框、等宽字体、零装饰。目标是让运维人员一眼看懂集群状态，而非被视觉噪音干扰。

---

## 色彩系统

```
--black:       #000000    主文字
--gray-900:    #1a1a1a    次标题
--gray-800:    #2a2a2a    
--gray-700:    #3a3a3a    
--gray-600:    #555555    辅助文字
--gray-500:    #777777    
--gray-400:    #999999    占位符
--gray-300:    #bbbbbb    禁用的边框
--gray-200:    #dddddd    
--gray-100:    #ebebeb    
--gray-50:     #f4f4f4    
--gray-25:     #fafafa    卡片底色
--white:       #ffffff    页面底色
--border:      #e5e5e5    卡片/输入框边框
--border-light:#f0f0f0    微妙的分割线
```

**交互规则**：hover 时边框从 `--border` 翻转为 `--black`；按钮 hover 时背景填充 `--black`、文字变为 `--white`。不使用任何彩色。

---

## 排版

| 用途 | 字体 | 字号 |
|---|---|---|
| 全局正文 | 等宽（`ui-monospace` / `SFMono` / `Menlo` / `Consolas`） | 14px |
| 导航栏品牌标识 | 等宽 | 13px / 600 weight / 2px letter-spacing |
| 页面标题 | 等宽 | 继承 / 通过 CSS 放大 |
| Badge 标签 | 等宽 | 11px |
| 代码块 | 等宽 | 13px |
| 按钮 | 等宽 | 13px |

所有圆角为 0（`--radius: 0`），过渡动画统一 150ms ease。

---

## 组件库

所有组件为自研纯 CSS 实现，**零第三方 UI 库依赖**。

### Card
- 底色 `--gray-25`，边框 1px `--border`
- 可选 `hover` 模式：hover 时边框变 `--black`
- 支持 onClick，可作可点击卡片

### Button
- `variant`: `primary`（黑底白字）、`secondary`（边框高亮）、`ghost`（透明底灰字）
- 统一等宽字体、1px 黑边框、hover 反转

### Input
- 等宽字体、透明底、1px `--border` 边框
- focus 时边框变黑
- 支持 label / placeholder / name / required

### Select
- 继承 Input 风格
- options 为 `{ value, label }[]` 数组

### Badge
- 用于状态标签（health、state、status）
- 等宽 11px、内边距紧凑

### Divider
- 水平分割线，带可选文字（children）
- 1px `--border` 线

### EmptyState
- 空数据占位提示
- 居中展示，灰色文字

### CodeBlock
- 深色底（`--gray-900`）、等宽字体
- 代码高亮或 IPXE 启动脚本展示

### ConfirmAction
- 内联确认对话框
- 用于危险操作（删除 Worker 等）
- 支持额外 checkbox 选项（如"同时删除 .img"）

---

## 页面结构

### 路由（HashRouter）

```
/                     Dashboard
/workers              Worker 列表 + 创建表单（内联展开）
/workers/:id          Worker 详情（台账 + 实时状态 + 启动变量 + 删除）
/agents               Agent 监控（自适应网格卡片）
/operations           操作审计日志（增量加载）
```

### 布局（Layout）

```
┌──────────────────────────────────────┐
│  IPXE CONTROL PLANE  [nav links]  中/EN │  ← 导航栏 52px，sticky
├──────────────────────────────────────┤
│                                      │
│  <Outlet />                         │  ← 页面内容 max-width 1100px
│                                      │
└──────────────────────────────────────┘
```

导航栏包含：品牌标识 + 4 个导航链接（Dashboard / Workers / Agents / Operations）+ 语言切换（中/EN）。

### Dashboard

- 统计卡片区：Worker 数量 / Agent 健康比例
- 最近操作：最新 10 条操作日志摘要；点击"查看全部"跳转 /operations
- 数据并行加载：`Promise.all([getWorkers, getAgents, getOperations])`

### Workers

- 列表页：表格行（ID / Hostname / OS / State），支持文本筛选
- 内联创建表单：
  - Worker ID、MAC、操作系统、存储节点（Agent 选择器）、磁盘类型
  - 条件字段：母盘名称（type=master）或磁盘大小（type=empty）、Windows ISO（os=windows 时）
  - 表单打开时自动拉取 Agent 列表，过滤出具备 disk 角色的节点
- 点击行进入详情页

### Worker Detail

- 基本信息卡片（Identity）：Worker ID、Hostname、MAC、OS、Arch、State
- 磁盘信息卡片（Disk）：Agent、IQN、Filename、Backing、Source
- 光驱信息卡片（CD-ROM，条件展示）：Agent、IQN、ISO、Backing
- 实时状态探测（Live Status）：dnsmasq 绑定、Disk Target 存在性、CD Target 存在性
- 启动变量预览（Boot Variables）：/boot-vars 返回内容的代码块展示
- 删除操作：内联二次确认（ConfirmAction），可选同时删除 .img 文件和忽略已不存在的 Target

### Agents

- 自适应网格布局（`grid-template-columns: repeat(auto-fill, minmax(320px, 1fr))`）
- 每张卡片展示：
  - Agent ID + 健康状态 Badge
  - 后端类型（stgt / lio）
  - API 地址（base_url）
  - iSCSI 数据面地址（iscsi_server）——从 agents.yml 读取
  - 光驱支持 / 磁盘角色（是/否）
  - 克隆方式 / 新建磁盘方式（中文翻译映射）
  - 标签（tags）
- Live 探测开关：开启时实时访问 Agent /healthz，关闭时仅展示静态配置

### Operations

- 操作日志列表，每行：ID、时间戳、操作类型（op）、状态 Badge、客户端 IP
- 展开详情：额外的 JSON 键值对
- 增量加载："加载更多"按钮，使用 `since` cursor 分页
- 最新日志排在最前面（entries 数组 reverse）

---

## i18n 国际化

### 架构

```
I18nProvider (React Context)
├── useI18n() hook → { t, locale, setLocale }
├── zh-CN.js     中文翻译
└── en-US.js     英文翻译（fallback）
```

### 语言检测

优先级：`localStorage('cp_locale')` → `navigator.language` → `en-US` fallback

### 翻译策略（zh-CN）

- **保留英文**：品牌名、技术名词（Worker、Agent、iSCSI、IQN、MAC、ISO）、导航链接
- **翻译中文**：按钮动词（创建/删除/取消/确认/刷新/加载更多）、表单标签（主机名/操作系统/磁盘类型/存储节点）、状态说明、提示信息、确认对话框
- **能力值翻译**：Agent 的技术描述（如 `reflink (FICLONE)` → `秒级快照 (reflink)`）通过 `capLabels` 映射表翻译

### t() 函数

```js
t('workers.count', { count: 5 })  // → "5 个"
t('agents.capLabels')['reflink (FICLONE) -> shutil.copy fallback']  // → "秒级快照..."
```

---

## API 集成

### 请求封装

```js
// api/client.js
const BASE = '/api/cp'

function getToken() {
  return import.meta.env.VITE_CP_TOKEN || localStorage.getItem('cp_token') || ''
}

async function request(path, options) {
  // 自动拼接 BASE + path
  // 自动附加 Authorization: Bearer <token>
  // 非 2xx 响应解析 error detail 抛出
}
```

### 鉴权

Token 优先级：
1. **构建时注入**：`webui/app/.env` 中 `VITE_CP_TOKEN=xxx`（生产环境推荐）
2. **运行时**：`localStorage.cp_token`（开发调试用，已废弃 UI 输入方式）

### 代理（Vite 开发 vs Nginx 生产）

| 环境 | `/api/cp/*` 代理 | 配置位置 |
|---|---|---|
| `npm run dev` | Vite proxy → Control Plane | `vite.config.js` |
| 生产部署 | nginx `proxy_pass` → Control Plane | `deploy/nginx/nginx.conf` |

---

## 部署架构

### 文件浏览器集成

同一 nginx 容器还承载文件浏览器功能：

| 端点 | 用途 |
|---|---|
| `/` | WebUI SPA（`try_files → index.html`） |
| `/api/cp/*` | Control Plane API 代理 |
| `/browse/` | 文件浏览器 HTML 页面 |
| `/api/browse/*` | njs 目录列表 JSON API |
| `/file/*` | iPXE 文件下载（ISO、kernel、initrd） |

### Docker Compose（仅 WebUI）

```yaml
services:
  nginx:
    build: { dockerfile: Dockerfile }
    ports: ["4838:80"]
    volumes:
      - ../app/dist:/usr/share/nginx/html:ro      # WebUI 静态文件
      - ./www/browse:/usr/share/nginx/browse:ro    # 文件浏览器页面
      - ${PUBLIC_PATH:-./public}:/data:ro           # iPXE 公开文件
```

### 构建命令

```bash
cd webui/app
cp .env.example .env       # 编辑 VITE_CP_TOKEN
npm install
npm run build              # 输出到 dist/
```

---

## 目录结构

```
webui/
├── app/
│   ├── .env                     # 环境变量（VITE_CP_TOKEN），不提交
│   ├── .env.example             # 环境变量模板
│   ├── package.json
│   ├── vite.config.js           # Vite 构建配置 + 开发代理
│   ├── index.html
│   └── src/
│       ├── main.jsx             # 入口：I18nProvider + HashRouter
│       ├── App.jsx              # 路由定义
│       ├── api/
│       │   └── client.js        # API 请求封装（fetch + token）
│       ├── components/          # 通用组件
│       │   ├── Layout.jsx/css   # 导航栏 + 语言切换
│       │   ├── Card.jsx/css     # 卡片容器
│       │   ├── Button.jsx/css   # 按钮
│       │   ├── Input.jsx/css    # 输入框
│       │   ├── Select.jsx/css   # 下拉选择
│       │   ├── Badge.jsx/css    # 状态标签
│       │   ├── Divider.jsx/css  # 分割线
│       │   ├── EmptyState.jsx/css  # 空状态
│       │   ├── CodeBlock.jsx/css   # 代码块
│       │   └── ConfirmAction.jsx/css # 确认对话框
│       ├── pages/               # 页面组件
│       │   ├── Dashboard.jsx/css
│       │   ├── Workers.jsx/css
│       │   ├── WorkerDetail.jsx/css
│       │   ├── Agents.jsx/css
│       │   └── Operations.jsx/css
│       ├── i18n/                # 国际化
│       │   ├── index.jsx        # I18nProvider + useI18n
│       │   ├── zh-CN.js         # 简体中文
│       │   └── en-US.js         # English
│       └── styles/
│           └── global.css       # CSS 变量 + Reset + 字体
│
└── deploy/
    ├── Dockerfile               # nginx:1.27-alpine + njs
    ├── docker-compose.yml
    ├── nginx/
    │   ├── nginx.conf           # 5 个 location 块 + upstream
    │   └── njs/
    │       └── file-list.js     # JSON 目录列表（njs）
    ├── public/                  # iPXE 公开文件目录
    │   └── .gitkeep
    └── www/
        └── browse/
            └── index.html       # 文件浏览器 HTML
```

---

## 技术栈

| 层 | 技术 |
|---|---|
| 框架 | React 18 |
| 构建 | Vite 5 |
| 路由 | React Router 6 (HashRouter) |
| 样式 | 纯 CSS（CSS 变量驱动，零第三方 UI 库） |
| i18n | 自研 React Context（零依赖） |
| API | 原生 fetch（零 HTTP 库） |
| 部署 | nginx:1.27-alpine + njs 模块 |
| 构建产物 | 纯静态文件（HTML + JS + CSS），~193KB gzipped ~62KB |
