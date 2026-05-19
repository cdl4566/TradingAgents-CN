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
            self.conn = sqlite3.connect(self.db_path)
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
        return "tb_" + code.replace('.', '_')

    def _parse_code(self, code: str) -> str:
        """标准化股票代码: 去掉后缀提取6位数字"""
        return code.split('.')[0] if '.' in code else code

    async def get_stock_basic_info(self, code: str = None) -> Optional[Dict[str, Any]]:
        """获取股票基础信息"""
        if not self.connected:
            return None

        clean_code = self._parse_code(code)
        table_name = self._get_table_name(code)

        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cursor.fetchone():
                return None

            # 查最新一条记录获取ts_code
            cursor.execute(f'SELECT ts_code FROM "{table_name}" LIMIT 1')
            row = cursor.fetchone()

            ts_code = row['ts_code'] if row else code
            # 确定市场
            if code.endswith('.SZ') or 'SZ' in code.upper():
                market = "SZ"
            elif code.endswith('.SH') or 'SH' in code.upper():
                market = "SH"
            else:
                market = "SZ" if clean_code.startswith(('0', '3')) else "SH"

            return {
                "code": clean_code,
                "name": f"股票{clean_code}",
                "symbol": clean_code,
                "full_symbol": ts_code if row else f"{clean_code}.{market}",
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
            cursor = self.conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cursor.fetchone():
                logger.warning(f"表 {table_name} 不存在")
                return None

            # 构建查询
            conditions = []
            params = []

            if start_date:
                start_str = str(start_date).replace('-', '')
                start_formatted = f"{start_str[:4]}-{start_str[4:6]}-{start_str[6:8]}"
                conditions.append("trade_date >= ?")
                params.append(start_formatted)

            if end_date:
                end_str = str(end_date).replace('-', '')
                end_formatted = f"{end_str[:4]}-{end_str[4:6]}-{end_str[6:8]}"
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

    def get_stock_data(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """同步获取股票数据（供get_stock_dataframe调用）"""
        if not self.connected:
            return None

        table_name = self._get_table_name(symbol)
        try:
            start_str = str(start_date).replace('-', '')
            end_str = str(end_date).replace('-', '')
            start_formatted = f"{start_str[:4]}-{start_str[4:6]}-{start_str[6:8]}"
            end_formatted = f"{end_str[:4]}-{end_str[4:6]}-{end_str[6:8]}"

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
