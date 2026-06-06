"""
SQLite本地数据提供器 - 从daily.db读取日线数据
基于sqlite_store.py结构，每个股票代码对应独立表
表名规则：tb_ + code.replace('.', '_')，如 tb_000001_SZ
"""
from typing import Optional, Dict, Any, List, Union
from datetime import datetime, date
import logging
import sqlite3
import pandas as pd
import os

from ..base_provider import BaseStockDataProvider

logger = logging.getLogger(__name__)


class SQLiteProvider(BaseStockDataProvider):
    """SQLite本地数据提供器"""

    def __init__(self, db_path: str = None):
        super().__init__(provider_name="sqlite")
        self.db_path = db_path or os.getenv("SQLITE_DB_PATH", "daily.db")
        self.conn = None

    async def connect(self) -> bool:
        """连接SQLite数据库"""
        try:
            if not os.path.exists(self.db_path):
                logger.warning(f"SQLite数据库文件不存在: {self.db_path}")
                self.connected = False
                return False
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.connected = True
            logger.info(f"SQLite连接成功: {self.db_path}")
            return True
        except Exception as e:
            logger.error(f"SQLite连接失败: {e}")
            self.connected = False
            return False

    async def disconnect(self):
        """断开连接"""
        if self.conn:
            self.conn.close()
            self.conn = None
        self.connected = False

    def _get_table_name(self, code: str) -> str:
        """股票代码 -> 表名: 000001.SZ -> tb_000001_SZ"""
        if not code:
            return ""

        c = str(code).strip()

        # If code has no market suffix, try to infer it from prefix
        if '.' not in c:
            if c.startswith('6'):
                c = c + '.SH'
            elif c.startswith(('0', '3')):
                c = c + '.SZ'
            elif c.startswith('920'):
                c = c + '.BJ'
            else:
                # default to SZ for unknown prefixes
                c = c + '.SZ'

        # Replace dot with underscore and normalize to upper for suffix
        return "tb_" + c.replace('.', '_').upper()

    def _parse_code(self, code: str) -> str:
        """标准化股票代码: 去掉后缀提取6位数字"""
        return code.split('.')[0] if '.' in code else code

    async def get_stock_basic_info(self, code: str = None) -> Optional[Dict[str, Any]]:
        """获取股票基础信息"""
        if not self.connected:
            return None

        clean_code = self._parse_code(code)

        try:
            # 优先使用写死的股票信息
            info = self._HARDCODED_STOCK_INFO.get(clean_code)
            if info:
                return dict(info)

            # 确定市场
            if clean_code.startswith('6'):
                market = "SH"
            elif clean_code.startswith(('0', '3')):
                market = "SZ"
            else:
                market = "SZ"

            return {
                "code": clean_code,
                "name": f"股票{clean_code}",
                "symbol": clean_code,
                "market": market,
                "industry": "未知",
                "area": "未知",
                "list_date": "",
                "data_source": "sqlite",
            }
        except Exception as e:
            logger.error(f"获取股票基础信息失败: {e}")
            return None

    async def get_stock_quotes(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取最新行情（从最新一条日线数据）"""
        if not self.connected:
            return None

        table_name = self._get_table_name(symbol)
        try:
            cursor = self.conn.cursor()
            query = f'SELECT * FROM "{table_name}" ORDER BY trade_date DESC LIMIT 1'
            cursor.execute(query)
            row = cursor.fetchone()
            if not row:
                return None

            d = dict(row)
            clean_code = self._parse_code(symbol)
            return {
                "code": clean_code,
                "symbol": clean_code,
                "close": d.get("close"),
                "open": d.get("open"),
                "high": d.get("high"),
                "low": d.get("low"),
                "pre_close": d.get("pre_close"),
                "pct_chg": d.get("pct_chg"),
                "volume": d.get("vol"),
                "amount": d.get("amount"),
                "trade_date": d.get("trade_date"),
                "data_source": "sqlite",
            }
        except Exception as e:
            logger.error(f"获取行情失败: {e}")
            return None

    async def get_historical_data(
        self,
        symbol: str,
        start_date: Union[str, date],
        end_date: Union[str, date] = None,
        period: str = "daily"
    ) -> Optional[pd.DataFrame]:
        """获取历史日线数据"""
        if not self.connected:
            return None

        table_name = self._get_table_name(symbol)

        try:
            # 构建查询
            conditions = []
            params = []

            if start_date:
                start_formatted = str(start_date).replace('-', '')
                conditions.append("trade_date >= ?")
                params.append(start_formatted)

            if end_date:
                end_formatted = str(end_date).replace('-', '')
                conditions.append("trade_date <= ?")
                params.append(end_formatted)

            where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

            query = f'SELECT * FROM "{table_name}"{where_clause} ORDER BY trade_date'

            df = pd.read_sql(query, self.conn, params=params)

            if df.empty:
                return None

            # 标准化列名: vol -> volume (保持与DataSourceManager兼容)
            if 'vol' in df.columns and 'volume' not in df.columns:
                df = df.rename(columns={'vol': 'volume'})

            return df

        except Exception as e:
            logger.error(f"获取历史数据失败: {e}")
            return None

    # ==================== 同步便捷方法（供DataSourceManager直接调用） ====================

    # TODO: 后续从本地 stock_basic_info 表或 JSON 文件读取，目前先写死
    _HARDCODED_STOCK_INFO = {
        "002049": {
            "symbol": "002049",
            "name": "紫光国微",
            "industry": "半导体",
            "area": "北京",
            "list_date": "2005-06-16",
            "market": "SZ",
            "source": "sqlite",
        },
    }

    def get_stock_info(self, symbol: str) -> Dict[str, Any]:
        """同步获取股票基本信息（供 DataSourceManager.get_stock_info 调用）"""
        info = self._HARDCODED_STOCK_INFO.get(symbol)
        if info:
            return dict(info)  # 返回副本，避免外部修改
        # 未写死的股票，返回默认值（会被判定为无效，触发降级到 AKShare）
        return {"symbol": symbol, "name": f"股票{symbol}", "industry": "未知", "area": "未知", "list_date": "未知", "market": "未知", "source": "sqlite"}

    def get_stock_data(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """同步获取股票数据（供get_stock_dataframe调用）"""
        if not self.connected:
            return None

        table_name = self._get_table_name(symbol)
        try:
            start_formatted = str(start_date).replace('-', '')
            end_formatted = str(end_date).replace('-', '')

            query = f'SELECT * FROM "{table_name}" WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date'
            df = pd.read_sql(query, self.conn, params=[start_formatted, end_formatted])

            if df.empty:
                return None

            if 'vol' in df.columns and 'volume' not in df.columns:
                df = df.rename(columns={'vol': 'volume'})

            return df
        except Exception as e:
            logger.error(f"同步获取数据失败: {e}")
            return None


# ==================== 单例 ====================

_sqlite_provider = None


def get_sqlite_provider() -> SQLiteProvider:
    """获取全局SQLite提供器实例"""
    global _sqlite_provider
    if _sqlite_provider is None:
        _sqlite_provider = SQLiteProvider()
        # 同步初始化连接
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在已有事件循环中，使用run_in_executor
                pass
            else:
                loop.run_until_complete(_sqlite_provider.connect())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_sqlite_provider.connect())
    return _sqlite_provider
