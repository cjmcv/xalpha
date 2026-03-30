import gradio as gr
from pyecharts.charts import Bar, Line
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
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return f"WSL IP: {ip}"
    except:
        return "请手动查看WSL IP: ip addr show | grep eth0"


def chart_to_html(chart):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        temp_path = f.name
    chart.render(temp_path)
    with open(temp_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    os.unlink(temp_path)
    fixed_html = html_content.replace('<head>', '<head><script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>')
    return f'<div style="width:100%; height:550px; border:1px solid #ddd; border-radius:10px; overflow:hidden; background:white;">' \
           f'<iframe srcdoc="{html.escape(fixed_html)}" style="width:100%; height:100%; border:none;" ' \
           f'sandbox="allow-scripts allow-same-origin allow-popups allow-forms"></iframe></div>'


def get_fund_data(fund_code):
    import akshare as ak
    df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
    df = df.sort_values('净值日期', ascending=False).reset_index(drop=True)
    df['单位净值'] = pd.to_numeric(df['单位净值'], errors='coerce')
    df['日增长率'] = pd.to_numeric(df['日增长率'], errors='coerce')
    return df


def format_percentage(value, color_mode=False):
    if value is None:
        return "--"
    if color_mode:
        if value > 0:
            return f'<span style="color: red; font-weight: bold;">+{value:.2f}%</span>'
        elif value < 0:
            return f'<span style="color: green; font-weight: bold;">{value:.2f}%</span>'
        return '<span style="color: gray;">0.00%</span>'
    else:
        return f"{value:+.2f}%" if value != 0 else "0.00%"


def get_positions_data():
    path = "./tests/cmb_holdings.csv"
    from xalpha.record_ext import from_positions, mulfix_pos
    read = from_positions(path, skiprows=0)
    sysopen = mulfix_pos(status=read)
    return sysopen, sysopen.combsummary()


def get_fund_categories():
    sysopen, summary_df = get_positions_data()
    category_config = sysopen.category_config
    fund_categories = {}
    for _, row in summary_df.iterrows():
        fund_name = row['简称']
        fund_code = row['产品代码']
        cat = "其他"
        for cat_name, config in category_config.items():
            if config["keywords"] and any(k in fund_name for k in config["keywords"]):
                cat = cat_name
                break
        if len(fund_name) > 11:
            fund_name = fund_name[:11] + "..."
        fund_categories.setdefault(cat, []).append({"code": fund_code, "name": fund_name})
    return fund_categories


# ==================== 图表创建 ====================
def create_chart(code):
    zzhli = xa.indexinfo(code)
    zzhli.bcmkset(xa.indexinfo("SH000300"), start="2014-01-01")
    return zzhli.v_netvalue(rendered=False)


def create_holdings():
    path = "./tests/cmb_holdings.csv"
    from xalpha.record_ext import from_positions, mulfix_pos
    read = from_positions(path, skiprows=0)
    sysopen = mulfix_pos(status=read)
    return sysopen.v_positions(rendered=False)


def get_random_line_chart():
    weeks = ['第一周', '第二周', '第三周', '第四周', '第五周']
    users = [random.randint(500, 2000) for _ in range(5)]
    return (Line(init_opts=opts.InitOpts(width="800px", height="500px", theme=ThemeType.MACARONS, bg_color='white'))
            .add_xaxis(weeks)
            .add_yaxis("活跃用户数", users, is_smooth=True)
            .set_global_opts(title_opts=opts.TitleOpts(title="📈 周活跃用户趋势"),
                           yaxis_opts=opts.AxisOpts(name="用户数"),
                           xaxis_opts=opts.AxisOpts(name="周次"),
                           toolbox_opts=opts.ToolboxOpts(is_show=True))
            .set_series_opts(label_opts=opts.LabelOpts(is_show=True)))


# ==================== 数字功能函数 ====================
def func_1():
    try:
        _, summary_df = get_positions_data()
        result = "📊 **持仓组合摘要**\n\n"
        result += "| 产品代码 | 简称 | 基金份额 | 单位净值 | 总成本 | 参考市值 | 浮动盈亏 | 收益率 | 占比 |\n"
        result += "|----------|------|----------|----------|--------|----------|----------|--------|------|\n"
        for _, row in summary_df.iterrows():
            result += f"| {row['产品代码']} | {row['简称']} | {row['基金份额']:.2f} | {row['单位净值']:.4f} | "
            result += f"{row['总成本']:.2f} | {row['参考市值']:.2f} | {row['浮动盈亏']:.2f} | {format_percentage(row['收益率'])} | {row['占比']:.2f}% |\n"
        total_market = summary_df['参考市值'].sum()
        total_cost = summary_df['总成本'].sum()
        total_profit = total_market - total_cost
        total_rate = (total_profit / total_cost * 100) if total_cost > 0 else 0
        result += f"\n---\n\n**📈 组合汇总**\n\n- **总市值**: {total_market:.2f} 元\n- **总成本**: {total_cost:.2f} 元\n"
        result += f"- **总盈亏**: {format_percentage(total_profit)} 元\n- **总收益率**: {format_percentage(total_rate)}\n"
        return result
    except Exception as e:
        return f"❌ 读取持仓信息失败: {str(e)}"


def func_2():
    """持仓基金涨跌幅统计"""
    try:
        fund_categories = get_fund_categories()
        intervals = [("40日", 40), ("20日", 20), ("10日", 10), ("5日", 5), ("4日", 4), ("3日", 3), ("2日", 2)]  # 添加4日和2日
        table_data = []
        
        for cat_name, funds in fund_categories.items():
            funds_to_show = funds if cat_name == "二级债基" else funds[:1]
            for fund in funds_to_show:
                try:
                    df = get_fund_data(fund["code"])
                    if df.empty or len(df) < 3:
                        continue
                    
                    latest_nav = df.iloc[0]['单位净值']
                    changes = []
                    for _, num_days in intervals:
                        if len(df) >= num_days:
                            nav_ago = df.iloc[num_days-1]['单位净值']
                            changes.append((latest_nav - nav_ago) / nav_ago * 100)
                        else:
                            changes.append(None)
                    
                    one_day_change = df.iloc[0]['日增长率'] if len(df) >= 1 and not pd.isna(df.iloc[0]['日增长率']) else None
                    
                    # 计算过去一年最高点
                    df_asc = df.sort_values('净值日期', ascending=True).reset_index(drop=True)
                    one_year_data = df_asc[df_asc['净值日期'] >= (df_asc.iloc[-1]['净值日期'] - pd.Timedelta(days=365))]
                    if len(one_year_data) > 0:
                        max_idx = one_year_data['单位净值'].idxmax()
                        max_nav = one_year_data.loc[max_idx, '单位净值']
                        peak_date = one_year_data.loc[max_idx, '净值日期'].strftime('%m-%d')
                        drawdown = (max_nav - latest_nav) / max_nav * 100
                    else:
                        drawdown, peak_date = None, None
                    
                    latest_date = df.iloc[0]['净值日期'].strftime('%m-%d')
                    table_data.append({
                        "category": cat_name, "code": fund["code"], "name": fund["name"],
                        "changes": changes, "one_day_change": one_day_change,
                        "latest_date": latest_date, "drawdown": drawdown, "peak_date": peak_date
                    })
                except Exception as e:
                    continue
        
        if not table_data:
            return "❌ 无法获取任何基金数据"
        
        result = "📊 **持仓分类基金近期涨跌幅统计**\n\n"
        result += "| 分类 | 基金代码 | 基金简称 | 40日 | 20日 | 10日 | 5日 | 4日 | 3日 | 2日 | 1日 | 距一年高点 |\n"  # 添加4日和2日列
        result += "|------|-------|-------|-------|-------|-------|------|------|------|------|-------------|----------------|\n"
        
        for item in table_data:
            changes_str = [format_percentage(c, color_mode=True) for c in item["changes"]]
            one_day_str = format_percentage(item["one_day_change"], color_mode=True)
            if item["drawdown"] is None:
                dd_str = "--"
            else:
                dd_str = format_percentage(-item["drawdown"], color_mode=True) + f' <span style="color: gray;">({item["peak_date"]})</span>'
            result += f"| {item['category']} | {item['code']} | {item['name']} | "
            result += " | ".join(changes_str) + f" | {one_day_str} ({item['latest_date']}) | {dd_str} |\n"
        return result
    except Exception as e:
        return f"❌ 获取基金数据失败: {str(e)}"
    
# todo: 股债性价比。检索财报摘要汇总。结合daily输出用于询问大模型的prompt。
def func_3(fund_code=None):
    """指定基金净值变化 - 添加雪球基金估值链接"""
    try:
        if fund_code is None:
            fund_code = "020989"
        
        # 获取分类数据
        fund_categories = get_fund_categories()
        
        # 查找目标基金
        target_fund = None
        target_category = None
        for cat_name, funds in fund_categories.items():
            for fund in funds:
                if fund["code"] == fund_code:
                    target_fund = fund
                    target_category = cat_name
                    break
            if target_fund:
                break
        
        if not target_fund:
            return f"❌ 未找到基金代码: {fund_code}"
        
        # 雪球基金代码映射
        dj_index_code_map = {
            "恒生科技": "HKHSTECH",
            "主要消费红利": "CSIH30094",
            "纳斯达克100": "NDX",
            "标普500": "SP500",
        }
        # etf.run代码映射，只有A股
        etfrun_index_code_map = {
            "中证A500": "SSE/000510",
            "主要消费红利": "CSI/h30094",
        }
        df = get_fund_data(fund_code)
        # 时间点定义
        intervals = [160, 80, 40, 20, 10, 5, 4, 3, 2, 1]
        interval_names = ["160日前", "80日前", "40日前", "20日前", "10日前", "5日前", "4日前", "3日前", "2日前", "最新"]
        
        # 构建净值数据
        data_rows = []
        for days, name in zip(intervals, interval_names):
            if len(df) >= days:
                nav = df.iloc[days-1]['单位净值']
                date = df.iloc[days-1]['净值日期'].strftime('%m-%d')
                data_rows.append({"时间点": name, "日期": date, "净值": nav})
        
        # 生成净值表格
        result = f"📈 **基金净值变化 - {target_fund['name']} ({target_fund['code']})**\n\n"
        result += f"分类: {target_category}\n"
        result += f"数据截止: {df.iloc[0]['净值日期'].strftime('%Y-%m-%d')}\n\n"
        
        # 构建表头
        result += "| 指标 |" + "".join([f" {r['时间点']} |" for r in data_rows]) + "\n"
        result += "|------|" + "".join(["------|" for _ in data_rows]) + "\n"
        result += "| 日期 |" + "".join([f" {r['日期']} |" for r in data_rows]) + "\n"
        result += "| 净值 |" + "".join([f" {r['净值']:.4f} |" for r in data_rows]) + "\n"
        
        # 涨跌幅行
        latest_nav = data_rows[-1]['净值']
        result += "| 涨跌幅 |"
        for row in data_rows[:-1]:
            change = (latest_nav - row['净值']) / row['净值'] * 100
            result += f" {format_percentage(change, color_mode=True)} |"
        result += " - |\n"
        
        # ========== 雪球基金估值链接 ==========
        result += "\n---\n\n### 📊 估值查询\n\n"
        
        # 优先使用指数代码（更精确的估值数据）
        if target_category in dj_index_code_map:
            index_code = dj_index_code_map[target_category]
            valuation_url = f"https://danjuanfunds.com/dj-valuation-table-detail/{index_code}"
            result += f"**查看估值详情**\n\n"
            result += f"🔗 [点击查看 {target_category} 指数估值（雪球基金）]({valuation_url})\n\n"
            result += f"指数代码: {index_code}（雪球基金）\n\n"
        
        if target_category in etfrun_index_code_map:
            index_code = etfrun_index_code_map[target_category]
            valuation_url = f"https://www.etf.run/index/{index_code}"
            result += f"**查看估值详情**\n\n"
            result += f"🔗 [点击查看 {target_category} 指数估值（etf.run）]({valuation_url})\n\n"
            result += f"指数代码: {index_code}（etf.run）\n\n"
        
        result += "**其他PE/PB数据:**\n"
        result += "- 且慢: https://qieman.com/idx-eval\n"
        
        return result
    except Exception as e:
        return f"❌ 查询失败: {str(e)}"
    
def func_4():
    result = f"💻 **系统信息**\n\n当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nPython版本: {sys.version.split()[0]}\n操作系统: {os.name}\n当前目录: {os.getcwd()}\n"
    try:
        import psutil
        memory = psutil.virtual_memory()
        result += f"内存使用: {memory.percent}%\n可用内存: {memory.available / (1024**3):.2f} GB\n"
    except:
        pass
    return result


def func_5():
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
    return f"📋 **数据示例**\n\n1. 随机数: {', '.join(map(str, [random.randint(1, 100) for _ in range(5)]))}\n" \
           f"2. 时间戳: {int(datetime.now().timestamp())}\n" \
           f"3. 随机选择: {random.choice(['Python', 'Gradio', 'Pyecharts', 'xalpha'])}"


# 功能映射
FUNCTIONS_MAP = {
    "1": {"func": func_1, "desc": "持仓组合摘要", "emoji": "📊", "has_param": False},
    "2": {"func": func_2, "desc": "基金涨跌统计", "emoji": "📈", "has_param": False},
    "3": {"func": func_3, "desc": "查阅基金(如020989)", "emoji": "🎲", "has_param": True, "param_desc": "基金代码"},
    "4": {"func": func_4, "desc": "系统信息", "emoji": "💻", "has_param": False},
    "5": {"func": func_5, "desc": "网络信息", "emoji": "🌐", "has_param": False},
    "6": {"func": func_6, "desc": "数据示例", "emoji": "📋", "has_param": False},
}


def build_charts(selected_types):
    charts_map = {"持仓分布": create_holdings, "柱状图": lambda: create_chart("0000922"), "折线图": get_random_line_chart}
    html_parts = [chart_to_html(charts_map[t]()) for t in selected_types if t in charts_map]
    return "".join(html_parts) if html_parts else '<div style="height:550px;display:flex;align-items:center;justify-content:center;">请勾选图表</div>'

# 创建界面
with gr.Blocks(title="基金数据看板", theme=gr.themes.Soft()) as demo:
    gr.HTML(f'<div style="text-align:center; padding:20px; background:linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius:10px;">'
            f'<h1 style="color:white;">📊 基金数据看板</h1><p style="color:white;">{get_network_info()} | 本地: http://localhost:7860</p></div>')
    
    # 第一行：左边控制面板+数字命令，右边图表
    with gr.Row():
        # 左侧：控制面板 + 数字命令
        with gr.Column(scale=1):
            # 图表类型选择
            gr.Markdown("**图表类型**")
            chart_1 = gr.Checkbox(label="持仓分布", value=True)
            chart_2 = gr.Checkbox(label="柱状图", value=False)
            chart_3 = gr.Checkbox(label="折线图", value=False)
            
            def combine_charts(c1, c2, c3):
                selected = []
                if c1: selected.append("持仓分布")
                if c2: selected.append("柱状图")
                if c3: selected.append("折线图")
                return selected
            
            generate_btn = gr.Button("🎨 生成图表", variant="primary")
            
            gr.Markdown("---")
            chat_input = gr.Textbox(label="💬 数字命令", placeholder=f"输入 1-6 或 基金编号 020989", lines=2)
            
            with gr.Row():
                chat_send = gr.Button("📨 发送", variant="primary", scale=1)
                clear_btn = gr.Button("🗑️ 清除", scale=1)
            
            function_list = "\n".join([
                f"- **{num}** {info['emoji']} {info['desc']}"
                for num, info in FUNCTIONS_MAP.items()
            ])
            gr.Markdown(function_list + "\n---")
        
        # 右侧：图表
        with gr.Column(scale=2):
            chart_output = gr.HTML(label="图表")
    
    # 第二行：执行结果框（横跨整行）
    with gr.Row():
        with gr.Column(scale=1):
            chatbot = gr.Chatbot(label="执行结果", height=600)
            chat_history = gr.State([])
    
    # 绑定按钮事件 - 合并checkbox的值
    generate_btn.click(
        fn=lambda a,b,c: build_charts(combine_charts(a,b,c)), 
        inputs=[chart_1, chart_2, chart_3], 
        outputs=chart_output
    )
    
    def send_message(msg, history):
        if not msg or not msg.strip():
            return history, "", history
        
        msg = msg.strip()
        parts = msg.split()
        first_part = parts[0]
        
        if first_part.isdigit() and first_part in FUNCTIONS_MAP:
            info = FUNCTIONS_MAP[first_part]
            if info.get("has_param", False):
                if len(parts) >= 2:
                    param = parts[1]
                    response = f"{info['emoji']} **{info['desc']} ({param})**\n\n{info['func'](param)}"
                else:
                    response = f"{info['emoji']} **{info['desc']} (使用默认代码: 020989)**\n\n{info['func']()}"
            else:
                response = f"{info['emoji']} **{info['desc']}**\n\n{info['func']()}"
        else:
            if msg.isdigit() and len(msg) == 6:
                response = f"📈 **查询基金净值 ({msg})**\n\n{func_3(msg)}"
            else:
                response = f"❌ 无效输入\n\n**使用格式:**\n- 数字命令: 1-6\n- 查询基金: `3 020989` 或直接输入基金代码\n\n**可用命令:**\n" + "\n".join([f"  {num} - {info['emoji']} {info['desc']}" for num, info in FUNCTIONS_MAP.items()])
        
        history.append({"role": "user", "content": f"🔢 {msg}"})
        history.append({"role": "assistant", "content": response})
        return history, "", history
    
    chat_send.click(send_message, [chat_input, chat_history], [chatbot, chat_input, chat_history])
    chat_input.submit(send_message, [chat_input, chat_history], [chatbot, chat_input, chat_history])
    clear_btn.click(lambda: ([], ""), None, [chatbot, chat_input])
    
    # 初始加载
    demo.load(fn=lambda: build_charts(["持仓分布"]), outputs=chart_output)
    
    
if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, debug=True)