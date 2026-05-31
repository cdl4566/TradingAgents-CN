# 需求描述
日线通过读取本地 SQLite3 (daily.db) 获取

# 实现方案
在 `tradingagents/dataflows/providers/china/` 下新增 `SQLiteProvider`，继承 `BaseStockDataProvider`。
Market analyst 调用链：`market analyst → toolkit → interface → DataSourceManager → Provider`

实际被调用的接口只有两个：
- `get_historical_data(symbol, start_date, end_date)` — 获取K线/历史行情
- `get_stock_basic_info(symbol)` — 获取股票名称

# 数据库表结构
基于 `pystock/store/sqlite_store.py`，每个股票代码一张表，表名：`tb_` + code.replace('.', '_')

```sql
CREATE TABLE IF NOT EXISTS "tb_000001_SZ" (
  "ts_code" VARCHAR(20),
  "trade_date" VARCHAR(20),
  "open" REAL, "high" REAL, "low" REAL, "close" REAL,
  "pre_close" REAL, "change" REAL, "pct_chg" REAL,
  "vol" REAL, "amount" REAL
);
```

# 实现步骤

1. 创建 `tradingagents/dataflows/providers/china/sqlite.py`，实现 `SQLiteProvider`
   - `connect()`: 连接 daily.db
   - `get_historical_data()`: 按 code 定位表，按日期范围查询
   - `get_stock_basic_info()`: 从表中查 ts_code，返回基础信息
   - `get_stock_data()`: 同步方法，供 get_stock_dataframe 调用
2. 在 `providers/china/__init__.py` 注册 `SQLiteProvider`
3. 在 `tradingagents/constants/data_sources.py` 的 `DataSourceCode` 枚举添加 `SQLITE`
4. 在 `tradingagents/dataflows/data_source_manager.py` 中：
   - `ChinaDataSource` 枚举添加 `SQLITE`
   - `_check_available_sources()` 检测 daily.db 是否存在
   - `_get_sqlite_adapter()` 获取 provider 实例
   - `_get_sqlite_data()` 实现数据获取逻辑
   - `get_stock_data()` / `get_stock_dataframe()` / `_try_fallback_sources()` 添加 SQLITE 分支

# 使用方式
设置环境变量 `DEFAULT_CHINA_DATA_SOURCE=sqlite` 即可将 SQLite 设为首选数据源。
或设置 `SQLITE_DB_PATH` 指定数据库路径（默认 `daily.db`）。

# 关键文件
- Provider: `tradingagents/dataflows/providers/china/sqlite.py`
- 注册: `tradingagents/dataflows/providers/china/__init__.py`
- 枚举: `tradingagents/constants/data_sources.py`
- 管理器: `tradingagents/dataflows/data_source_manager.py`
- 参考结构: `pystock/store/sqlite_store.py`
