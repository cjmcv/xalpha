import gradio as gr
from pyecharts.charts import Bar, Line, Pie
from pyecharts import options as opts
from pyecharts.globals import ThemeType
import random
import tempfile
import os
import socket
import pandas as pd
import xalpha as xa
import html
import sys
from datetime import datetime


# ==================== 公共工具函数 ====================
def get_network_info():
    """获取网络信息"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return f"WSL IP: {ip}"
    except:
        return "请手动查看WSL IP: ip addr show | grep eth0"


def chart_to_html(chart):
    """将Pyecharts图表转换为HTML"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        temp_path = f.name
    
    chart.render(temp_path)
    
    with open(temp_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    os.unlink(temp_path)
    
    fixed_html = html_content.replace(
        '<head>',
        '<head><script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>'
    )
    
    return f"""
    <div style="width:100%; height:550px; border:1px solid #ddd; border-radius:10px; overflow:hidden; background:white;">
        <iframe srcdoc='{html.escape(fixed_html)}' style="width:100%; height:100%; border:none;"
                sandbox="allow-scripts allow-same-origin allow-popups allow-forms"></iframe>
    </div>
    """


def get_fund_data(fund_code):
    """获取基金历史净值数据"""
    import akshare as ak
    df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
    df = df.sort_values('净值日期', ascending=False).reset_index(drop=True)
    df['日增长率'] = pd.to_numeric(df['日增长率'])
    return df


def format_percentage(value, with_emoji=True):
    """格式化百分比显示"""
    if value is None:
        return "--"
    if with_emoji:
        if value > 0:
            return f"📈 +{value:.2f}%"
        elif value < 0:
            return f"📉 {value:.2f}%"
        else:
            return f"➡️ 0.00%"
    else:
        return f"{value:+.2f}%"


# ==================== 图表创建函数 ====================
def create_chart(code):
    """创建指数净值曲线图"""
    zzhli = xa.indexinfo(code)
    zzhli.bcmkset(xa.indexinfo("SH000300"), start="2014-01-01")
    return zzhli.v_netvalue(rendered=False)


def create_holdings():
    """创建持仓组合图"""
    path = "./tests/cmb_holdings.csv"
    from xalpha.record_ext import from_positions, mulfix_pos
    read = from_positions(path, skiprows=0)
    sysopen = mulfix_pos(status=read)
    return sysopen.v_positions(rendered=False)


def get_random_line_chart():
    """生成随机折线图"""
    weeks = ['第一周', '第二周', '第三周', '第四周', '第五周']
    users = [random.randint(500, 2000) for _ in range(5)]
    
    return (Line(init_opts=opts.InitOpts(width="800px", height="500px", 
                                          theme=ThemeType.MACARONS, bg_color='white'))
            .add_xaxis(weeks)
            .add_yaxis("活跃用户数", users, is_smooth=True)
            .set_global_opts(title_opts=opts.TitleOpts(title="📈 周活跃用户趋势"),
                           yaxis_opts=opts.AxisOpts(name="用户数"),
                           xaxis_opts=opts.AxisOpts(name="周次"),
                           toolbox_opts=opts.ToolboxOpts(is_show=True))
            .set_series_opts(label_opts=opts.LabelOpts(is_show=True)))


# ==================== 数字功能函数 ====================
def get_positions_data():
    """获取持仓数据"""
    path = "./tests/cmb_holdings.csv"
    from xalpha.record_ext import from_positions, mulfix_pos
    read = from_positions(path, skiprows=0)
    sysopen = mulfix_pos(status=read)
    return sysopen, sysopen.combsummary()


def func_1():
    """显示持仓组合摘要信息"""
    try:
        sysopen, summary_df = get_positions_data()
        
        # 使用 Markdown 表格
        result = "📊 **持仓组合摘要**\n\n"
        result += "| 产品代码 | 简称 | 基金份额 | 单位净值 | 总成本 | 参考市值 | 浮动盈亏 | 收益率 | 占比 |\n"
        result += "|----------|------|----------|----------|--------|----------|----------|--------|------|\n"
        
        for _, row in summary_df.iterrows():
            profit_rate = format_percentage(row['收益率'], with_emoji=False)
            result += f"| {row['产品代码']} | {row['简称']} | {row['基金份额']:.2f} | {row['单位净值']:.4f} | "
            result += f"{row['总成本']:.2f} | {row['参考市值']:.2f} | {row['浮动盈亏']:.2f} | {profit_rate} | {row['占比']:.2f}% |\n"
        
        # 汇总信息
        total_market = summary_df['参考市值'].sum()
        total_cost = summary_df['总成本'].sum()
        total_profit = total_market - total_cost
        total_rate = (total_profit / total_cost * 100) if total_cost > 0 else 0
        
        result += f"\n---\n\n**📈 组合汇总**\n\n"
        result += f"- **总市值**: {total_market:.2f} 元\n"
        result += f"- **总成本**: {total_cost:.2f} 元\n"
        result += f"- **总盈亏**: {format_percentage(total_profit, with_emoji=False)} 元\n"
        result += f"- **总收益率**: {format_percentage(total_rate, with_emoji=False)}\n"
        
        return result
    except Exception as e:
        return f"❌ 读取持仓信息失败: {str(e)}"

def func_2():
    """显示指定基金的净值变化（横向展示）"""
    try:
        # 指定要查询的基金代码
        target_fund_code = "020989"  # 南方恒生科技ETF
        
        # 获取func3的完整数据
        sysopen, summary_df = get_positions_data()
        category_config = sysopen.category_config
        
        # 分类基金
        fund_categories = {}
        for _, row in summary_df.iterrows():
            fund_name = row['简称']
            fund_code = row['产品代码']
            
            # 截断基金名称
            if len(fund_name) > 11:
                fund_name = fund_name[:11] + "..."
            
            # 查找分类
            cat = "其他"
            for cat_name, config in category_config.items():
                if config["keywords"] and any(k in fund_name for k in config["keywords"]):
                    cat = cat_name
                    break
            
            if cat not in fund_categories:
                fund_categories[cat] = []
            fund_categories[cat].append({"code": fund_code, "name": fund_name})
        
        # 查找目标基金
        target_fund = None
        for cat_name, funds in fund_categories.items():
            for fund in funds:
                if fund["code"] == target_fund_code:
                    target_fund = fund
                    target_category = cat_name
                    break
            if target_fund:
                break
        
        if not target_fund:
            return f"❌ 未找到基金代码: {target_fund_code}"
        
        # 获取基金历史数据
        try:
            import akshare as ak
            # 直接获取数据
            df = ak.fund_open_fund_info_em(
                symbol=target_fund_code,
                indicator="单位净值走势"
            )
            
            # 数据处理
            df['净值日期'] = pd.to_datetime(df['净值日期'])
            df = df.sort_values('净值日期', ascending=False).reset_index(drop=True)
            df['单位净值'] = pd.to_numeric(df['单位净值'], errors='coerce')
            
            # 定义要查询的时间点
            intervals = [40, 20, 10, 5, 3, 1]
            interval_names = ["40日前", "20日前", "10日前", "5日前", "3日前", "最新"]
            
            # 准备数据
            data_rows = []
            for days, name in zip(intervals, interval_names):
                if len(df) >= days:
                    nav = df.iloc[days-1]['单位净值']
                    date = df.iloc[days-1]['净值日期'].strftime('%m-%d')
                    data_rows.append({
                        "时间点": name,
                        "日期": date,
                        "净值": nav
                    })
            
            # 输出表格（横向展示）
            result = f"📈 **基金净值变化 - {target_fund['name']} ({target_fund['code']})**\n\n"
            result += f"分类: {target_category}\n"
            result += f"数据截止: {df.iloc[0]['净值日期'].strftime('%Y-%m-%d')}\n\n"
            
            # 构建横向表格
            result += "| 时间点 |"
            for row in data_rows:
                result += f" {row['时间点']} |"
            result += "\n"
            
            result += "|--------|"
            for _ in data_rows:
                result += "------|"
            result += "\n"
            
            result += "| 日期 |"
            for row in data_rows:
                result += f" {row['日期']} |"
            result += "\n"
            
            result += "| 净值 |"
            for row in data_rows:
                result += f" {row['净值']:.4f} |"
            result += "\n"
            
            # 添加涨跌幅行
            latest_nav = data_rows[-1]['净值']
            result += "| 涨跌幅 |"
            for row in data_rows[:-1]:  # 最后一个是最新，不计算
                change = (latest_nav - row['净值']) / row['净值'] * 100
                if change > 0:
                    change_str = f'<span style="color: red; font-weight: bold;">+{change:.2f}%</span>'
                elif change < 0:
                    change_str = f'<span style="color: green; font-weight: bold;">{change:.2f}%</span>'
                else:
                    change_str = '<span style="color: gray;">0.00%</span>'
                result += f" {change_str} |"
            result += " - |"  # 最新的涨跌幅列留空
            
            return result
            
        except Exception as e:
            return f"❌ 获取基金数据失败: {str(e)}"
        
    except Exception as e:
        return f"❌ 查询失败: {str(e)}"


def func_3():
    """显示持仓基金近期涨跌幅统计"""
    try:
        sysopen, summary_df = get_positions_data()
        category_config = sysopen.category_config
        
        # 分类基金
        fund_categories = {}
        for _, row in summary_df.iterrows():
            fund_name = row['简称']
            fund_code = row['产品代码']
            
            # 查找分类
            cat = "其他"
            for cat_name, config in category_config.items():
                if config["keywords"] and any(k in fund_name for k in config["keywords"]):
                    cat = cat_name
                    break
                
            # 截断基金名称，只保留前11个字符
            if len(fund_name) > 11:
                fund_name = fund_name[:11] + "..."

            if cat not in fund_categories:
                fund_categories[cat] = []
            fund_categories[cat].append({"code": fund_code, "name": fund_name})
        
        # 筛选：二级债基全部，其他只取第一只
        intervals = [("40日", 40), ("20日", 20), ("10日", 10), ("5日", 5), ("3日", 3)]
        table_data = []
        
        for cat_name, funds in fund_categories.items():
            funds_to_show = funds if cat_name == "二级债基" else funds[:1]
            
            for fund in funds_to_show:
                try:
                    import akshare as ak
                    # 获取基金历史净值数据
                    df = ak.fund_open_fund_info_em(
                        symbol=fund["code"],
                        indicator="单位净值走势"
                    )
                    
                    # 确保数据是DataFrame且非空
                    if df is None or df.empty:
                        continue
                    
                    # 转换日期列和数值列
                    df['净值日期'] = pd.to_datetime(df['净值日期'])
                    df = df.sort_values('净值日期', ascending=False).reset_index(drop=True)
                    df['单位净值'] = pd.to_numeric(df['单位净值'], errors='coerce')
                    
                    # 检查数据长度
                    if len(df) < 3:
                        continue
                    
                    # 使用净值直接计算涨跌幅（40日、20日、10日、5日、3日）
                    latest_nav = df.iloc[0]['单位净值']
                    changes = []
                    for _, num_days in intervals:
                        if len(df) >= num_days:
                            nav_ago = df.iloc[num_days-1]['单位净值']
                            change = (latest_nav - nav_ago) / nav_ago * 100
                            changes.append(change)
                        else:
                            changes.append(None)
                    
                    # 1日涨跌幅使用日增长率
                    df['日增长率'] = pd.to_numeric(df['日增长率'], errors='coerce')
                    one_day_change = df.iloc[0]['日增长率'] if len(df) >= 1 and not pd.isna(df.iloc[0]['日增长率']) else None
                    
                    # 日期格式
                    latest_date = df.iloc[0]['净值日期'].strftime('%m-%d') if hasattr(df.iloc[0]['净值日期'], 'strftime') else str(df.iloc[0]['净值日期'])[5:]
                    
                    table_data.append({
                        "category": cat_name,
                        "code": fund["code"],
                        "name": fund["name"],
                        "changes": changes,
                        "one_day_change": one_day_change,
                        "latest_date": latest_date
                    })
                    
                except Exception as e:
                    print(f"Error: {fund['code']} - {str(e)}")
                    continue
        
        # 检查是否有数据
        if not table_data:
            return "❌ 无法获取任何基金数据，请检查网络连接"
        
        # 输出表格（使用HTML颜色替代emoji）
        result = "📊 **持仓分类基金近期涨跌幅统计**\n\n"
        result += "| 分类 | 基金代码 | 基金简称 | 40日涨跌 | 20日涨跌 | 10日涨跌 | 5日涨跌 | 3日涨跌 | 1日涨跌(日期) |\n"
        result += "|------|----------|----------|----------|----------|----------|---------|---------|----------------|\n"
        
        for item in table_data:
            changes_str = []
            for c in item["changes"]:
                if c is None:
                    changes_str.append("--")
                elif c > 0:
                    changes_str.append(f'<span style="color: red; font-weight: bold;">+{c:.2f}%</span>')
                elif c < 0:
                    changes_str.append(f'<span style="color: green; font-weight: bold;">{c:.2f}%</span>')
                else:
                    changes_str.append(f'<span style="color: gray;">0.00%</span>')
            
            # 1日涨跌格式化（使用颜色）
            if item["one_day_change"] is None:
                one_day_str = "--"
            elif item["one_day_change"] > 0:
                one_day_str = f'<span style="color: red; font-weight: bold;">+{item["one_day_change"]:.2f}%</span>'
            elif item["one_day_change"] < 0:
                one_day_str = f'<span style="color: green; font-weight: bold;">{item["one_day_change"]:.2f}%</span>'
            else:
                one_day_str = '<span style="color: gray;">0.00%</span>'
            
            result += f"| {item['category']} | {item['code']} | {item['name']} | "
            result += " | ".join(changes_str) + f" | {one_day_str} ({item['latest_date']}) |\n"
        
        return result
        
    except Exception as e:
        return f"❌ 获取基金数据失败: {str(e)}"
    
def func_4():
    """显示系统信息"""
    result = f"💻 **系统信息**\n\n"
    result += f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    result += f"Python版本: {sys.version.split()[0]}\n"
    result += f"操作系统: {os.name}\n"
    result += f"当前目录: {os.getcwd()}\n"
    
    try:
        import psutil
        memory = psutil.virtual_memory()
        result += f"内存使用: {memory.percent}%\n"
        result += f"可用内存: {memory.available / (1024**3):.2f} GB\n"
    except:
        pass
    
    return result


def func_5():
    """获取网络信息"""
    try:
        hostname = socket.gethostname()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        
        return f"🌐 **网络信息**\n\n主机名: {hostname}\nIP地址: {ip}\n端口: 7860\n访问地址: http://{ip}:7860"
    except Exception as e:
        return f"❌ 获取网络信息失败: {str(e)}"


def func_6():
    """显示数据示例"""
    return f"📋 **数据示例**\n\n1. 随机数: {', '.join(map(str, [random.randint(1, 100) for _ in range(5)]))}\n" \
           f"2. 时间戳: {int(datetime.now().timestamp())}\n" \
           f"3. 随机选择: {random.choice(['Python', 'Gradio', 'Pyecharts', 'xalpha'])}"


# 功能映射
FUNCTIONS_MAP = {
    "1": {"func": func_1, "desc": "持仓组合摘要", "emoji": "📊"},
    "2": {"func": func_2, "desc": "指数信息查询", "emoji": "📈"},
    "3": {"func": func_3, "desc": "基金涨跌统计", "emoji": "🎲"},
    "4": {"func": func_4, "desc": "系统信息", "emoji": "💻"},
    "5": {"func": func_5, "desc": "网络信息", "emoji": "🌐"},
    "6": {"func": func_6, "desc": "数据示例", "emoji": "📋"},
}


def build_charts(selected_types):
    """构建图表"""
    charts_map = {
        "持仓分布": create_holdings,
        "柱状图": lambda: create_chart("0000922"),
        "折线图": get_random_line_chart
    }
    
    html_parts = [chart_to_html(charts_map[t]()) for t in selected_types if t in charts_map]
    
    if not html_parts:
        return '<div style="height:550px;display:flex;align-items:center;justify-content:center;">请勾选图表</div>'
    return "".join(html_parts)


# 创建界面
with gr.Blocks(title="基金数据看板", theme=gr.themes.Soft()) as demo:
    gr.HTML(f"""
    <div style="text-align:center; padding:20px; background:linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius:10px;">
        <h1 style="color:white;">📊 基金数据看板</h1>
        <p style="color:white;">{get_network_info()} | 本地: http://localhost:7860</p>
    </div>
    """)
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 🎮 控制面板")
            chart_types = gr.CheckboxGroup(
                choices=["持仓分布", "柱状图", "折线图"],
                label="图表类型（可多选）",
                value=["持仓分布"]
            )
            gr.Button("🎨 生成图表", variant="primary").click(
                fn=build_charts, inputs=chart_types, outputs=gr.HTML(label="图表")
            )
            
            gr.Markdown("### 💬 数字命令")
            chat_input = gr.Textbox(label="输入数字", placeholder=f"输入 1-{len(FUNCTIONS_MAP)}", lines=2)
            chat_send = gr.Button("📨 发送")
            clear_btn = gr.Button("🗑️ 清除")
            
            # 功能对照表
            function_list = "\n".join([f"- **{num}** {info['emoji']} {info['desc']}" 
                                       for num, info in FUNCTIONS_MAP.items()])
            gr.Markdown("---\n### 📋 功能对照表\n" + function_list + "\n---")
        
        with gr.Column(scale=3):
            chart_output = gr.HTML(label="图表")
            chatbot = gr.Chatbot(label="执行结果", height=400)
            chat_history = gr.State([])
    
    # 聊天逻辑
    def send_message(msg, history):
        if not msg or not msg.strip():
            return history, "", history
        
        msg = msg.strip()
        if msg.isdigit() and msg in FUNCTIONS_MAP:
            info = FUNCTIONS_MAP[msg]
            response = f"{info['emoji']} **{info['desc']}**\n\n{info['func']()}"
        else:
            response = f"❌ 无效输入\n请输入 1-{len(FUNCTIONS_MAP)} 的数字"
        
        history.append({"role": "user", "content": f"🔢 {msg}"})
        history.append({"role": "assistant", "content": response})
        return history, "", history
    
    chat_send.click(send_message, [chat_input, chat_history], [chatbot, chat_input, chat_history])
    chat_input.submit(send_message, [chat_input, chat_history], [chatbot, chat_input, chat_history])
    clear_btn.click(lambda: ([], ""), None, [chatbot, chat_input])
    
    demo.load(fn=lambda: build_charts(["持仓分布"]), outputs=chart_output)


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, debug=True)