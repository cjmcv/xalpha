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
        elif value < -5:
            return f'<span style="color: gold; font-weight: bold;">{value:.2f}%</span>'
        elif value < -3:
            return f'<span style="color: darkgoldenrod; font-weight: bold;">{value:.2f}%</span>'
        elif value < 0:
            return f'<span style="color: green; font-weight: bold;">{value:.2f}%</span>'
        return '<span style="color: gray;">0.00%</span>'
    else:
        return f"{value:+.2f}%" if value != 0 else "0.00%"


def get_fund_positions_data():
    path = "./tests/CMB_fund_positions.csv"
    from xalpha.record_ext import from_positions, mulfix_pos
    read = from_positions(path, skiprows=0)
    sysopen = mulfix_pos(status=read)
    return sysopen, sysopen.combsummary()


def get_fund_categories():
    sysopen, summary_df = get_fund_positions_data()
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

def create_fund_pos_ratio_chart():
    sysopen, summary_df = get_fund_positions_data()
    chart = sysopen.v_positions(rendered=False)
    for s in chart.options.get("series", []):
        if s.get("type") == "pie":
            s["center"] = ["65%", "50%"]
    return chart

def create_chart(code):
    zzhli = xa.indexinfo(code)
    zzhli.bcmkset(xa.indexinfo("SH000300"), start="2014-01-01")
    return zzhli.v_netvalue(rendered=False)

def create_erp_chart():
    """创建股债性价比(ERP)图表"""
    import akshare as ak

    # 1. 获取沪深300 PE
    df_pe = ak.stock_index_pe_lg(symbol="沪深300")
    df_pe["日期"] = pd.to_datetime(df_pe["日期"])
    df_pe = df_pe.rename(columns={"滚动市盈率": "pe_ttm"})
    df_pe = df_pe.set_index("日期")[["pe_ttm"]].dropna()
    df_pe = df_pe.resample("ME").last()

    # 2. 获取10年期国债收益率
    end_date = pd.Timestamp.today().strftime("%Y%m%d")
    start_date = (pd.Timestamp.today() - pd.DateOffset(years=1)).strftime("%Y%m%d")
    df_bond = ak.bond_china_yield(start_date=start_date, end_date=end_date)
    df_bond = df_bond[df_bond["曲线名称"] == "中债国债收益率曲线"]
    df_bond = df_bond[["日期", "10年"]].rename(columns={"10年": "bond_yield"})
    df_bond["日期"] = pd.to_datetime(df_bond["日期"])
    df_bond = df_bond.set_index("日期")
    df_bond = df_bond.resample("ME").last()

    # 3. 合并计算 ERP
    df = pd.merge(df_pe, df_bond, left_index=True, right_index=True, how="inner").dropna()
    if df.empty:
        return None

    df["earnings_yield"] = 1 / df["pe_ttm"]
    df["erp"] = df["earnings_yield"] - df["bond_yield"] / 100

    # 4. 绘图数据
    dates = df.index.strftime("%Y-%m").tolist()
    erp_pct = (df["erp"] * 100).round(2).tolist()
    bond_pct = df["bond_yield"].round(2).tolist()
    mean_erp = 0.050 # 外部搜索得出，基于2016年-2026年
    q20 = 0.059 # 大于是股票机会区，越高越好
    q80 = 0.043 # 小于是股票风险区，越低越危险
    mean_line = [round(mean_erp * 100, 2)] * len(dates)
    q20_line = [round(q20 * 100, 2)] * len(dates)
    q80_line = [round(q80 * 100, 2)] * len(dates)

    # 5. 创建双轴图表
    line = (
        Line(init_opts=opts.InitOpts(width="100%", height="500px", theme=ThemeType.MACARONS, bg_color="#1a1a1a"))
        .add_xaxis(dates)
        .add_yaxis("ERP(股债利差) %", erp_pct, yaxis_index=0, is_symbol_show=False, linestyle_opts=opts.LineStyleOpts(width=3))
        .add_yaxis("10年期国债收益率 %", bond_pct, yaxis_index=1, is_symbol_show=False, linestyle_opts=opts.LineStyleOpts(width=1.5))
        .add_yaxis("ERP均值 %", mean_line, yaxis_index=0, is_symbol_show=False, linestyle_opts=opts.LineStyleOpts(type_="dashed"))
        .add_yaxis("80%分位(风险区) %", q80_line, yaxis_index=0, is_symbol_show=False, linestyle_opts=opts.LineStyleOpts(type_="dashed"))
        .add_yaxis("20%分位(机会区) %", q20_line, yaxis_index=0, is_symbol_show=False, linestyle_opts=opts.LineStyleOpts(type_="dashed"))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="股债利差（ERP=1/滚动PE(TTM) - 10年期国债收益率）", subtitle="沪深300", title_textstyle_opts=opts.TextStyleOpts(color="#FFFFFF")),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
            legend_opts=opts.LegendOpts(pos_top="5%", textstyle_opts=opts.TextStyleOpts(color="#FFFFFF")),
            xaxis_opts=opts.AxisOpts(name="日期", name_textstyle_opts=opts.TextStyleOpts(color="#CCCCCC"), axislabel_opts=opts.LabelOpts(color="#CCCCCC")),
            yaxis_opts=opts.AxisOpts(name="ERP %", name_textstyle_opts=opts.TextStyleOpts(color="#CCCCCC"), axislabel_opts=opts.LabelOpts(color="#CCCCCC")),
        )
        .extend_axis(yaxis=opts.AxisOpts(name="国债收益率 %", position="right", name_textstyle_opts=opts.TextStyleOpts(color="#CCCCCC"), axislabel_opts=opts.LabelOpts(color="#CCCCCC")))
        .set_series_opts(label_opts=opts.LabelOpts(is_show=False))
    )
    return line

def create_trade_records_charts():
    """创建权益类申购记录折线图"""
    try:
        path = "./tests/CMB_trade_records.csv"
        encodings = ['gb2312', 'gbk', 'utf-8']
        for enc in encodings:
            try:
                with open(path, 'r', encoding=enc) as f:
                    lines = f.readlines()
                break
            except UnicodeDecodeError:
                continue

        # 解析CSV
        data_lines = [l for l in lines if l.strip() and not l.strip().startswith('"#')]
        header_line = [l for l in data_lines if '交易日期' in l][0]
        header_idx = data_lines.index(header_line)

        import io
        csv_text = ''.join(data_lines[header_idx:])
        df = pd.read_csv(io.StringIO(csv_text))

        df.columns = df.columns.str.strip()
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].astype(str).str.strip()

        import re
        def extract_code(remark):
            remark = str(remark).strip()
            match = re.search(r'\d{5,6}', remark)
            return match.group() if match else None

        df['code'] = df['交易备注'].apply(extract_code)

        trans_types = ["基金定期定额申购", "基金申购", "基金赎回"]
        df_filtered = df[df['交易类型'].isin(trans_types)].copy()
        df_filtered = df_filtered[df_filtered['code'].notna()].copy()

        df_filtered['收入'] = pd.to_numeric(df_filtered['收入'], errors='coerce').fillna(0)
        df_filtered['支出'] = pd.to_numeric(df_filtered['支出'], errors='coerce').fillna(0)

        df_filtered['交易类型合并'] = df_filtered['交易类型'].apply(
            lambda x: '申购' if x in ['基金定期定额申购', '基金申购'] else '赎回'
        )

        sysopen, summary_df = get_fund_positions_data()
        category_config = sysopen.category_config
        code_to_name = dict(zip(summary_df['产品代码'].astype(str), summary_df['简称']))

        def get_category(code):
            name = code_to_name.get(code, "未知")
            for cat_name, config in category_config.items():
                if config["keywords"] and any(k in name for k in config["keywords"]):
                    return cat_name
            return "其他"

        df_filtered['category'] = df_filtered['code'].apply(get_category)

        df_filtered['交易日期_str'] = df_filtered['交易日期'].apply(
            lambda x: str(int(float(x))) if not pd.isna(x) else None
        )
        df_filtered = df_filtered[df_filtered['交易日期_str'].notna()].copy()
        all_dates = sorted(df_filtered['交易日期_str'].unique())

        # X轴日期（格式化为04-01）
        x_dates = [d[2:] if len(d) == 8 else d for d in all_dates]

        # 构建数据
        from pyecharts.charts import Line
        from pyecharts import options as opts

        purchase_lines = []
        redeem_lines = []

        categories = sorted([c for c in df_filtered['category'].unique() if c != "其他"])
        colors = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4']

        for idx, cat in enumerate(categories):
            df_cat = df_filtered[df_filtered['category'] == cat]

            if cat == "二级债基":
                continue  # 二级债基不输出，只输出权益类
                fund_codes = sorted(df_cat['code'].unique())
                for code in fund_codes:
                    df_fund = df_cat[df_cat['code'] == code]
                    name = code_to_name.get(code, code)
                    if len(name) > 8:
                        name = name[:8]

                    purchase_values = []
                    redeem_values = []
                    for date in all_dates:
                        df_date = df_fund[df_fund['交易日期_str'] == date]
                        purchase_val = df_date[df_date['交易类型合并'] == '申购']['支出'].sum()
                        redeem_val = df_date[df_date['交易类型合并'] == '赎回']['收入'].sum()
                        purchase_values.append(purchase_val)
                        redeem_values.append(redeem_val)

                    purchase_lines.append((name, purchase_values))
                    redeem_lines.append((name, redeem_values))
            else:
                purchase_values = []
                redeem_values = []
                for date in all_dates:
                    df_date = df_cat[df_cat['交易日期_str'] == date]
                    purchase_val = df_date[df_date['交易类型合并'] == '申购']['支出'].sum()
                    redeem_val = df_date[df_date['交易类型合并'] == '赎回']['收入'].sum()
                    purchase_values.append(purchase_val)
                    redeem_values.append(redeem_val)

                purchase_lines.append((cat, purchase_values))
                redeem_lines.append((cat, redeem_values))

        # 计算累计金额
        purchase_cumulative = []
        for name, values in purchase_lines:
            cumulative = []
            total = 0
            for v in values:
                total += v
                cumulative.append(total)
            purchase_cumulative.append((name, cumulative))

        from pyecharts.charts import Line

        # 创建申购图表（折线图，累计金额）
        purchase_chart = (
            Line(init_opts=opts.InitOpts(width="100%", height="400px", theme=ThemeType.MACARONS, bg_color="#1a1a1a"))
            .add_xaxis(x_dates)
        )
        for name, values in purchase_cumulative:
            purchase_chart.add_yaxis(
                name, values,
                is_symbol_show=False,
                linestyle_opts=opts.LineStyleOpts(width=2)
            )
        purchase_chart.set_global_opts(
            title_opts=opts.TitleOpts(title="权益类申购（累计金额）", title_textstyle_opts=opts.TextStyleOpts(color="#FFFFFF")),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
            legend_opts=opts.LegendOpts(pos_top="5%", textstyle_opts=opts.TextStyleOpts(color="#FFFFFF")),
            xaxis_opts=opts.AxisOpts(name="日期", name_textstyle_opts=opts.TextStyleOpts(color="#CCCCCC"), axislabel_opts=opts.LabelOpts(color="#CCCCCC")),
            yaxis_opts=opts.AxisOpts(name="累计金额", name_textstyle_opts=opts.TextStyleOpts(color="#CCCCCC"), axislabel_opts=opts.LabelOpts(color="#CCCCCC")),
        )
        purchase_chart.set_series_opts(label_opts=opts.LabelOpts(is_show=False))

        return [purchase_chart]

    except Exception as e:
        return None

# ==================== 数字功能函数 ====================
def fund_pos_detail():
    try:
        _, summary_df = get_fund_positions_data()
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

def fund_pos_change_stat():
    """持仓基金涨跌幅统计"""
    try:
        fund_categories = get_fund_categories()
        intervals = [("40日", 40), ("20日", 20), ("10日", 10), ("5日", 5), ("4日", 4), ("3日", 3), ("2日", 2), ("1日", 1)]  # N日=(今天净值-(N+1)天前净值)/(N+1)天前净值
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
                        if len(df) > num_days:
                            nav_ago = df.iloc[num_days]['单位净值']
                            changes.append((latest_nav - nav_ago) / nav_ago * 100)
                        else:
                            changes.append(None)

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
                    
                    one_day_date = df.iloc[0]['净值日期'].strftime('%m-%d') if len(df) > 0 else ""

                    table_data.append({
                        "category": cat_name, "code": fund["code"], "name": fund["name"],
                        "changes": changes, "drawdown": drawdown, "peak_date": peak_date, "one_day_date": one_day_date
                    })
                except Exception as e:
                    continue
        
        if not table_data:
            return "❌ 无法获取任何基金数据"

        result = "📊 **持仓分类基金近期涨跌幅统计**\n\n"
        result += "| 分类 | 基金代码 | 基金简称 | 40日 | 20日 | 10日 | 5日 | 4日 | 3日 | 2日 | 1日 | 距一年高点 |\n"
        result += "|------|-------|-------|-------|-------|-------|------|------|------|------|-------------|----------------|\n"

        for item in table_data:
            changes_str = [format_percentage(c, color_mode=True) for c in item["changes"]]
            # 1日显示带日期的完整信息
            one_day_str = changes_str[-1] + f' <span style="color: gray;">({item["one_day_date"]})</span>' if item["one_day_date"] else changes_str[-1]
            changes_str_with_date = changes_str[:-1] + [one_day_str]
            if item["drawdown"] is None:
                dd_str = "--"
            else:
                dd_str = format_percentage(-item["drawdown"], color_mode=True) + f' <span style="color: gray;">({item["peak_date"]})</span>'
            result += f"| {item['category']} | {item['code']} | {item['name']} | "
            result += " | ".join(changes_str_with_date) + f" | {dd_str} |\n"
        return result
    except Exception as e:
        return f"❌ 获取基金数据失败: {str(e)}"
    
# todo: 检索财报摘要汇总。结合daily输出用于询问大模型的prompt。
def get_fund_detail(fund_code=None):
    """指定基金详情"""
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
        # 时间点定义：N日=(今天净值-(N+1)天前净值)/(N+1)天前净值
        intervals = [260, 160, 80, 40, 20, 10, 5, 4, 3, 2, 1]
        interval_names = ["260日", "160日", "80日", "40日", "20日", "10日", "5日", "4日", "3日", "2日", "1日"]

        # 构建净值数据
        data_rows = []
        for days, name in zip(intervals, interval_names):
            if len(df) > days:
                nav = df.iloc[days]['单位净值']
                # 1日显示最新净值日期，与fund_pos_change_stat保持一致
                date = df.iloc[0 if days == 1 else days]['净值日期'].strftime('%m-%d')
                data_rows.append({"时间点": name, "日期": date, "净值": nav})
        
        # 生成净值表格
        result = f"📈 **基金详情 - {target_fund['name']} ({target_fund['code']})**\n\n"
        result += f"分类: {target_category}\n"
        result += f"数据截止: {df.iloc[0]['净值日期'].strftime('%Y-%m-%d')}\n\n"
        
        # 构建表头
        result += "| 指标 |" + "".join([f" {r['时间点']} |" for r in data_rows]) + "\n"
        result += "|------|" + "".join(["------|" for _ in data_rows]) + "\n"
        result += "| 日期 |" + "".join([f" {r['日期']} |" for r in data_rows]) + "\n"
        result += "| 净值 |" + "".join([f" {r['净值']:.4f} |" for r in data_rows]) + "\n"
        
        # 涨跌幅行
        latest_nav = df.iloc[0]['单位净值']  # 真正的最新净值
        result += "| 涨跌幅 |"
        for row in data_rows:
            change = (latest_nav - row['净值']) / row['净值'] * 100
            result += f" {format_percentage(change, color_mode=True)} |"
        result += "\n"
        
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
    """招商银行申购记录统计"""
    try:
        path = "./tests/CMB_trade_records.csv"
        encodings = ['gb2312', 'gbk', 'utf-8']
        for enc in encodings:
            try:
                with open(path, 'r', encoding=enc) as f:
                    lines = f.readlines()
                break
            except UnicodeDecodeError:
                continue

        # 解析CSV（跳过注释行）
        data_lines = [l for l in lines if l.strip() and not l.strip().startswith('"#')]
        header_line = [l for l in data_lines if '交易日期' in l][0]
        header_idx = data_lines.index(header_line)

        import io
        csv_text = ''.join(data_lines[header_idx:])
        df = pd.read_csv(io.StringIO(csv_text))

        # 清理列名和数据
        df.columns = df.columns.str.strip()
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].astype(str).str.strip()

        # 提取基金代码（保留原始格式如008929）
        import re
        def extract_code(remark):
            remark = str(remark).strip()
            match = re.search(r'\d{5,6}', remark)
            return match.group() if match else None

        df['code'] = df['交易备注'].apply(extract_code)

        # 交易类型
        trans_types = ["基金定期定额申购", "基金申购", "基金赎回"]
        df_filtered = df[df['交易类型'].isin(trans_types)].copy()
        df_filtered = df_filtered[df_filtered['code'].notna()].copy()

        # 金额列处理
        df_filtered['收入'] = pd.to_numeric(df_filtered['收入'], errors='coerce').fillna(0)
        df_filtered['支出'] = pd.to_numeric(df_filtered['支出'], errors='coerce').fillna(0)

        # 合并申购类型
        df_filtered['交易类型合并'] = df_filtered['交易类型'].apply(
            lambda x: '申购' if x in ['基金定期定额申购', '基金申购'] else '赎回'
        )

        # 获取category_config和基金信息
        sysopen, summary_df = get_fund_positions_data()
        category_config = sysopen.category_config
        code_to_name = dict(zip(summary_df['产品代码'].astype(str), summary_df['简称']))

        # 建立基金代码到分类的映射（与get_fund_categories逻辑一致）
        def get_category(code):
            name = code_to_name.get(code, "未知")
            for cat_name, config in category_config.items():
                if config["keywords"] and any(k in name for k in config["keywords"]):
                    return cat_name
            return "其他"

        df_filtered['category'] = df_filtered['code'].apply(get_category)

        # 获取所有交易日期（去重排序，转为字符串）
        df_filtered['交易日期_str'] = df_filtered['交易日期'].apply(
            lambda x: str(int(float(x))) if not pd.isna(x) else None
        )
        df_filtered = df_filtered[df_filtered['交易日期_str'].notna()].copy()
        all_dates = sorted(df_filtered['交易日期_str'].unique())

        # 按分类汇总
        categories = sorted(df_filtered['category'].unique())

        # 构建结果
        result = "📋 **招商银行申购记录统计**\n\n"
        result += f"数据日期范围: {all_dates[-1]} ~ {all_dates[0]}\n\n"

        # 分别输出申购和赎回两个表格
        for trans_label, trans_key in [("申购", "申购"), ("赎回", "赎回")]:
            df_trans = df_filtered[df_filtered['交易类型合并'] == trans_key]
            if df_trans.empty:
                continue

            # 表头
            header_dates = [d[2:] if len(d) == 8 else d for d in all_dates]
            result += f"### {trans_label}\n\n"
            result += "| 分类 | " + " | ".join(header_dates) + " |\n"
            result += "|------|" + "|------|" * len(header_dates) + "\n"

            # 按分类汇总
            for cat in categories:
                df_cat = df_trans[df_trans['category'] == cat]

                if cat == "二级债基":
                    # 二级债基每个基金单独一行
                    fund_codes_in_cat = sorted(df_cat['code'].unique())
                    for code in fund_codes_in_cat:
                        name = code_to_name.get(code, "未知")
                        if len(name) > 10:
                            name = name[:10] + "..."
                        row_values = [f"{name} ({code})"]
                        for date in all_dates:
                            df_fund_date = df_cat[(df_cat['code'] == code) & (df_cat['交易日期_str'] == date)]
                            if trans_key == "申购":
                                total = df_fund_date['支出'].sum()
                            else:
                                total = df_fund_date['收入'].sum()
                            row_values.append(f"{total:.0f}" if total > 0 else "-")
                        result += "| " + " | ".join(row_values) + " |\n"
                else:
                    # 其他分类按大类汇总
                    row_values = [cat]
                    for date in all_dates:
                        df_cat_date = df_cat[df_cat['交易日期_str'] == date]
                        if trans_key == "申购":
                            total = df_cat_date['支出'].sum()
                        else:
                            total = df_cat_date['收入'].sum()
                        row_values.append(f"{total:.0f}" if total > 0 else "-")
                    result += "| " + " | ".join(row_values) + " |\n"
            result += "\n"

        return result if len(categories) > 0 else "❌ 无有效申购记录"

    except Exception as e:
        return f"❌ 读取申购记录失败: {str(e)}"
    
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
    "1": {"func": fund_pos_detail, "desc": "持仓组合摘要", "emoji": "📊", "has_param": False},
    "2": {"func": fund_pos_change_stat, "desc": "持仓基金涨跌统计", "emoji": "📈", "has_param": False},
    "3": {"func": get_fund_detail, "desc": "查阅基金(如020989)", "emoji": "🎲", "has_param": True, "param_desc": "基金代码"},
    "4": {"func": func_4, "desc": "系统信息", "emoji": "💻", "has_param": False},
    "5": {"func": func_5, "desc": "网络信息", "emoji": "🌐", "has_param": False},
    "6": {"func": func_6, "desc": "数据示例", "emoji": "📋", "has_param": False},
}

def build_charts(selected_types):
    charts_map = {"持仓分布": create_fund_pos_ratio_chart, "申购记录": create_trade_records_charts, "股债利差": create_erp_chart}
    html_parts = []
    for t in selected_types:
        if t in charts_map:
            result = charts_map[t]()
            if result is not None:
                if isinstance(result, list):
                    html_parts.extend([chart_to_html(c) for c in result])
                else:
                    html_parts.append(chart_to_html(result))
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
            chart_2 = gr.Checkbox(label="申购记录", value=False)
            chart_3 = gr.Checkbox(label="股债利差", value=False)
            
            def combine_charts(c1, c2, c3):
                selected = []
                if c1: selected.append("持仓分布")
                if c2: selected.append("申购记录")
                if c3: selected.append("股债利差")
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
        with gr.Column(scale=3):
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
                response = f"📈 **查询基金净值 ({msg})**\n\n{get_fund_detail(msg)}"
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