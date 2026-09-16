# 多版套色木刻 · 图层叠压次序审计台

残存的套色痕迹只能说明「某色层应压在另一层之上」。痕迹污损、互相冲突时，
按局部最高权重贪心放置会错过全局最优次序。本项目从空白仓库实现一个全栈审计台：

- **后端**：FastAPI + Pydantic，使用**精确整数子集动态规划**求全局最低违背代价；
  不使用贪心，也不调用任何外部/通用求解器。
- **前端**：React + TypeScript + Vite，以 **SVG 层叠轨道**展示见证，并逐条
  复算每条观察的违背状态与代价。
- **编排**：Docker Compose 运行 `web`（nginx 托管 SPA 并反代 API）、`api`
  （FastAPI）和一次性 `verify` 验收容器。

## 问题定义

- 输入 2–20 个**唯一**图层，标识匹配 `[A-Za-z0-9_-]{1,24}`。
- 至少 1 条有向观察 `lower → upper`，权重为 1–1,000,000 的**严格整数**。
- 排列按**从底到顶**解释；对观察 `lower → upper`，若 `upper` 未严格位于
  `lower` 之后（即 `pos(upper) <= pos(lower)`），则该观察被违背，计入其权重。
- 目标：最小化违背权重总和。

非法输入一次返回**全部**错误（空观察数组、重复标识、悬空引用、自环、重复有向对、
数量越界、标识格式、权重范围/类型、多余字段、坏 JSON），按
[JSON Pointer](https://www.rfc-editor.org/rfc/rfc6901)（如 `/observations/3/upper`）
字典序排序，HTTP 422；前端收到非法响应会**清除旧结果**。

## 算法：精确整数子集 DP（非贪心）

按底到顶构造排列。设前缀已放置集合为掩码 `S`，把图层 `j` 放到当前最顶时，
所有以上层 `j` 为终点、且其下层不在 `S` 中的观察都必然被违背（该下层只能更晚、
即更靠上出现）：

```
add(j, S) = Σ w  (对所有边 lower → j 且 lower ∉ S)
```

代价只依赖于 `S`，因此对全部 2ⁿ 个掩码做 DP：

```
dp[S ∪ {j}] = min  dp[S] + add(j, S)
```

- 所有代价用 Python 任意精度整数运算；20 层、权重 10⁶ 时总和约 2×10¹⁴，精确无浮点。
- 并列时对每个掩码只保留 ASCII 字典序最小的**两条不同**最优前缀（实现上把按
  ASCII 排序后的标识排名存成 `bytes`，字节序比较与「逐项比较标识 ASCII 字节序」
  完全等价），最终：
  - 唯一最优 → `"status": "unique"`，返回唯一排列；
  - 存在并列 → `"status": "ambiguous"`，返回最小的两条不同最优排列，代价相同。

### 为什么不是贪心（陷阱）

示例 `backend/tests` 与前端「载入示例」内置同一用例（4 层）：

| 观察 | 权重 | 观察 | 权重 |
|---|--|---|--|
| A→B | 8 | B→C | 7 |
| A→C | 1 | C→A | 1 |
| A→D | 3 | C→D | 8 |
| B→A | 1 | D→A | 9 |

- 每步选「当前增量代价最小」的贪心得到 `B,C,D,A`，代价 **12**；
- 子集 DP 全局最优为 `A,B,C,D`，代价 **11**，且唯一。

## 重排不变性

排列/代价只取决于图层与观察的**集合**。服务端内部按 ASCII 规范化标识排名、
按 `(lower, upper)` ASCII 序输出见证明细行；因此打乱 `layers` 或 `observations`
的输入顺序，状态、总代价、最优排列与规范见证完全不变（有测试与验收覆盖）。

## 目录结构

```
.
├── backend/            FastAPI + Pydantic + 子集 DP
│   ├── app/solver.py   精确整数子集 DP（2ⁿ 掩码，保留两条 ASCII 最小最优）
│   │                   + placement_profile（前缀/后缀两次 2ⁿ⁻¹ DP 拼出全深度剖面）
│   ├── app/models.py   模式与跨字段全量校验
│   ├── app/main.py     POST /api/solve、POST /api/placement-profile、GET /api/health
│   └── tests/          全排列穷举核对、贪心陷阱、非等权环、对称并列、重排不变、剖面
├── frontend/           React + TS + Vite
│   └── src/components/ StackTrack.tsx（SVG 轨道，图层可点击）、ObservationTable.tsx、
│                       ProfilePanel.tsx（派生的层位敏感性剖面区域）
├── web/                nginx 镜像（托管 dist + 反代 /api）
├── verify/             一次性验收：pytest 全量 + 端到端 HTTP 验收
└── docker-compose.yml
```

## 运行方式

### 方式一：Docker Compose（推荐，含验收）

```bash
docker compose build
docker compose up -d web        # 启动 api 与 web
# 网页：http://localhost:8080
# API 健康检查：http://localhost:8000/api/health（另含 /docs）

docker compose run --rm verify  # 一次性验收：穷举测试 + 134 项端到端检查
```

`verify` 服务不会常驻：先运行后端全部 pytest（含小规模全排列穷举核对 DP），
再对运行中的 `web`/`api` 做端到端验收，全部通过时退出码为 0。
也可一条命令完成：`docker compose up --build --abort-on-container-exit --exit-code-from verify verify`
（会自动拉起 `api`、`web`，验收结束后退出）。

### 方式二：本地开发

后端：

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
pytest -q
```

前端：

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173 ，/api 已代理到 localhost:8000
npm run build    # 类型检查 + 产物到 dist/
```

## API 摘要

`POST /api/solve`

```json
{
  "layers": ["A", "B", "C", "D"],
  "observations": [
    {"lower": "A", "upper": "B", "weight": 8}
  ]
}
```

成功（200）返回 `status`、精确整数 `cost`、`order`（底→顶）、`witness`
（含 `order`、`cost` 与每条观察的位置/是否违背/代价，求和即总代价）；
`ambiguous` 时额外返回 `second_cost`、`second_order`、`second_witness`。

失败（422）：

```json
{ "errors": [ { "pointer": "/observations/3/upper", "message": "dangling reference to unknown layer 'X'" } ] }
```

`POST /api/placement-profile`（层位敏感性剖面）

装帧限制可能把某块色版钉死在指定深度。点击规范见证 SVG 中的任一图层后，
前端以**原 ProblemIn 数据加一个 `target`** 调用本端点，一次返回该图层落在
**每个**深度（0 = 最底层）时的最低总代价、相对原全局最优的增量 `delta`，
以及该深度下 ASCII 字典序最小的排列：

```json
{
  "target": "C",
  "optimal_cost": 11,
  "depths": [
    {"depth": 0, "cost": 12, "delta": 1, "order": ["C", "D", "A", "B"]},
    {"depth": 2, "cost": 11, "delta": 0, "order": ["A", "B", "C", "D"]}
  ]
}
```

- 返回的深度行数恒等于图层数，且每行 `order[depth] === target`；
  `delta >= 0`，至少一个深度 `delta === 0`（全局最优必把目标放在某个深度）。
- 算法**不逐深度重复 solve**：对其余 n−1 层做一遍底→顶的前缀 DP
  （目标作为始终在其上方的虚拟下层）和一遍顶→底的“剥离”后缀 DP，
  每个可行前缀子集把两侧缓存状态拼接一次即得该深度剖面；复用同一套
  精确整数代价与 ASCII 排名规则。n=20 全双向图的整条剖面与一次 solve
  同量级（两条 2ⁿ⁻¹ 扫描 ≈ 一条 2ⁿ 扫描）。
- 未知 `target` 返回指向 `/target` 的 422（与其他校验错误合并、按
  JSON Pointer 排序）；剖面加载/成功/失败只更新前端派生区域，
  原求解见证保留；再次成功提交主问题会清除旧剖面。
- 小规模用例同样以 n! 全排列独立核对每个深度的代价与字典序最小排列
  （后端 pytest 与 `verify` 端到端验收均覆盖）。

## 测试与质量约束

- 小规模（n=2/3 全部图结构、n=4 大量随机实例）对 **n! 全排列穷举**独立核对 DP 的
  最优代价与 ASCII 最小两条排列；
- 覆盖**贪心陷阱**（唯一最优，贪心更差）、**非等权环**（打破最便宜的边）、
  **对称并列**（两条 ASCII 最小最优）、重排不变、错误合并与 JSON Pointer 排序、
  严格整数与大权重精确性、20 层性能上限；
- 验收脚本仅用 Python 标准库，在容器网络内走 nginx 全链路验证。
