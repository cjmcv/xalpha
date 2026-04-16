import gradio as gr
from pyecharts import options as opts
from pyecharts.charts import Line
from pyecharts.globals import ThemeType
import akshare as ak
import html
import os
import pandas as pd
import random
import re
import socket
import tempfile
from datetime import datetime, timedelta
from fund_positions import from_positions, mulfix_pos

# TODO: 1. 可转债的百元溢价率
#       2. 财经报告：风险预警清单，1）美联储最近一次表态是鹰派还是鸽派
#                                    2）新发基金规模有没有连续爆量
#                                    3）股债利差：http://www.dashiyetouzi.com/tools/compare/hs300_10gz_pro.php
#                                    4）拥挤度：https://legulegu.com/stockdata/ashares-congestion
#                                    5）北向资金流向：http://wdatacn.aastocks.com/sc/cnhk/market/quota-balance/
#                                    给出具体数据，并作出总结。
#      3. 主动基金的季报总结。

# 规则：1. 分批建仓，日定投，每月增量资金按目标比例分配，即超配少投，低配多投。（自动低吸）
#      2. 90天再平衡：包含短债在内，超配部分卖出，低配部分补足。（自动高抛低吸，如增量资金能完成修复则不卖）
#                    （高斜率保护：纳指和标普允许比例上浮偏移30%不减持）
#      3. 短债应急补仓：权益仓位从最近高点回撤>15%，动用短债分批定投修复比例，每个权益仓位单独处理。
#      4. 熊市短债减配机制：沪深300/纳指100 从近12个月高点回撤≥25%，判定为A股/美股熊市。
#                         增量资金忽略短债份额，优先补足权益仓位。如增量资金无法补足，等待月度平衡权益仓位，短债保持空仓。
#                         对应基金单月反弹≥10% 后，恢复常规规则，增量资金重新优先补足短债。

### 50% ###
# 现金3级： 短债，华夏鼎泓债券，景颐裕利   6+2+2=10% 
# A股固收+：景颐招利，瑞锦混合，安阳债券  30+5+5=40%
### 25% ###
# A股固收+卫星：中证红利低波(股息4以上)    6% 
# A股价值卫星: 国证自由现金流             6% 
# AH股主动价值: 大成高鑫 (刘旭)           6%
#              中欧红利优享 (蓝小康)      4%
# A股主动成长: 兴全合润 (谢志宇)          3%
### 25% ###
# 美股被动成长: 标普500                    3%
#              纳指100                   10%
# 美股主动成长: 易方达全球优质企业 (李剑锋)  5%
#              广发全球精选 (李耀柱)       5%
#              易方达全球成长精选 (郑希)    2%
###########

# "类别": {"keywords": ["基金名称里的关键词"]，"entry": "实际开始定投日期, 
#          "target_ratio": 目标份额比例, "vol_coef": 波动系数(直接乘以加仓阈值，波动越大，触发加仓越难)"},
# "target_ratio": 0 表示暂不持仓；二级债基/全球主动和黄金只做手动加仓。
category_config = {
    # 美股，低估或跌了加快建仓，回涨时转向固收+。高估减半止盈。等估值被打下来后继续快速加仓。
    "标普500": {"keywords": ["标普500"],                 "vol_coef": 0.8, "entry": "2026-03-20", "target_ratio": 3, "phase": "ACC", "amount_per_share": 0, "link": ""},  #  017641 适中
    "纳斯达克100": {"keywords": ["纳斯达克100"],          "vol_coef": 1.0, "entry": "2026-03-20", "target_ratio": 10, "phase": "ACC", "amount_per_share": 0, "link": ""},  # 012752 适中
    "美股主动-全球优质企业": {"keywords": ["全球优质企业"], "vol_coef": 99, "entry": "2026-03-20", "target_ratio": 5, "phase": "ACC", "amount_per_share": 200, "link": ""},  # 100 + 50
    "美股主动-广发全球精选": {"keywords": ["广发全球精选"], "vol_coef": 99, "entry": "2026-04-15", "target_ratio": 5, "phase": "ACC", "amount_per_share": 200, "link": ""},  # 100 + 50
    "美股主动-全球成长精选": {"keywords": ["全球成长精选"], "vol_coef": 99, "entry": "2026-03-20", "target_ratio": 2, "phase": "ACC", "amount_per_share": 200, "link": ""},  # 100 + 50
    # AH股主动
    "A股价值主动-大成高鑫": {"keywords": ["大成高鑫"],       "vol_coef": 99, "entry": "2026-04-14", "target_ratio": 6, "phase": "ACC", "amount_per_share": 100, "link": ""},
    "A股价值主动-中欧红利": {"keywords": ["中欧红利"],       "vol_coef": 99, "entry": "2026-04-15", "target_ratio": 4, "phase": "ACC", "amount_per_share": 100, "link": ""},
    "A股成长主动-兴全合润": {"keywords": ["兴全合润"],       "vol_coef": 99, "entry": "2026-04-14", "target_ratio": 3, "phase": "ACC", "amount_per_share": 100, "link": ""},
    # A股固收+卫星
    "红利低波": {"keywords": ["红利低波"],                  "vol_coef": 0.8, "entry": "2026-04-13", "target_ratio": 6, "phase": "ACC", "amount_per_share": 100, "link": ""},
    "自由现金流": {"keywords": ["现金流"],                  "vol_coef": 0.8, "entry": "2026-04-13", "target_ratio": 6, "phase": "ACC", "amount_per_share": 100, "link": ""},
    # A股二级债基增强
    "二级债基-景颐招利": {"keywords": ["景颐招利"],        "vol_coef": 99, "entry": "2026-03-13", "target_ratio": 30, "phase": "ACC", "amount_per_share": 300, "link": "http://www.f5.igwfmc.com/main/jjcp/product/010011/detail.html"},
    "二级债基-瑞锦混合": {"keywords": ["瑞锦混合"],        "vol_coef": 99, "entry": "2026-03-13", "target_ratio": 8, "phase": "ACC", "amount_per_share": 300, "link": ""},
    "二级债基-安阳债券": {"keywords": ["安阳债券"],        "vol_coef": 99, "entry": "2026-03-13", "target_ratio": 5, "phase": "ACC", "amount_per_share": 300, "link": ""},
    # A股短债增强
    "现金2-景颐裕利": {"keywords": ["景颐裕利"],           "vol_coef": 99, "entry": "2026-04-16", "target_ratio": 2, "phase": "ACC", "amount_per_share": 0, "link": ""},
    "现金1-鼎泓债券": {"keywords": ["鼎泓债券"],           "vol_coef": 99, "entry": "2026-04-16", "target_ratio": 2, "phase": "ACC", "amount_per_share": 0, "link": ""},
    "现金短债": {"keywords": [],                         "vol_coef": 99, "entry": "2026-03-20", "target_ratio": 3, "phase": "ACC", "amount_per_share": 0, "link": ""},
    ########
    # A股，逢低布局
    "证券公司": {"keywords": ["证券公司"],        "vol_coef": 1.0, "entry": "2026-04-10", "target_ratio": 0, "phase": "FIX", "amount_per_share": 0, "link": ""},
    "主要消费红利": {"keywords": ["消费红利"],    "vol_coef": 0.8, "entry": "2026-03-20", "target_ratio": 0, "phase": "FIX", "amount_per_share": 0, "link": ""},   # 008929 低估
    "中证A500": {"keywords": ["A500"],           "vol_coef": 1.0, "entry": "2026-03-20", "target_ratio": 0, "phase": "WATCH", "amount_per_share": 0, "link": ""},
    "中证1000": {"keywords": ["1000"],           "vol_coef": 1.2, "entry": "2026-03-20", "target_ratio": 0, "phase": "WATCH", "amount_per_share": 0, "link": ""},
    "创业板": {"keywords": ["创业板"],           "vol_coef": 1.2, "entry": "2026-03-20", "target_ratio": 0, "phase": "WATCH", "amount_per_share": 0, "link": ""},
    "科创50": {"keywords": ["科创50"],           "vol_coef": 1.2, "entry": "2026-03-20", "target_ratio": 0, "phase": "WATCH", "amount_per_share": 0, "link": ""},
    "有色金属": {"keywords": ["有色金属"],        "vol_coef": 1.2, "entry": "2026-03-20", "target_ratio": 0, "phase": "WATCH", "amount_per_share": 0, "link": ""},
    "半导体": {"keywords": ["半导体"],           "vol_coef": 1.2, "entry": "2026-03-20", "target_ratio": 0, "phase": "WATCH", "amount_per_share": 0, "link": ""},
    "中证医疗": {"keywords": ["医疗"],           "vol_coef": 0.8, "entry": "2026-03-20", "target_ratio": 0, "phase": "WATCH", "amount_per_share": 0, "link": ""},  # 008929 低估
    # 港股，逢低布局
    "恒生科技": {"keywords": ["恒生科技"],        "vol_coef": 1.0, "entry": "2026-03-20", "target_ratio": 0, "phase": "FIX", "amount_per_share": 0, "link": ""},  # 020989 低估
    "港股通信息技术": {"keywords": ["信息技术"],   "vol_coef": 1.2, "entry": "2026-03-20", "target_ratio": 0, "phase": "WATCH", "amount_per_share": 0, "link": ""},   # 026755 适中
    "港股通创新药": {"keywords": ["创新药"],      "vol_coef": 1.1, "entry": "2026-03-20", "target_ratio": 0, "phase": "WATCH", "amount_per_share": 0, "link": ""},
    # 商品
    "黄金": {"keywords": ["黄金", "上海金"],      "vol_coef": 99, "entry": "2026-03-20", "target_ratio": 0, "phase": "WATCH", "amount_per_share": 0, "link": ""},
    "其他": {"keywords": [],                     "vol_coef": 99, "entry": "2026-03-20", "target_ratio": 0, "phase": "WATCH", "amount_per_share": 0, "link": ""},
}

# ==================== 定投份数计算规则 ====================
# 条件：每周日设定加仓份额，基于新份额日定投持续一周
# 纳指/标普：从适中开始，低估300，适中100，高估停止。
# 宽基/创业板指/科创50/港股信息技术/恒科/消费红利：从低估开始, 低估100，适中50，高估停止。
RULES = {
    # 短期均线（10日）：降权，作为辅助信号
    "ma10": [
        {"range": (-float('inf'), -8), "shares": 1.0},
        {"range": (-8, -4), "shares": 0.5},
        {"range": (-4, float('inf')), "shares": 0.0},
    ],
    # 中期均线（20日）：提权，与周调整匹配
    "ma20": [
        {"range": (-float('inf'), -6), "shares": 2.0},
        {"range": (-6, -2), "shares": 1.0},
        {"range": (-2, float('inf')), "shares": 0.0},
    ],
    # 长期均线（60日）：提权，捕捉熊市趋势
    "ma60": [
        {"range": (-float('inf'), -6), "shares": 2.0},
        {"range": (-6, -3), "shares": 1.0},
        {"range": (-3, float('inf')), "shares": 0.0},
    ],
    # 启动后回撤：主加仓机制，不受周调整影响
    # entry至今少于一年，按实际入场点的净值算。 
    #      如超过一年，按一年前的净值算，避免过度加仓。
    "since_entry": [
        {"range": (-float('inf'), -15), "shares": 3.0},  # 极端深跌（罕见）
        {"range": (-15, -10), "shares": 2.0},            # 深度回撤
        {"range": (-10, -5), "shares": 1.0},             # 中度回撤
        {"range": (-5, -3), "shares": 0.5},              # 轻度回撤
        {"range": (-3, float('inf')), "shares": 0.0},
    ],
    "max": 5.0, 
}

def get_contribution(deviation, rules):
    """根据偏离度获取贡献份数"""
    for rule in rules:
        low, high = rule["range"]
        if low < deviation <= high:
            return rule["shares"]
    return 0.0

def scale_rules(vol_coef):
    """根据vol_coef缩放RULES的range阈值"""
    scaled = {}
    for key in ["ma10", "ma20", "ma60", "since_entry"]:
        scaled[key] = []
        for rule in RULES[key]:
            low, high = rule["range"]
            # -inf 和 +inf 保持不变
            if low == float('inf'):
                new_low = float('inf')
            elif low == -float('inf'):
                new_low = -float('inf')
            else:
                new_low = low * vol_coef
            if high == float('inf'):
                new_high = float('inf')
            elif high == -float('inf'):
                new_high = -float('inf')
            else:
                new_high = high * vol_coef
            scaled[key].append({"range": (new_low, new_high), "shares": rule["shares"]})
    return scaled

def calc_shares(ma10_dev, ma20_dev, ma60_dev, since_entry_dev=0, vol_coef=1.0):
    """计算定投份数，vol_coef为阈值系数，返回(total, ma10, ma20, ma60, since_entry)"""
    scaled = scale_rules(vol_coef)
    ma10_c = get_contribution(ma10_dev, scaled["ma10"])
    ma20_c = get_contribution(ma20_dev, scaled["ma20"])
    ma60_c = get_contribution(ma60_dev, scaled["ma60"])
    since_c = get_contribution(since_entry_dev, scaled["since_entry"])
    total = min(ma10_c + ma20_c + ma60_c + since_c, RULES["max"])
    return total, ma10_c, ma20_c, ma60_c, since_c


def calc_since_entry_dev(df_asc, entry_date, current_date, current_nav):
    """计算距入场点偏离度（窗口一年）

    Args:
        df_asc: 升序排列的基金净值DataFrame（需含'净值日期'和'单位净值'列）
        entry_date: 入场日期（pd.Timestamp）
        current_date: 当前日期（pd.Timestamp）
        current_nav: 当前净值

    Returns:
        since_entry_dev: 偏离度百分比，0表示无法计算
    """
    if entry_date is None or current_nav is None:
        return 0
    entry_date = entry_date.normalize()
    current_date = current_date.normalize()
    one_year_ago = current_date - pd.DateOffset(years=1)
    df_asc_copy = df_asc.copy()
    df_asc_copy['净值日期'] = pd.to_datetime(df_asc_copy['净值日期']).dt.normalize()
    entry_data = df_asc_copy[df_asc_copy['净值日期'] >= entry_date]
    if len(entry_data) == 0:
        return 0
    entry_nav = entry_data.iloc[0]['单位净值']
    if entry_date <= one_year_ago:
        # 超过一年：找current_date往前一年的净值
        window_data = df_asc_copy[df_asc_copy['净值日期'] >= one_year_ago]
        if len(window_data) > 0:
            ref_nav = window_data.iloc[0]['单位净值']
        else:
            ref_nav = entry_nav
    else:
        ref_nav = entry_nav
    return (current_nav - ref_nav) / ref_nav * 100


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
    return f"{value:+.2f}%" if value != 0 else "0.00%"


def format_rebalance_yuan(value_yuan, pct_of_total):
    """格式化再平衡金额颜色：正=买入=绿，负=卖出=红"""
    if value_yuan is None:
        return "--"
    if value_yuan > 0:
        return f'<span style="color: green; font-weight: bold;">+{value_yuan:.0f}</span> ({pct_of_total:.1f}%)'
    elif value_yuan < 0:
        return f'<span style="color: red; font-weight: bold;">{value_yuan:.0f}</span> ({pct_of_total:.1f}%)'
    return f'<span style="color: gray;">0</span> (0.0%)'


def chart_to_html(chart):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        temp_path = f.name
    chart.render(temp_path)
    with open(temp_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    os.unlink(temp_path)
    fixed_html = html_content.replace('<head>', '<head><script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>')
    return f'<div style="width:100%; height:550px; border:1px solid #333; border-radius:10px; overflow:hidden; background:#1a1a1a;">' \
           f'<iframe srcdoc="{html.escape(fixed_html)}" style="width:100%; height:100%; border:none;" ' \
           f'sandbox="allow-scripts allow-same-origin allow-popups allow-forms"></iframe></div>'


def get_fund_data(fund_code):
    df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
    df = df.sort_values('净值日期', ascending=False).reset_index(drop=True)
    df['单位净值'] = pd.to_numeric(df['单位净值'], errors='coerce')
    df['日增长率'] = pd.to_numeric(df['日增长率'], errors='coerce')
    return df


def get_fund_positions_data():
    read = from_positions("./CMB/fund_positions.csv", skiprows=0)
    sysopen = mulfix_pos(status=read)
    return sysopen, sysopen.combsummary()


def get_fund_categories():
    sysopen, summary_df = get_fund_positions_data()
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


def parse_cmb_trade_csv():
    """解析招商银行交易记录CSV"""
    path = "./CMB/trade_records.csv"
    for enc in ['gb2312', 'gbk', 'utf-8']:
        try:
            with open(path, 'r', encoding=enc) as f:
                lines = f.readlines()
            break
        except UnicodeDecodeError:
            continue

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

    df['code'] = df['交易备注'].apply(lambda x: re.search(r'\d{5,6}', str(x).strip()).group() if re.search(r'\d{5,6}', str(x).strip()) else None)
    return df


def get_trade_category(code):
    """根据基金代码获取分类"""
    sysopen, summary_df = get_fund_positions_data()
    code_to_name = dict(zip(summary_df['产品代码'].astype(str), summary_df['简称']))
    name = code_to_name.get(code, "未知")
    for cat_name, config in category_config.items():
        if config["keywords"] and any(k in name for k in config["keywords"]):
            return cat_name
    return "其他"


# ==================== 图表创建 ====================
def create_fund_pos_ratio_chart():
    sysopen, summary_df = get_fund_positions_data()
    chart = sysopen.v_positions(category_config, rendered=False)

    # 左侧标签颜色改成白色
    if "legend" in chart.options and len(chart.options["legend"]) > 0:
        chart.options["legend"][0]["textStyle"] = {"color": "#FFFFFF"}

    # 标题颜色改成白色，保持原有文本和位置
    title_opts = chart.options.get("title", [])
    if isinstance(title_opts, list) and len(title_opts) > 0:
        if "textStyle" not in title_opts[0]:
            title_opts[0]["textStyle"] = {}
        title_opts[0]["textStyle"]["color"] = "#FFFFFF"

    for s in chart.options.get("series", []):
        if s.get("type") == "pie":
            s["center"] = ["65%", "50%"]
    return chart


def create_trade_records_charts():
    """创建权益类申购记录折线图"""
    try:
        df = parse_cmb_trade_csv()

        trans_types = ["基金定期定额申购", "基金申购", "基金赎回"]
        df_filtered = df[df['交易类型'].isin(trans_types) & df['code'].notna()].copy()
        df_filtered['收入'] = pd.to_numeric(df_filtered['收入'], errors='coerce').fillna(0)
        df_filtered['支出'] = pd.to_numeric(df_filtered['支出'], errors='coerce').fillna(0)
        df_filtered['交易类型合并'] = df_filtered['交易类型'].apply(
            lambda x: '申购' if x in ['基金定期定额申购', '基金申购'] else '赎回'
        )
        df_filtered['category'] = df_filtered['code'].apply(get_trade_category)
        df_filtered['交易日期_str'] = df_filtered['交易日期'].apply(
            lambda x: str(int(float(x))) if not pd.isna(x) else None
        )
        df_filtered = df_filtered[df_filtered['交易日期_str'].notna()].copy()

        # 用持仓市值过滤，持仓少于50元的分类不显示
        _, summary_df = get_fund_positions_data()
        code_to_name = dict(zip(summary_df['产品代码'].astype(str), summary_df['简称']))
        summary_df['分类'] = summary_df['简称'].apply(lambda name: next(
            (cat for cat, cfg in category_config.items()
             if cfg["keywords"] and any(k in name for k in cfg["keywords"])), "其他"
        ))
        cat_mv = summary_df.groupby('分类')['参考市值'].sum()
        valid_categories = {cat for cat, mv in cat_mv.items() if mv >= 50}

        all_dates = sorted(df_filtered['交易日期_str'].unique())
        x_dates = [d[2:] if len(d) == 8 else d for d in all_dates]

        purchase_lines = []
        categories = sorted([c for c in df_filtered['category'].unique() if c != "其他" and c in valid_categories])

        for cat in categories:
            if cat == "二级债基":
                continue
            df_cat = df_filtered[df_filtered['category'] == cat]
            purchase_values = [
                df_cat[(df_cat['交易日期_str'] == d) & (df_cat['交易类型合并'] == '申购')]['支出'].sum()
                for d in all_dates
            ]
            cumulative = []
            total = 0
            for v in purchase_values:
                total += v
                cumulative.append(total)
            purchase_lines.append((cat, cumulative))

        purchase_chart = (
            Line(init_opts=opts.InitOpts(width="100%", height="400px", theme=ThemeType.MACARONS, bg_color="#1a1a1a"))
            .add_xaxis(x_dates)
        )
        for name, values in purchase_lines:
            purchase_chart.add_yaxis(name, values, is_symbol_show=False, linestyle_opts=opts.LineStyleOpts(width=2))

        purchase_chart.set_global_opts(
            title_opts=opts.TitleOpts(title="权益类申购（累计金额）", title_textstyle_opts=opts.TextStyleOpts(color="#FFFFFF")),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
            legend_opts=opts.LegendOpts(pos_top="5%", textstyle_opts=opts.TextStyleOpts(color="#FFFFFF")),
            xaxis_opts=opts.AxisOpts(name="日期", name_textstyle_opts=opts.TextStyleOpts(color="#CCCCCC"), axislabel_opts=opts.LabelOpts(color="#CCCCCC")),
            yaxis_opts=opts.AxisOpts(name="累计金额", name_textstyle_opts=opts.TextStyleOpts(color="#CCCCCC"), axislabel_opts=opts.LabelOpts(color="#CCCCCC")),
        )
        purchase_chart.set_series_opts(label_opts=opts.LabelOpts(is_show=False))
        return [purchase_chart]
    except:
        return None


def create_erp_chart():
    """创建股债性价比(ERP)图表"""
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
    os.makedirs(cache_dir, exist_ok=True)
    pe_cache_file = os.path.join(cache_dir, "erp_pe_cache.csv")
    bond_cache_file = os.path.join(cache_dir, "erp_bond_cache.csv")

    today = pd.Timestamp.today().normalize()  # 去掉时间部分，只保留日期
    today_str = today.strftime("%Y%m%d")
    three_days_ago = today - pd.Timedelta(days=3)

    # 处理PE数据
    df_pe = None
    if os.path.exists(pe_cache_file):
        df_pe = pd.read_csv(pe_cache_file, parse_dates=["日期"])
        df_pe = df_pe.set_index("日期").sort_index()

    # 如果缓存不存在或数据超过3天，则获取新数据
    need_fetch_pe = True
    if df_pe is not None and len(df_pe) > 0:
        latest_pe_date = df_pe.index.max().normalize()
        # 如果最新数据在3天内，不需要获取
        if latest_pe_date >= three_days_ago:
            need_fetch_pe = False

    if need_fetch_pe:
        # akshare的PE数据可以直接获取全部历史
        df_pe_new = ak.stock_index_pe_lg(symbol="沪深300")
        df_pe_new["日期"] = pd.to_datetime(df_pe_new["日期"])
        df_pe_new = df_pe_new.rename(columns={"滚动市盈率": "pe_ttm"}).set_index("日期")[["pe_ttm"]].dropna()
        if df_pe is not None:
            df_pe = pd.concat([df_pe, df_pe_new[df_pe_new.index > df_pe.index.max()]]).sort_index()
        else:
            df_pe = df_pe_new
        df_pe.to_csv(pe_cache_file)

    df_pe = df_pe.resample("ME").last()

    # 处理国债收益率数据（逐年获取）
    df_bond = None
    if os.path.exists(bond_cache_file):
        df_bond = pd.read_csv(bond_cache_file, parse_dates=["日期"])
        df_bond = df_bond.set_index("日期").sort_index()

    # 如果缓存不存在或数据超过3天，则获取新数据
    need_fetch_bond = True
    if df_bond is not None and len(df_bond) > 0:
        latest_bond_date = df_bond.index.max().normalize()
        # 如果最新数据在3天内，不需要获取
        if latest_bond_date >= three_days_ago:
            need_fetch_bond = False

    if need_fetch_bond:
        # akshare国债数据只能逐年获取，从2020年开始逐年补充到今年
        start_year = 2020
        end_year = today.year
        df_bond_all = []
        for year in range(start_year, end_year + 1):
            year_start = f"{year}0101"
            year_end = f"{year}1231" if year < end_year else today_str
            try:
                df_year = ak.bond_china_yield(start_date=year_start, end_date=year_end)
                df_year = df_year[df_year["曲线名称"] == "中债国债收益率曲线"]
                df_year = df_year[["日期", "10年"]].rename(columns={"10年": "bond_yield"})
                df_year["日期"] = pd.to_datetime(df_year["日期"]).dt.tz_localize(None)
                df_bond_all.append(df_year)
            except:
                continue
        if df_bond_all:
            df_bond_new = pd.concat(df_bond_all).set_index("日期").sort_index()
            if df_bond is not None:
                df_bond = pd.concat([df_bond, df_bond_new[df_bond_new.index > df_bond.index.max()]]).sort_index()
            else:
                df_bond = df_bond_new
            df_bond.to_csv(bond_cache_file)

    df_bond = df_bond.resample("ME").last()

    df = pd.merge(df_pe, df_bond, left_index=True, right_index=True, how="inner").dropna()
    if df.empty:
        return None

    df["erp"] = (1 / df["pe_ttm"] - df["bond_yield"] / 100) * 100
    dates = df.index.strftime("%Y-%m").tolist()

    return (
        Line(init_opts=opts.InitOpts(width="100%", height="500px", theme=ThemeType.MACARONS, bg_color="#1a1a1a"))
        .add_xaxis(dates)
        .add_yaxis("ERP(股债利差) %", df["erp"].round(2).tolist(), yaxis_index=0, is_symbol_show=False, linestyle_opts=opts.LineStyleOpts(width=3))
        .add_yaxis("10年期国债收益率 %", df["bond_yield"].round(2).tolist(), yaxis_index=1, is_symbol_show=False, linestyle_opts=opts.LineStyleOpts(width=1.5))
        .add_yaxis("ERP均值 %", [5.0] * len(dates), yaxis_index=0, is_symbol_show=False, linestyle_opts=opts.LineStyleOpts(type_="dashed"))
        .add_yaxis("80%分位(风险区) %", [4.3] * len(dates), yaxis_index=0, is_symbol_show=False, linestyle_opts=opts.LineStyleOpts(type_="dashed"))
        .add_yaxis("20%分位(机会区) %", [5.9] * len(dates), yaxis_index=0, is_symbol_show=False, linestyle_opts=opts.LineStyleOpts(type_="dashed"))
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


def create_fund_trend_chart(fund_code="019547"):
    """创建基金走势图（5年数据）"""
    try:
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
        df['净值日期'] = pd.to_datetime(df['净值日期'])
        df = df.sort_values('净值日期', ascending=True).reset_index(drop=True)
        df['单位净值'] = pd.to_numeric(df['单位净值'], errors='coerce')

        latest_date = df['净值日期'].max()
        df = df[df['净值日期'] >= (latest_date - timedelta(days=5*365))]

        fund_categories = get_fund_categories()
        category_name = fund_code
        for cat, funds in fund_categories.items():
            for f in funds:
                if f["code"] == fund_code:
                    category_name = f"{cat} {fund_code}"
                    break

        dates = df['净值日期'].dt.strftime('%Y-%m-%d').tolist()
        nav_values = df['单位净值'].tolist()

        return (
            Line(init_opts=opts.InitOpts(width="100%", height="400px", theme=ThemeType.MACARONS, bg_color="#1a1a1a"))
            .add_xaxis(dates)
            .add_yaxis("单位净值", nav_values, is_symbol_show=False)
            .set_global_opts(
                title_opts=opts.TitleOpts(title=f"基金详情 {category_name}", title_textstyle_opts=opts.TextStyleOpts(color="#FFFFFF")),
                tooltip_opts=opts.TooltipOpts(trigger="axis"),
                legend_opts=opts.LegendOpts(pos_top="5%", textstyle_opts=opts.TextStyleOpts(color="#FFFFFF")),
                xaxis_opts=opts.AxisOpts(name="日期", name_textstyle_opts=opts.TextStyleOpts(color="#CCCCCC"), axislabel_opts=opts.LabelOpts(color="#CCCCCC")),
                yaxis_opts=opts.AxisOpts(name="单位净值", name_textstyle_opts=opts.TextStyleOpts(color="#CCCCCC"), axislabel_opts=opts.LabelOpts(color="#CCCCCC"), splitline_opts=opts.SplitLineOpts(is_show=True, linestyle_opts=opts.LineStyleOpts(color="#333333")), min_="dataMin"),
            )
            .set_series_opts(label_opts=opts.LabelOpts(is_show=False))
        )
    except:
        return None


# ==================== 数字功能函数 ====================
def fund_pos_detail():
    try:
        _, summary_df = get_fund_positions_data()
        result = "| 产品代码 | 简称 | 基金份额 | 单位净值 | 总成本 | 参考市值 | 浮动盈亏 | 收益率 | 占比 |\n"
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
        _, summary_df = get_fund_positions_data()

        # 按分类汇总市值，计算分类级别的当前占比（与v_positions保持一致）
        summary_df['分类'] = summary_df['简称'].apply(lambda name: next(
            (cat for cat, cfg in category_config.items()
             if any(k in name for k in cfg.get("keywords", []))), "其他"
        ))
        # 只取ACC分类的基金来计算百分比
        df_acc = summary_df[summary_df['分类'].apply(lambda x: category_config.get(x, {}).get("phase") == "ACC")]
        cat_mv = df_acc.groupby('分类')['参考市值'].sum()
        # 分母应该是总资产（基金市值+现金），与v_positions一致
        total_mv = summary_df['参考市值'].sum()
        sysopen, _ = get_fund_positions_data()
        grand_total = total_mv + sysopen.cash
        cat_current_ratio = (cat_mv / grand_total * 100) if grand_total > 0 else {}
        # 现金短债单独处理（不在summary_df里，市值在sysopen.cash）
        if sysopen.cash > 0:
            cat_current_ratio["现金短债"] = sysopen.cash / grand_total * 100

        table_data = []

        for cat_name, funds in fund_categories.items():
            # 只列出 phase 为 ACC 的基金
            if category_config.get(cat_name, {}).get("phase") != "ACC":
                continue
            funds_to_show = funds if cat_name == "二级债基" else funds[:1]
            for idx, fund in enumerate(funds_to_show):
                try:
                    df = get_fund_data(fund["code"])
                    if df.empty or len(df) < 3:
                        continue

                    latest_nav = df.iloc[0]['单位净值']
                    # 只保留1日涨跌
                    if len(df) > 1:
                        nav_1_ago = df.iloc[1]['单位净值']
                        change_1d = (latest_nav - nav_1_ago) / nav_1_ago * 100
                    else:
                        change_1d = None

                    # 计算距20日均值（当前净值与过去20个交易日均值百分比差值）
                    if len(df) > 20:
                        nav_20_avg = df.iloc[1:21]['单位净值'].mean()
                        change_20_avg = (latest_nav - nav_20_avg) / nav_20_avg * 100
                    else:
                        change_20_avg = None

                    # 计算距60日均值（当前净值与过去60个交易日均值百分比差值）
                    if len(df) > 60:
                        nav_60_avg = df.iloc[1:61]['单位净值'].mean()
                        change_60_avg = (latest_nav - nav_60_avg) / nav_60_avg * 100
                    else:
                        change_60_avg = None

                    # 计算距5日均值（当前净值与过去5个交易日均值百分比差值）
                    if len(df) >= 5:
                        nav_5_avg = df.iloc[1:6]['单位净值'].mean()
                        change_5_avg = (latest_nav - nav_5_avg) / nav_5_avg * 100
                    else:
                        nav_5_avg = None
                        change_5_avg = None

                    # 计算距10日均值（当前净值与过去10个交易日均值百分比差值）
                    if len(df) >= 10:
                        nav_10_avg = df.iloc[1:11]['单位净值'].mean()
                        change_10_avg = (latest_nav - nav_10_avg) / nav_10_avg * 100
                    else:
                        nav_10_avg = None
                        change_10_avg = None

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

                    # 获取该分类的vol_coef用于判断是否为债券基金
                    vol_coef = category_config.get(cat_name, {}).get("vol_coef", 1.0)
                    entry_date_str = category_config.get(cat_name, {}).get("entry", None)

                    # 计算距入场点涨跌（窗口一年）
                    if entry_date_str:
                        entry_date = pd.to_datetime(entry_date_str).normalize()
                        today_start = pd.Timestamp.today().normalize()
                        one_year_ago = today_start - pd.DateOffset(years=1)
                        df_asc_for_entry = df.sort_values('净值日期', ascending=True).copy()
                        df_asc_for_entry['净值日期'] = pd.to_datetime(df_asc_for_entry['净值日期']).dt.normalize()
                        entry_data = df_asc_for_entry[df_asc_for_entry['净值日期'] >= entry_date]
                        if len(entry_data) > 0:
                            entry_nav = entry_data.iloc[0]['单位净值']
                            entry_nav_date = entry_data.iloc[0]['净值日期'].strftime('%m-%d')
                            # 入场至今是否超过一年：比较入场日期和 today-1年
                            if entry_date <= one_year_ago:
                                # 超过一年：找今天往前一年那个日期的净值
                                window_data = df_asc_for_entry[df_asc_for_entry['净值日期'] >= one_year_ago]
                                if len(window_data) > 0:
                                    window_nav = window_data.iloc[0]['单位净值']
                                    since_entry_dev = (latest_nav - window_nav) / window_nav * 100
                                else:
                                    # 找不到用入场净值
                                    ref_nav = entry_nav
                                    since_entry_dev = (latest_nav - ref_nav) / ref_nav * 100
                                ref_date_str = None
                            else:
                                # 不足一年：用入场时净值
                                ref_nav = entry_nav
                                ref_date_str = entry_nav_date
                                since_entry_dev = (latest_nav - ref_nav) / ref_nav * 100
                        else:
                            entry_nav = None
                            entry_nav_date = None
                            since_entry_dev = 0
                            ref_date_str = None
                    else:
                        entry_nav = None
                        entry_nav_date = None
                        since_entry_dev = 0
                        ref_date_str = None

                    # 计算份额偏离度（按分类汇总计算）
                    target_ratio = category_config.get(cat_name, {}).get("target_ratio", 0)
                    current_ratio = cat_current_ratio.get(cat_name, 0)
                    if target_ratio > 0:
                        ratio_dev = (current_ratio - target_ratio) / target_ratio
                    else:
                        ratio_dev = None

                    # 二级债基第一个基金直接填入amount_per_share
                    is_bond_first = (vol_coef >= 99 and cat_name == "二级债基" and idx == 0)

                    table_data.append({"category": cat_name, "code": fund["code"], "name": fund["name"],
                                       "drawdown": drawdown, "peak_date": peak_date, "one_day_date": one_day_date,
                                       "change_1d": change_1d, "change_5_avg": change_5_avg, "change_10_avg": change_10_avg,
                                       "change_20_avg": change_20_avg, "change_60_avg": change_60_avg,
                                       "since_entry_dev": since_entry_dev, "ref_date_str": ref_date_str,
                                       "ratio_dev": ratio_dev, "current_ratio": current_ratio, "target_ratio": target_ratio,
                                       "amount_per_share": category_config.get(cat_name, {}).get("amount_per_share", 0),
                                       "is_bond_first": is_bond_first})
                except:
                    continue

        if not table_data:
            return "❌ 无法获取任何基金数据"

        # ========== 计算22天定投修复方案 ==========
        # 构建所有ACC分类的偏离数据（按分类汇总，非按基金）
        all_cats = list(cat_current_ratio.keys())
        cat_data_for_calc = []
        for cat in all_cats:
            target = category_config.get(cat, {}).get("target_ratio", 0)
            current = cat_current_ratio.get(cat, 0)
            if target > 0 or current > 0:
                cat_data_for_calc.append({
                    "cat": cat,
                    "target_ratio": target,
                    "current_ratio": current,
                })

        # 计算最优月定投金额M（使修复后偏离度最小）
        # M > 0: 新增资金买入低配分类，超配分类卖出
        # M = 0: 不操作
        def calc_squared_dev(M, cat_list, grand_total):
            """给定月定投金额M，计算所有分类的平方偏离总和"""
            # total_excess和total_shortfall都在百分比单位（points）
            total_excess = sum(max(0, c["current_ratio"] - c["target_ratio"]) for c in cat_list)
            total_shortfall = sum(max(0, c["target_ratio"] - c["current_ratio"]) for c in cat_list)
            # grand_total（总资产）用于计算月后新市值占比
            total_mv = sum(c["current_ratio"] for c in cat_list)  # 当前各分类百分比之和

            total_dev = 0
            for c in cat_list:
                excess = max(0, c["current_ratio"] - c["target_ratio"])
                shortfall = max(0, c["target_ratio"] - c["current_ratio"])

                if excess > 0:
                    # 超配分类：按过剩比例卖出（卖出金额=过剩百分比*grand_total*M的份额）
                    sell_ratio = excess / total_excess * M if total_excess > 0 else 0
                    new_mv = c["current_ratio"] - sell_ratio
                else:
                    # 低配分类：按短缺比例买入
                    buy_ratio = shortfall / total_shortfall * M if total_shortfall > 0 else 0
                    new_mv = c["current_ratio"] + buy_ratio

                new_total_ratio = total_mv + M  # 总额（百分比）变化
                new_ratio = new_mv / new_total_ratio * 100 if new_total_ratio > 0 else 0
                dev = (new_ratio - c["target_ratio"])
                total_dev += dev ** 2
            return total_dev

        # 数值优化：搜索最优M
        from scipy.optimize import minimize_scalar
        total_excess = sum(max(0, c["current_ratio"] - c["target_ratio"]) for c in cat_data_for_calc)
        upper_bound = max(total_excess * 2, 1)

        result_opt = minimize_scalar(
            lambda M: calc_squared_dev(M, cat_data_for_calc, grand_total),
            bounds=(0, upper_bound),
            method='bounded'
        )
        optimal_M = result_opt.x

        # 计算每个分类的月/日定投金额
        total_excess = sum(max(0, c["current_ratio"] - c["target_ratio"]) for c in cat_data_for_calc)
        total_shortfall = sum(max(0, c["target_ratio"] - c["current_ratio"]) for c in cat_data_for_calc)
        total_mv = sum(c["current_ratio"] for c in cat_data_for_calc)

        for c in cat_data_for_calc:
            excess = max(0, c["current_ratio"] - c["target_ratio"])
            shortfall = max(0, c["target_ratio"] - c["current_ratio"])

            if excess > 0:
                # 超配分类：按过剩比例卖出（负投资）
                sell_ratio = excess / total_excess * optimal_M if total_excess > 0 else 0
                c["monthly_invest"] = -sell_ratio
                c["daily_invest"] = -sell_ratio / 22
                new_mv = c["current_ratio"] - sell_ratio
            else:
                # 低配分类：按短缺比例买入（正投资）
                buy_ratio = shortfall / total_shortfall * optimal_M if total_shortfall > 0 else 0
                c["monthly_invest"] = buy_ratio
                c["daily_invest"] = buy_ratio / 22
                new_mv = c["current_ratio"] + buy_ratio

            new_total_ratio = total_mv + optimal_M
            c["new_ratio"] = new_mv / new_total_ratio * 100 if new_total_ratio > 0 else 0
            c["post_dev"] = (c["new_ratio"] - c["target_ratio"]) / c["target_ratio"] if c["target_ratio"] > 0 else None

        # 建立 cat -> daily_invest, post_dev, new_ratio 的映射
        cat_daily_invest = {c["cat"]: c["daily_invest"] for c in cat_data_for_calc}
        cat_post_dev = {c["cat"]: c["post_dev"] for c in cat_data_for_calc}
        cat_new_ratio = {c["cat"]: c["new_ratio"] for c in cat_data_for_calc}
        # ========== 计算结束 ==========

        result = "| 分类 | 基金代码 | 基金简称 | 日定投 | 月后偏离 | 份额偏离 | 最新涨跌 | 距MA5 | 距MA10 | 距MA20 | 距MA60 | 距入场点(窗口一年) | 距一年高点 |\n"
        result += "|------|-------|-------|------------|------------|------------|--------|--------|--------|--------|-------------------|----------------|------|\n"

        # total_daily = 总卖出金额 = 总买入金额（M/22）
        total_daily = optimal_M / 22

        for item in table_data:
            if item["drawdown"] is None:
                dd_str = "--"
            else:
                dd_str = format_percentage(-item["drawdown"], color_mode=True) + f' <span style="color: gray;">({item["peak_date"]})</span>'
            change_60_str = format_percentage(item["change_60_avg"], color_mode=True) if item["change_60_avg"] is not None else "--"
            change_20_str = format_percentage(item["change_20_avg"], color_mode=True) if item["change_20_avg"] is not None else "--"
            change_10_str = format_percentage(item["change_10_avg"], color_mode=True) if item["change_10_avg"] is not None else "--"
            change_5_str = format_percentage(item["change_5_avg"], color_mode=True) if item["change_5_avg"] is not None else "--"
            change_1d_str = format_percentage(item["change_1d"], color_mode=True) if item["change_1d"] is not None else "--"
            change_1d_full = change_1d_str + f' <span style="color: gray;">({item["one_day_date"]})</span>' if item["one_day_date"] else change_1d_str
            since_entry_str = format_percentage(item["since_entry_dev"], color_mode=True) if item["since_entry_dev"] is not None else "--"
            if item["ref_date_str"]:
                since_entry_str += f' <span style="color: gray;">({item["ref_date_str"]})</span>'
            ratio_dev = item["ratio_dev"]
            if ratio_dev is None:
                ratio_str = "---"
            else:
                ratio_str = format_percentage(ratio_dev * 100, color_mode=True) + f' <span style="color: gray;">({item["current_ratio"]:.2f}%/{item["target_ratio"]}%)</span>'
            # 日定投金额（按分类计算，正=买入，负=卖出）
            # cat_daily_invest 是百分点，需转为元
            daily_inv_pct = cat_daily_invest.get(item["category"], 0)
            daily_inv_yuan = daily_inv_pct * grand_total / 100
            abs_daily_yuan = abs(daily_inv_yuan)
            # 百分比基于总再平衡金额（卖出=买入，各占50%）
            pct_of_total = abs_daily_yuan / (total_daily * grand_total / 100 * 2) * 100 if total_daily > 0 else 0
            amount_str = format_rebalance_yuan(daily_inv_yuan, pct_of_total)
            # 月后偏离
            post_dev = cat_post_dev.get(item["category"], None)
            new_ratio = cat_new_ratio.get(item["category"], None)
            if post_dev is None or new_ratio is None:
                post_dev_str = "---"
            else:
                post_dev_str = format_percentage(post_dev * 100, color_mode=True) + f' <span style="color: gray;">({new_ratio:.2f}%/{item["target_ratio"]}%)</span>'
            result += f"| {item['category']} | {item['code']} | {item['name']} | {amount_str} | {post_dev_str} | {ratio_str} | {change_1d_full} | {change_5_str} | {change_10_str} | {change_20_str} | {change_60_str} | {since_entry_str} | {dd_str} |\n"

        # 现金短债单独一行
        cash_target = category_config.get("现金短债", {}).get("target_ratio", 0)
        cash_ratio = cat_current_ratio.get("现金短债", 0)
        cash_dev = (cash_ratio - cash_target) / cash_target if cash_target > 0 else None
        if cash_dev is None:
            cash_dev_str = "---"
        else:
            cash_dev_str = format_percentage(cash_dev * 100, color_mode=True) + f' <span style="color: gray;">({cash_ratio:.2f}%/{cash_target}%)</span>'
        cash_daily_pct = cat_daily_invest.get("现金短债", 0)
        cash_daily_yuan = cash_daily_pct * grand_total / 100
        cash_abs = abs(cash_daily_yuan)
        cash_pct = cash_abs / (total_daily * grand_total / 100 * 2) * 100 if total_daily > 0 else 0
        cash_amount_str = format_rebalance_yuan(cash_daily_yuan, cash_pct)
        cash_post_dev = cat_post_dev.get("现金短债", None)
        cash_new_ratio = cat_new_ratio.get("现金短债", None)
        if cash_post_dev is None or cash_new_ratio is None:
            cash_post_dev_str = "---"
        else:
            cash_post_dev_str = format_percentage(cash_post_dev * 100, color_mode=True) + f' <span style="color: gray;">({cash_new_ratio:.2f}%/{cash_target}%)</span>'
        result += f"| 现金短债 | - | 现金短债 | {cash_amount_str} | {cash_post_dev_str} | {cash_dev_str} | -- | -- | -- | -- | -- | -- | -- |\n"

        return result
    except Exception as e:
        return f"❌ 获取基金数据失败: {str(e)}"


def get_fund_detail(fund_code=None):
    """指定基金详情"""
    try:
        fund_code = fund_code or "019547"
        fund_categories = get_fund_categories()

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

        dj_index_code_map = {"恒生科技": "HKHSTECH", "主要消费红利": "CSIH30094", "纳斯达克100": "NDX", "标普500": "SP500"}
        etfrun_index_code_map = {"中证A500": "SSE/000510", "主要消费红利": "CSI/h30094"}

        df = get_fund_data(fund_code)
        intervals = [260, 160, 80, 40, 20, 10, 5, 4, 3, 2, 1]
        interval_names = ["260日", "160日", "80日", "40日", "20日", "10日", "5日", "4日", "3日", "2日", "1日"]

        data_rows = []
        for days, name in zip(intervals, interval_names):
            if len(df) > days:
                nav = df.iloc[days]['单位净值']
                date = df.iloc[0 if days == 1 else days]['净值日期'].strftime('%m-%d')
                data_rows.append({"时间点": name, "日期": date, "净值": nav})

        result = f"📈 **基金详情 - {target_fund['name']} ({target_fund['code']})**\n\n"
        result += f"分类: {target_category}\n"
        result += f"数据截止: {df.iloc[0]['净值日期'].strftime('%Y-%m-%d')}\n\n"
        result += "| 指标 |" + "".join([f" {r['时间点']} |" for r in data_rows]) + "\n"
        result += "|------|" + "".join(["------|" for _ in data_rows]) + "\n"
        result += "| 日期 |" + "".join([f" {r['日期']} |" for r in data_rows]) + "\n"
        result += "| 净值 |" + "".join([f" {r['净值']:.4f} |" for r in data_rows]) + "\n"

        latest_nav = df.iloc[0]['单位净值']
        result += "| 涨跌幅 |"
        for row in data_rows:
            change = (latest_nav - row['净值']) / row['净值'] * 100
            result += f" {format_percentage(change, color_mode=True)} |"
        result += "\n\n---\n\n### 📊 估值查询\n"

        if target_category in dj_index_code_map:
            index_code = dj_index_code_map[target_category]
            result += f"**查看估值详情**\n\n🔗 [点击查看 {target_category} 指数估值（雪球基金）](https://danjuanfunds.com/dj-valuation-table-detail/{index_code})\n\n指数代码: {index_code}（雪球基金）\n\n"

        if target_category in etfrun_index_code_map:
            index_code = etfrun_index_code_map[target_category]
            result += f"**查看估值详情**\n\n🔗 [点击查看 {target_category} 指数估值（etf.run）](https://www.etf.run/index/{index_code})\n\n指数代码: {index_code}（etf.run）\n\n"

        result += "**其他PE/PB数据:**\n- 且慢: https://qieman.com/idx-eval\n"
        return result
    except Exception as e:
        return f"❌ 查询失败: {str(e)}"


def _build_position_health_prompt() -> str:
    """对持仓>1%的类别联网搜索行业新闻，构建持仓体检分析段落"""
    try:
        from financial_news import FinancialNewsFetcher

        sysopen, summary_df = get_fund_positions_data()
        df = sysopen.df.copy()
        total_value = sysopen.total_market_value + sysopen.cash

        def classify(name):
            for category, config in category_config.items():
                for keyword in config.get("keywords", []):
                    if keyword in name:
                        return category
            return "其他"

        df["分类"] = df["简称"].apply(classify)
        cat_df = df.groupby("分类").agg({"参考市值": "sum"}).reset_index()
        cat_df = cat_df[cat_df["参考市值"] / total_value > 0.01].sort_values("参考市值", ascending=False)

        if cat_df.empty:
            return ""

        # 行业关键词映射
        industry_queries = {
            "纳斯达克100": ["纳斯达克100 科技股", "Nasdaq tech stocks"],
            "标普500": ["标普500 美股", "S&P 500 stock market"],
            "全球主动": ["QDII 全球基金 投资"],
            "中证A500": ["中证A500 A股", "A股 中证A500"],
            "中证1000": ["中证1000 小盘股"],
            "创业板": ["创业板 创业板指"],
            "科创50": ["科创50 科创板"],
            "有色金属": ["有色金属 矿业 大宗商品"],
            "半导体": ["半导体 芯片 集成电路"],
            "证券公司": ["证券行业 券商 股市"],
            "主要消费红利": ["消费红利 食品饮料 消费"],
            "中证医疗": ["医疗行业 医药 医疗器械"],
            "恒生科技": ["恒生科技 港股 科技"],
            "港股通信息技术": ["港股 信息技术 科技"],
            "港股通创新药": ["港股 创新药 生物医药"],
            "红利低波": ["红利低波 中证红利"],
            "自由现金流": ["自由现金流 价值投资"],
            "二级债基": ["债券基金 固收 债市"],
        }

        fetcher = FinancialNewsFetcher()
        lines = []
        for _, row in cat_df.iterrows():
            cat_name = row["分类"]
            pos_pct = row["参考市值"] / total_value * 100
            if pos_pct < 1:
                continue

            queries = industry_queries.get(cat_name, [cat_name])
            news_list = fetcher.search_industry(queries)

            if not news_list:
                lines.append(f"- **{cat_name}**（{pos_pct:.1f}%）：暂无相关新闻")
            else:
                news_str = "\n".join([
                    f"  {i+1}. {n['title']}（{n['source']}）{n['snippet'][:100]}"
                    for i, n in enumerate(news_list[:3])
                ])
                lines.append(f"- **{cat_name}**（{pos_pct:.1f}%）：\n{news_str}")

        if not lines:
            return ""

        health_section = (
            "\n---\n"
            "## 📋 持仓体检分析（当前仓位>1%的行业）\n\n"
            "### 九、持仓行业现状与未来展望\n\n"
            "以下为各持仓行业近3日新闻，请结合新闻分析各行业现状，并给出未来展望：\n\n"
            + "\n".join(lines)
            + "\n\n**要求**：每个行业给出**一句话现状**（概括近期新闻反映的行业状态）和**一句话未来展望**（方向性判断），格式：行业名：现状|未来。"
        )
        return health_section
    except Exception as e:
        return f"\n\n_（持仓体检分析获取失败: {str(e)}）_"


def daily_financial_report(param=None):
    """当日财经新闻报告"""
    try:
        from financial_news import FinancialNewsFetcher
        from news_analyzer import LLMNewsAnalyzer
        cache_dir = ".cache"

        # 如果指定了日期，尝试读取对应缓存
        if param and len(param) == 8 and param.isdigit():
            date_str = param
            cache_path = os.path.join(cache_dir, f"analysis_report_{date_str}.txt")
            if os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as f:
                    report = f.read()
                return f"📰 **财经新闻报告 ({date_str})**\n\n{report}"
            else:
                return f"❌ 未找到 {date_str} 的缓存报告"

        # 默认生成当日报告
        news_fetcher = FinancialNewsFetcher()
        news_prompt = news_fetcher.run()

        # 追加持仓体检分析
        health_prompt = _build_position_health_prompt()

        # 追加风险预警区
        risk_prompt = news_fetcher.generate_risk_warning_prompt()

        full_prompt = news_prompt + health_prompt + risk_prompt
        news_fetcher.save_prompt(full_prompt)
        
        llm_analyzer = LLMNewsAnalyzer()
        report = llm_analyzer.analyze(full_prompt)
        return f"📰 **当日财经新闻报告**\n\n{report}"
    except Exception as e:
        return f"❌ 生成新闻报告失败: {str(e)}"


def trade_records_detail():
    """招商银行申购记录统计"""
    try:
        df = parse_cmb_trade_csv()

        trans_types = ["基金定期定额申购", "基金申购", "基金赎回"]
        df_filtered = df[df['交易类型'].isin(trans_types) & df['code'].notna()].copy()
        df_filtered['收入'] = pd.to_numeric(df_filtered['收入'], errors='coerce').fillna(0)
        df_filtered['支出'] = pd.to_numeric(df_filtered['支出'], errors='coerce').fillna(0)
        df_filtered['交易类型合并'] = df_filtered['交易类型'].apply(lambda x: '申购' if x in ['基金定期定额申购', '基金申购'] else '赎回')
        df_filtered['category'] = df_filtered['code'].apply(get_trade_category)
        df_filtered['交易日期_str'] = df_filtered['交易日期'].apply(lambda x: str(int(float(x))) if not pd.isna(x) else None)
        df_filtered = df_filtered[df_filtered['交易日期_str'].notna()].copy()
        all_dates = sorted(df_filtered['交易日期_str'].unique())
        categories = sorted(df_filtered['category'].unique())

        sysopen, summary_df = get_fund_positions_data()
        code_to_name = dict(zip(summary_df['产品代码'].astype(str), summary_df['简称']))

        result = "📋 **招商银行申购记录统计**\n\n"
        result += f"数据日期范围: {all_dates[-1]} ~ {all_dates[0]}\n\n"

        for trans_label, trans_key in [("申购", "申购"), ("赎回", "赎回")]:
            df_trans = df_filtered[df_filtered['交易类型合并'] == trans_key]
            if df_trans.empty:
                continue

            header_dates = [d[2:] if len(d) == 8 else d for d in all_dates]
            result += f"### {trans_label}\n\n"
            result += "| 分类 | " + " | ".join(header_dates) + " |\n"
            result += "|------|" + "|------|" * len(header_dates) + "\n"

            for cat in categories:
                df_cat = df_trans[df_trans['category'] == cat]
                if df_cat.empty:
                    continue

                if cat == "二级债基":
                    for code in sorted(df_cat['code'].unique()):
                        name = code_to_name.get(code, "未知")
                        name = name[:10] + "..." if len(name) > 10 else name
                        row_values = [f"{name} ({code})"]
                        for date in all_dates:
                            df_fund_date = df_cat[(df_cat['code'] == code) & (df_cat['交易日期_str'] == date)]
                            total = df_fund_date['支出'].sum() if trans_key == "申购" else df_fund_date['收入'].sum()
                            row_values.append(f"{total:.0f}" if total > 0 else "-")
                        result += "| " + " | ".join(row_values) + " |\n"
                else:
                    row_values = [cat]
                    for date in all_dates:
                        df_cat_date = df_cat[df_cat['交易日期_str'] == date]
                        total = df_cat_date['支出'].sum() if trans_key == "申购" else df_cat_date['收入'].sum()
                        row_values.append(f"{total:.0f}" if total > 0 else "-")
                    result += "| " + " | ".join(row_values) + " |\n"
            result += "\n"

        return result if categories else "❌ 无有效申购记录"
    except Exception as e:
        return f"❌ 读取申购记录失败: {str(e)}"


def dca_backtest(fund_code=None, start_date=None, end_date=None, amount_per_share=100, vol_coef=1.0):
    """定投回测函数

    Args:
        fund_code: 基金代码
        start_date: 开始日期 (YYYYMMDD或YYYY-MM-DD格式)
        end_date: 结束日期 (YYYYMMDD或YYYY-MM-DD格式)
        amount_per_share: 每份定投金额，默认100元
        vol_coef: 波动系数，默认1.0（用于放大/缩小偏离度阈值）

    规则：每5个交易日计算一次定投份额，新份额连续投5个交易日
    """
    try:
        fund_code = fund_code or "019547"
        df = get_fund_data(fund_code)
        df['净值日期'] = pd.to_datetime(df['净值日期'])
        df = df.sort_values('净值日期', ascending=True).reset_index(drop=True)

        # 解析日期参数
        def parse_date(d):
            if d is None:
                return None
            if isinstance(d, str):
                if len(d) == 8:
                    return pd.to_datetime(d, format='%Y%m%d')
                return pd.to_datetime(d)
            return pd.to_datetime(d)

        start_date = parse_date(start_date)
        end_date = parse_date(end_date)

        # 保留更多历史数据用于MA计算（MA60需要60个交易日历史）
        df_with_history = df.copy()
        if start_date:
            df = df[df['净值日期'] >= start_date]
        if end_date:
            df = df[df['净值日期'] <= end_date]
        df = df.reset_index(drop=True)

        if len(df) < 5:
            return f"❌ 数据不足（需要至少5个交易日）"

        # 获取基金分类和波动系数
        cat_name = get_trade_category(fund_code)
        if vol_coef == 1.0:
            vol_coef = category_config.get(cat_name, {}).get("vol_coef", 1.0)

        total_invested = 0.0
        total_shares = 0.0
        records = []

        # 每5个交易日为一个定投周期
        i = 0
        period_count = 0
        while i < len(df):
            period_count += 1
            window_end = min(i + 5, len(df))

            # 取窗口起始日的数据计算份额
            current_nav = df.iloc[i]['单位净值']
            current_date = df.iloc[i]['净值日期']

            # 计算MA偏离度（使用到i为止的历史数据，避免未来函数）
            ma10_dev = 0
            ma20_dev = 0
            ma60_dev = 0

            # 在完整历史数据中查找当前日期的位置，用来进行MA偏离度计算
            hist_pos = df_with_history[df_with_history['净值日期'] == current_date].index[0]

            if hist_pos >= 10:
                ma10_avg = df_with_history.iloc[hist_pos-9:hist_pos+1]['单位净值'].mean()
                ma10_dev = (current_nav - ma10_avg) / ma10_avg * 100

            if hist_pos >= 20:
                ma20_avg = df_with_history.iloc[hist_pos-19:hist_pos+1]['单位净值'].mean()
                ma20_dev = (current_nav - ma20_avg) / ma20_avg * 100

            if hist_pos >= 60:
                ma60_avg = df_with_history.iloc[hist_pos-59:hist_pos+1]['单位净值'].mean()
                ma60_dev = (current_nav - ma60_avg) / ma60_avg * 100

            # 计算距入场点偏离度（窗口一年）
            entry_date = start_date if start_date else df.iloc[0]['净值日期']
            df_asc_for_entry = df_with_history.sort_values('净值日期', ascending=True).reset_index(drop=True)
            since_entry_dev = calc_since_entry_dev(df_asc_for_entry, entry_date, current_date, current_nav)

            shares, ma10_c, ma20_c, ma60_c, since_c = calc_shares(
                ma10_dev, ma20_dev, ma60_dev, since_entry_dev, vol_coef
            )

            daily_investment = (shares + 1) * amount_per_share

            # 连续投入5个交易日
            for j in range(i, window_end):
                day_nav = df.iloc[j]['单位净值']
                day_shares = daily_investment / day_nav
                total_shares += day_shares
                total_invested += daily_investment
                records.append({
                    'date': df.iloc[j]['净值日期'].strftime('%Y-%m-%d'),
                    'nav': day_nav,
                    'period': period_count,
                    'shares': shares,
                    'ma10_c': ma10_c, 'ma20_c': ma20_c, 'ma60_c': ma60_c, 'since_c': since_c,
                    'ma10_dev': ma10_dev, 'ma20_dev': ma20_dev, 'ma60_dev': ma60_dev,
                    'since_entry_dev': since_entry_dev,
                    'investment': daily_investment,
                    'day_shares': day_shares,
                    'cumulative_shares': total_shares,
                    'cumulative_invested': total_invested
                })

            i += 5

        # 计算最终收益
        final_nav = df.iloc[-1]['单位净值']
        final_value = total_shares * final_nav
        profit = final_value - total_invested
        profit_rate = (profit / total_invested * 100) if total_invested > 0 else 0
        annual_days = 250
        days_span = (df.iloc[-1]['净值日期'] - df.iloc[0]['净值日期']).days
        annual_rate = (profit_rate * annual_days / days_span) if days_span > 0 else 0

        # 构建结果
        result = f"""📊 **定投回测结果**

**基金**: {fund_code} | **{cat_name}**
**时间范围**: {df.iloc[0]['净值日期'].strftime('%Y-%m-%d')} ~ {df.iloc[-1]['净值日期'].strftime('%Y-%m-%d')}
**交易日数**: {len(df)} 天 | **定投期数**: {period_count} 期
**每份金额**: {amount_per_share} 元 | **波动系数**: {vol_coef}

---

**📈 收益汇总**

| 指标 | 数值 |
|------|------|
| 总投入 | {total_invested:.2f} 元 |
| 总份额 | {total_shares:.4f} |
| 持仓净值 | {final_nav:.4f} |
| 持仓市值 | {final_value:.2f} 元 |
| 总收益 | {profit:.2f} 元 |
| 总收益率 | {profit_rate:+.2f}% |
| 年化收益率 | {annual_rate:+.2f}% |

---

**📋 每期明细（每5个交易日重新计算份额）**

| 期 | 开始日 | 起始净值 | 份额(ma10+ma20+ma60+since) | 距MA10 | 距MA20 | 距MA60 | 距入场(一年) | 日投×天 | 买入份 | 累计份 | 累计投入 |
|----|------|------|------|------|------|------|------|--------|--------|--------|----------|"""

        # 按期汇总，每期一行
        period_summary = {}
        for r in records:
            p = r['period']
            if p not in period_summary:
                period_summary[p] = {
                    'start_date': r['date'], 'start_nav': r['nav'],
                    'shares': r['shares'], 'ma10_c': r['ma10_c'], 'ma20_c': r['ma20_c'], 'ma60_c': r['ma60_c'], 'since_c': r['since_c'],
                    'ma10_dev': r['ma10_dev'], 'ma20_dev': r['ma20_dev'], 'ma60_dev': r['ma60_dev'],
                    'since_entry_dev': r['since_entry_dev'],
                    'daily_investment': r['investment'],
                    'day_count': 0, 'total_shares_bought': 0,
                    'end_cumulative_shares': r['cumulative_shares'], 'end_cumulative_invested': r['cumulative_invested']
                }
            period_summary[p]['day_count'] += 1
            period_summary[p]['total_shares_bought'] += r['day_shares']
            period_summary[p]['end_cumulative_shares'] = r['cumulative_shares']
            period_summary[p]['end_cumulative_invested'] = r['cumulative_invested']

        for p, s in period_summary.items():
            def dev_color(v):
                """偏离度数值对应的HTML颜色标签（无百分号）"""
                if v > 0:
                    return f'<span style="color: red; font-weight: bold;">+{v:.2f}</span>'
                elif v < -5:
                    return f'<span style="color: gold; font-weight: bold;">{v:.2f}</span>'
                elif v < -3:
                    return f'<span style="color: darkgoldenrod; font-weight: bold;">{v:.2f}</span>'
                elif v < 0:
                    return f'<span style="color: green; font-weight: bold;">{v:.2f}</span>'
                return f'<span style="color: gray;">{v:.2f}</span>'

            m10 = dev_color(s['ma10_dev']) if s['ma10_dev'] != 0 else "--"
            m20 = dev_color(s['ma20_dev']) if s['ma20_dev'] != 0 else "--"
            m60 = dev_color(s['ma60_dev']) if s['ma60_dev'] != 0 else "--"
            m_entry = dev_color(s['since_entry_dev']) if s['since_entry_dev'] != 0 else "--"
            shares_str = f'<span style="color: gold; font-weight: bold;">{s["shares"]:.1f}</span>={s["ma10_c"]:.1f}+{s["ma20_c"]:.1f}+{s["ma60_c"]:.1f}+{s["since_c"]:.1f}' if s['shares'] > 0 else f'{s["shares"]:.1f}={s["ma10_c"]:.1f}+{s["ma20_c"]:.1f}+{s["ma60_c"]:.1f}+{s["since_c"]:.1f}'
            result += f"\n| **{p}** | {s['start_date']} | {s['start_nav']:.4f} | {shares_str} | {m10} | {m20} | {m60} | {m_entry} | {s['daily_investment']:.0f}×{s['day_count']} | {s['total_shares_bought']:.4f} | {s['end_cumulative_shares']:.4f} | {s['end_cumulative_invested']:.2f} |"

        # 折叠：用<details>包裹整个表格（需在table之前打开）
        sep_line = "|----|------|------|------|------|------|------|------|--------|--------|--------|----------|"
        # 在表头行之前插入 <details><summary>，在分隔符行之后关闭open状态并插入 </details>
        result = result.replace(
            f"**📋 每期明细（每5个交易日重新计算份额）**\n\n| 期",
            f"**📋 每期明细（每5个交易日重新计算份额）**\n\n<details>\n<summary>点击展开</summary>\n\n| 期"
        )
        result = result.replace(
            f"{sep_line}\"\"\"",
            f"{sep_line}\"\n</details>"
        )

        return result

    except Exception as e:
        return f"❌ 回测失败: {str(e)}"


def func_6():
    return f"📋 **数据示例**\n\n1. 随机数: {', '.join(map(str, [random.randint(1, 100) for _ in range(5)]))}\n" \
           f"2. 时间戳: {int(datetime.now().timestamp())}\n" \
           f"3. 随机选择: {random.choice(['Python', 'Gradio', 'Pyecharts', 'xalpha'])}"


# 功能映射
FUNCTIONS_MAP = {
    "1": {"func": fund_pos_change_stat, "desc": "持仓基金加仓建议", "emoji": "📈", "has_param": False},
    "2": {"func": dca_backtest, "desc": "定投回测", "emoji": "📊", "has_param": True, "param_desc": "2 019547 20250101 20260331 100"},
    "3": {"func": daily_financial_report, "desc": "当日财经报告", "emoji": "🎲", "has_param": True, "param_desc": "3 20260403"},
    "4": {"func": fund_pos_detail, "desc": "持仓组合摘要", "emoji": "📊", "has_param": False},
    "5": {"func": trade_records_detail, "desc": "基金申购赎回明细", "emoji": "💻", "has_param": False},
    "6": {"func": func_6, "desc": "数据示例", "emoji": "📋", "has_param": False},
}


def build_charts(selected_types, fund_code="019547"):
    charts_map = {
        "持仓分布": create_fund_pos_ratio_chart,
        "申购记录": create_trade_records_charts,
        "股债利差": create_erp_chart,
        "基金详情": lambda: create_fund_trend_chart(fund_code)
    }
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

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("**图表类型**")
            chart_1 = gr.Checkbox(label="持仓分布", value=True)
            chart_2 = gr.Checkbox(label="申购记录", value=False)
            chart_3 = gr.Checkbox(label="股债利差", value=False)
            chart_4 = gr.Checkbox(label="基金详情", value=False)
            fund_code_input = gr.Textbox(label="基金代码", value="019547", lines=1)

            def combine_charts(c1, c2, c3, c4):
                selected = []
                if c1: selected.append("持仓分布")
                if c2: selected.append("申购记录")
                if c3: selected.append("股债利差")
                if c4: selected.append("基金详情")
                return selected

            generate_btn = gr.Button("🎨 生成图表", variant="primary")

            gr.Markdown("---")
            chat_input = gr.Textbox(label="💬 数字命令", placeholder="输入 1-6", lines=2)

            with gr.Row():
                chat_send = gr.Button("📨 发送", variant="primary", scale=1)
                clear_btn = gr.Button("🗑️ 清除", scale=1)

            function_list = "\n".join([f"- **{num}** {info['emoji']} {info['desc']}" + (f" ({info.get('param_desc', '')})" if info.get("has_param") else "") for num, info in FUNCTIONS_MAP.items()])
            gr.Markdown(function_list + "\n---")

        with gr.Column(scale=3):
            chart_output = gr.HTML(label="图表")

    with gr.Row():
        with gr.Column(scale=1):
            chatbot = gr.Chatbot(label="执行结果", height=600)
            chat_history = gr.State([])

    def generate_charts_with_detail(a, b, c, d, code, history):
        selected = combine_charts(a, b, c, d)
        chart_html = build_charts(selected, code)
        if d and code:
            detail = get_fund_detail(code)
            history = history + [{"role": "user", "content": f"📈 基金详情 ({code})"}, {"role": "assistant", "content": detail}]
        return chart_html, history, history

    generate_btn.click(
        fn=generate_charts_with_detail,
        inputs=[chart_1, chart_2, chart_3, chart_4, fund_code_input, chat_history],
        outputs=[chart_output, chatbot, chat_history]
    )

    def send_message(msg, history):
        if not msg or not msg.strip():
            return history, "", history, gr.update()

        msg = msg.strip()
        parts = msg.split()
        first_part = parts[0]
        new_fund_code = gr.update()
        fund_code = "019547"  # default

        if first_part.isdigit() and first_part in FUNCTIONS_MAP:
            info = FUNCTIONS_MAP[first_part]
            if info.get("has_param", False):
                # dca_backtest: 基金代码 开始日期 结束日期 每份金额(可选)
                if first_part == "2":
                    fund_code = parts[1] if len(parts) >= 2 else "019547"
                    start_date = parts[2] if len(parts) >= 3 else None
                    end_date = parts[3] if len(parts) >= 4 else None
                    amount_per_share = float(parts[4]) if len(parts) >= 5 and parts[4].replace('.','',1).isdigit() else 100
                    response = f"{info['emoji']} **{info['desc']} ({fund_code})**\n\n{info['func'](fund_code, start_date, end_date, amount_per_share)}"
                else:
                    fund_code = parts[1] if len(parts) >= 2 else "019547"
                    response = f"{info['emoji']} **{info['desc']} ({fund_code})**\n\n{info['func'](fund_code)}"
                if fund_code.isdigit() and len(fund_code) == 6:
                    new_fund_code = fund_code
            else:
                response = f"{info['emoji']} **{info['desc']}**\n\n{info['func']()}"
        else:
            response = f"❌ 无效输入\n\n**使用格式:**\n- 数字命令: 1-6\n\n**可用命令:**\n" + "\n".join([f"  {num} - {info['emoji']} {info['desc']}" + (f" ({info.get('param_desc', '')})" if info.get("has_param") else "") for num, info in FUNCTIONS_MAP.items()])

        history.append({"role": "user", "content": f"🔢 {msg}"})
        history.append({"role": "assistant", "content": response})
        return history, "", history, new_fund_code

    chat_send.click(send_message, [chat_input, chat_history], [chatbot, chat_input, chat_history, fund_code_input])
    chat_input.submit(send_message, [chat_input, chat_history], [chatbot, chat_input, chat_history, fund_code_input])
    clear_btn.click(lambda: ([], "", []), None, [chatbot, chat_input, chat_history])

    demo.load(fn=lambda: build_charts(["持仓分布"]), outputs=chart_output)


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, debug=True)