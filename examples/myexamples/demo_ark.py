import os
import sys
from pathlib import Path
from datetime import date

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
import argparse
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# 加载 .env 文件
load_dotenv()


def main():
    """使用智谱 AI GLM 模型演示 TradingAgents 简化分析。"""
    # 先校验必需的命令行参数，避免在初始化前做大量工作
    parser = argparse.ArgumentParser(description="Run TradingAgents demo for a specific stock")
    parser.add_argument('--code', '-c', required=True, help='股票代码（例：002049 或 600519）')
    args = parser.parse_args()
    stock_symbol = str(args.code).strip().zfill(6)
    if not stock_symbol:
        print('❌ 必须提供股票代码参数 --code')
        return
    print('环境变量加载检查:')
    print(f"ZHIPUAI_API_KEY: {os.getenv('ZHIPUAI_API_KEY')}")
    print(f"CUSTOM_OPENAI_API_KEY: {os.getenv('CUSTOM_OPENAI_API_KEY')}")
    print()

    zhipuai_key = os.getenv('ZHIPUAI_API_KEY')
    if not zhipuai_key:
        print('❌ 未找到 ZHIPUAI_API_KEY 环境变量，请先在 .env 中配置智谱 AI API Key。')
        print('可使用示例: ZHIPUAI_API_KEY=your_zhipuai_api_key')
        return

    # 兼容 TradingAgentsGraph 的 custom_openai 分支
    if not os.getenv('CUSTOM_OPENAI_API_KEY'):
        os.environ['CUSTOM_OPENAI_API_KEY'] = zhipuai_key

    print(f'✅ 已读取智谱 AI API Key，长度: {len(zhipuai_key)}')
    print()

    config = DEFAULT_CONFIG.copy()
    config['llm_provider'] = 'custom_openai'
    config['custom_openai_base_url'] = 'https://open.bigmodel.cn/api/paas/v4/'
    config['deep_think_llm'] = 'glm-4-flash'
    config['quick_think_llm'] = 'glm-4-flash'
    config['max_debate_rounds'] = 1
    config['memory_enabled'] = False
    config['online_tools'] = False

    # 仅启用两种分析师：市场分析师 + 基本面分析师
    # selected_analysts = ['market', 'fundamentals']
    selected_analysts = ['market']

    print('📊 当前演示配置:')
    print(f"  llm_provider: {config['llm_provider']}")
    print(f"  custom_openai_base_url: {config['custom_openai_base_url']}")
    print(f"  quick_think_llm: {config['quick_think_llm']}")
    print(f"  deep_think_llm: {config['deep_think_llm']}")
    print(f"  selected_analysts: {selected_analysts}")
    print('  memory_enabled: False')
    print('  online_tools: False')
    print()

    try:
        print('🤖 正在初始化 TradingAgentsGraph...')
        ta = TradingAgentsGraph(debug=True, config=config, selected_analysts=selected_analysts)
        print('✅ TradingAgentsGraph 初始化成功')
        print()

        # 所有数据（市场+基本面）统一走 SQLite，不依赖 AKShare
        try:
            from tradingagents.dataflows.data_source_manager import get_data_source_manager, ChinaDataSource

            mgr = get_data_source_manager()
            mgr.set_current_source(ChinaDataSource.SQLITE)
            print('🔧 数据源统一设置为 SQLite（市场+基本面均走本地）')

        except Exception as e:
            print('⚠️ 配置数据源时发生错误:', e)

        # 校验 LLM 配置是否指向 Ark (custom_openai)
        try:
            llm_provider = ta.config.get('llm_provider')
            print(f'🔍 LLM Provider 配置: {llm_provider}')
            if llm_provider != 'custom_openai':
                print('⚠️ 注意：llm_provider 未设置为 custom_openai，可能不是智谱 AI')
            else:
                print('✅ llm_provider 为 custom_openai，继续检查环境与模型信息...')
                print(f"  CUSTOM_OPENAI_API_KEY 存在: {bool(os.getenv('CUSTOM_OPENAI_API_KEY'))}")
                print(f"  custom_openai_base_url: {ta.config.get('custom_openai_base_url')}")
                try:
                    deep = getattr(ta, 'deep_thinking_llm', None)
                    quick = getattr(ta, 'quick_thinking_llm', None)
                    deep_name = getattr(deep, 'model_name', None) or deep.__class__.__name__ if deep else None
                    quick_name = getattr(quick, 'model_name', None) or quick.__class__.__name__ if quick else None
                    print(f'  深度模型: {deep_name}, 快速模型: {quick_name}')
                except Exception as e:
                    print('  无法读取 LLM 实例详情:', e)
        except Exception as e:
            print('⚠️ 校验 LLM 配置时发生错误:', e)

        analysis_date = date.today().isoformat()

        print(f'📈 开始分析: {stock_symbol} ({analysis_date})')
        print('⏳ 请稍等，正在执行简化分析流程...')
        state, decision = ta.propagate(stock_symbol, analysis_date)

        print('\n🎯 分析结果:')
        print('----------------------------------------')
        print(f'决策: {decision}')
        print('----------------------------------------')
        print('🧾 最终状态摘要:')
        for key, value in state.items():
            if key in ['market_report', 'fundamentals_report', 'final_trade_decision']:
                print(f'  {key}: {value}')
        print('\n✅ 演示完成！')
        print('提示: 如需更少分析师，可将 selected_analysts 改为 ["fundamentals"] 或 ["market"]。')

    except Exception as e:
        print(f'❌ 运行失败: {e}')
        import traceback
        traceback.print_exc()
        print('\n请确认:')
        print('  1. 已在 .env 中配置 ZHIPUAI_API_KEY')
        print('  2. 智谱 AI 端点可访问')
        print('  3. 模型名支持 glm-4-flash')


if __name__ == '__main__':
    main()
