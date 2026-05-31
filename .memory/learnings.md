# 经验教训

积累项目经验教训和最佳实践。

*待补充详细内容*

## Market & Fundamentals Analyst 调用链（简要说明）

- **Demo 入口**: `examples/myexamples/demo_ark.py` 创建 `TradingAgentsGraph(selected_analysts=['market','fundamentals'])` 并调用 `propagate()`。
- **TradingAgentsGraph.propagate**: 构建初始状态（由 `Propagator.create_initial_state`）, 调用编译好的 LangGraph 工作流（`self.graph.stream(init_agent_state, ...)`），按节点顺序执行。
- **GraphSetup.setup_graph**: 根据 `selected_analysts` 使用 `create_market_analyst()` 和 `create_fundamentals_analyst()` 创建分析师节点（节点函数接收 `state` 并返回状态片段）。
- **分析师节点实现**:
	- `market_analyst.market_analyst_node(state)`：
		1. 检查并构建上下文（公司名、market_info、instrument_context）。
		2. 绑定工具 `toolkit.get_stock_market_data_unified`，构造提示词并通过 LLM (`llm.bind_tools`) 调用。
		3. 如果 LLM 返回 `tool_calls`，执行对应工具（Toolkit 内部会调 `tradingagents.dataflows.interface` 的统一接口），将工具结果封装为 ToolMessage 并再次调用 LLM 生成最终 `market_report`。
		4. 返回包含 `market_report` 和更新的 `messages` 的状态片段。

	- `fundamentals_analyst.fundamentals_analyst_node(state)`：
		1. 计算固定的数据范围（示例为最近10天）并构建上下文。
		2. 绑定工具 `toolkit.get_stock_fundamentals_unified`，强制或等待 LLM 通过 tool_calls 获得真实数据（实现中有严格的“必须调用工具”及“只调用一次”的策略）。
		3. 工具真实返回（或强制调用）后，分析师会基于 `combined_data` 生成基本面报告 `fundamentals_report` 并返回状态片段。

- **Toolkit → dataflows.interface → DataSourceManager → Provider**:
	- `Toolkit` 中的统一工具（`get_stock_market_data_unified` / `get_stock_fundamentals_unified`）最终会调用 `tradingagents.dataflows.interface` 的对应函数。
	- `dataflows.interface` 使用 `DataSourceManager` 自动选择具体数据源（AKShare、Tushare、SQLite 本地等）。
	- 对于日线数据，若配置或检测到使用本地 SQLite，则会调用 `tradingagents.dataflows.providers.china.sqlite.SQLiteProvider`（环境变量 `SQLITE_DB_PATH` 默认为 `daily.db`）。

- **返回到图流程**: 每个分析师返回的状态片段（如 `market_report`、`fundamentals_report`）会被累积进全局状态，随后进入研究员、交易员与风险评估节点，最终由 `TradingAgentsGraph.process_signal` 生成 `final_trade_decision`。

简要参考路径：

- 分析师实现：[tradingagents/agents/analysts/market_analyst.py](tradingagents/agents/analysts/market_analyst.py)
- 基本面实现：[tradingagents/agents/analysts/fundamentals_analyst.py](tradingagents/agents/analysts/fundamentals_analyst.py)
- Graph 与调度：[tradingagents/graph/trading_graph.py](tradingagents/graph/trading_graph.py#L649-L667)
- GraphSetup：[tradingagents/graph/setup.py](tradingagents/graph/setup.py#L1-L200)
- Toolkit 工具实现（统一工具）：[tradingagents/agents/utils/agent_utils.py](tradingagents/agents/utils/agent_utils.py#L694-L760)
- SQLite Provider（日线数据）：[tradingagents/dataflows/providers/china/sqlite.py](tradingagents/dataflows/providers/china/sqlite.py#L1-L40)

（以上为简要链路说明，便于快速定位实现与排查）

### 数据源选择详解（日线 vs 基本面）

下面补充说明代码中如何决定使用本地 `SQLite`（日线）或 `AKShare`/`Tushare`（基本面/行情）：

- 市场识别（第一步）：先根据股票代码识别市场类型（A股/港股/美股），使用 `StockUtils.identify_stock_market` / `StockUtils.get_market_info`。参见：[tradingagents/utils/stock_utils.py](tradingagents/utils/stock_utils.py#L27) 和 [tradingagents/utils/stock_utils.py](tradingagents/utils/stock_utils.py#L166)。

- 统一入口（第二步）：根据市场路由到不同的统一接口：
	- 中国A股 → `get_china_stock_data_unified`（见：[tradingagents/dataflows/interface.py](tradingagents/dataflows/interface.py#L1909) 和 [tradingagents/dataflows/data_source_manager.py](tradingagents/dataflows/data_source_manager.py#L2208)）。
	- 港股/美股分别走 `get_hk_stock_data_unified` 或美股 provider（见 `get_stock_data_by_market`：[tradingagents/dataflows/interface.py](tradingagents/dataflows/interface.py#L1860)）。

- 数据源管理器（核心决策，第三步）：`DataSourceManager` 负责具体选择与降级逻辑。
	- 默认数据源由环境变量 `DEFAULT_CHINA_DATA_SOURCE`（或启用 MongoDB 缓存时优先为 MongoDB）决定，参见 `_get_default_source()`。
	- 可用数据源通过 `_check_available_sources()` 检查（检测是否安装 `akshare`/`tushare`、以及 `SQLITE_DB_PATH` 指向的文件是否存在），参见：[tradingagents/dataflows/data_source_manager.py](tradingagents/dataflows/data_source_manager.py#L1) 与 `get_stock_data` 的选择逻辑：[tradingagents/dataflows/data_source_manager.py](tradingagents/dataflows/data_source_manager.py#L1068)。

- SQLite 使用条件：
	1. 在系统配置（`system_configs` 的 `data_source_configs`）或运行时配置中启用了 `sqlite`；
	2. 环境变量 `SQLITE_DB_PATH` 指定的文件存在（默认 `daily.db`）；
	3. 当 `DataSourceManager.current_source` 被设置为 `SQLITE`（或作为降级候选）时，会调用 `SQLiteProvider` 读取日线，参见实现：[tradingagents/dataflows/providers/china/sqlite.py](tradingagents/dataflows/providers/china/sqlite.py#L1-L40)。

- 基本面（fundamentals）优先使用逻辑：
	- `DataSourceManager.get_fundamentals_data()` 会根据 `current_source` 优先从 MongoDB → Tushare → AKShare 获取基本面；若这些失败，会调用降级逻辑或生成分析，参见：[tradingagents/dataflows/data_source_manager.py](tradingagents/dataflows/data_source_manager.py#L320)。
	- 实际优先级亦受数据库配置（`data_source_configs`）与环境变量影响；当数据质量或调用失败时，管理器使用 `_try_fallback_sources()` 按市场/优先级顺序降级到其它已启用的数据源（包括 `sqlite` 作为备用），参见：[tradingagents/dataflows/data_source_manager.py](tradingagents/dataflows/data_source_manager.py#L1447)。

- 总结（什么时候用 sqlite，什么时候用 akshare/tushare）：
	- 日线/历史行情：若本地 `daily.db` 存在且 `sqlite` 已启用，则 `SQLiteProvider` 常用于快速离线或本地缓存场景；否则优先使用 AKShare/Tushare 等在线提供器。
	- 基本面数据：通常由 Tushare 或 AKShare 提供（取决于 `current_source` 与配置），`SQLite` 更常作为行情缓存/备用而不是首选的基本面数据提供者。

### 相关代码快速定位
- 市场识别： [tradingagents/utils/stock_utils.py](tradingagents/utils/stock_utils.py#L27)
- 统一入口： [tradingagents/dataflows/interface.py](tradingagents/dataflows/interface.py#L1860) 、 [tradingagents/dataflows/interface.py](tradingagents/dataflows/interface.py#L1909)
- 决策与降级： [tradingagents/dataflows/data_source_manager.py](tradingagents/dataflows/data_source_manager.py#L1068) 、 [tradingagents/dataflows/data_source_manager.py](tradingagents/dataflows/data_source_manager.py#L1447)
- SQLite provider 实现： [tradingagents/dataflows/providers/china/sqlite.py](tradingagents/dataflows/providers/china/sqlite.py#L1-L40)
