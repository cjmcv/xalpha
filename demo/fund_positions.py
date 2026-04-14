# -*- coding: utf-8 -*-
"""
扩展 record 模块以支持招行持仓CSV格式
"""

from pyecharts.charts import Bar, Line, Pie
from pyecharts import options as opts

import pandas as pd
import re
import numpy as np


class position_record:
    def __init__(self, path, **readkwds):
        self.account_total = 0  # 账户总资产（现金）
        
        if isinstance(path, str):
            with open(path, 'r', encoding='gbk') as f:
                lines = f.readlines()

            # ---------------------- 提取人民币现金 ----------------------
            for line in lines:
                if '人民币' in line:
                    for next_line in lines[lines.index(line):]:
                        if '￥' in next_line:
                            num_str = re.search(r'[\d,.]+', next_line).group()
                            num_str = num_str.replace(',', '')
                            try:
                                self.account_total = float(num_str)
                            except:
                                self.account_total = 0
                            break
                    break

            # ---------------------- 清洗数据：只保留有效基金行 ----------------------
            valid_lines = []
            header = "产品代码,简称,基金份额,交易币种,单位净值,单位成本,总成本,现金分红,参考市值,浮动盈亏,收益率,操作\n"
            
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                if line.startswith("产品代码"):
                    continue
                if stripped.startswith("以下是") or stripped.startswith("说明") or stripped.startswith("币种"):
                    continue
                if stripped[0].isdigit():
                    valid_lines.append(line)

            from io import StringIO
            data_str = header + ''.join(valid_lines)
            df = pd.read_csv(StringIO(data_str), encoding='gbk', **readkwds)
        else:
            df = path

        df.columns = df.columns.str.strip()
        df = df.dropna(subset=["基金份额", "总成本", "参考市值"])
        
        # 完全删除日期逻辑
        rows = []
        for _, row in df.iterrows():
            try:
                code_raw = str(row['产品代码']).strip()
                code = code_raw.zfill(6)
                shares = float(row['基金份额'])
                total_cost = float(row['总成本'])
                
                if shares > 0 and total_cost > 0:
                    rows.append({code: total_cost})
            except:
                continue
        
        if rows:
            status_df = pd.DataFrame(rows)
            status_df.fillna(0, inplace=True)
            self.status = status_df
        else:
            self.status = pd.DataFrame()
        
        self.positions = df


# ==================== 兼容 mulfix 的组合分析类 ====================
class mulfix_pos:
    def __init__(self, status):
        self.pos = status
        self.cash = int(round(status.account_total, 0)) if status.account_total > 0 else 0
        self.df = self._make_summary()

    def _make_summary(self):
        pos = self.pos.positions.copy()
        data = []
        total_mv = 0.0

        for _, row in pos.iterrows():
            try:
                code = str(row["产品代码"]).strip().zfill(6)
                name = row["简称"]
                share = float(row["基金份额"])
                netvalue = float(row["单位净值"])
                cost = float(row["总成本"])
                market_value = float(row["参考市值"])
                profit = float(row["浮动盈亏"])
                profit_rate = float(str(row["收益率"]).replace('%', '').strip())

                data.append({
                    "产品代码": code,
                    "简称": name,
                    "基金份额": share,
                    "单位净值": netvalue,
                    "总成本": cost,
                    "参考市值": market_value,
                    "浮动盈亏": profit,
                    "收益率": profit_rate,
                })
                total_mv += market_value
            except:
                continue

        df = pd.DataFrame(data)
        self.total_market_value = total_mv if not np.isnan(total_mv) else 0.0
        if self.total_market_value > 0:
            df["占比"] = df["参考市值"] / self.total_market_value * 100
        else:
            df["占比"] = 0.0
        
        return df

    def combsummary(self):
        return self.df

    def v_positions(self, category_config, rendered=True):
        df = self.df.copy()
        fund_total = int(round(self.total_market_value if not np.isnan(self.total_market_value) else 0, 0))
        cash = self.cash
        grand_total = cash + fund_total
        
        # ===================== 归类规则 =====================
        def classify(name):
            for category, config in category_config.items():
                for keyword in config["keywords"]:
                    if keyword in name:
                        return category
            return "其他"

        # 生成分类
        df["分类"] = df["简称"].apply(classify)
        # 根据配置获取目标占比和phase
        df["目标占比"] = df["分类"].apply(lambda x: category_config.get(x, {}).get("target_ratio", 0))
        df["phase"] = df["分类"].apply(lambda x: category_config.get(x, {}).get("phase", "WATCH"))

        # 分离ACC和非ACC
        df_acc = df[df["phase"] == "ACC"].copy()
        df_other = df[df["phase"] != "ACC"].copy()

        # 汇总ACC分类
        outer_df = df_acc.groupby("分类").agg({
            "参考市值": "sum",
            "目标占比": "first"
        }).reset_index()

        # 非ACC归入"其他"
        other_mv = df_other["参考市值"].sum()
        if other_mv > 0:
            outer_df.loc[len(outer_df)] = {"分类": "其他", "参考市值": other_mv, "目标占比": 0}

        # 加入现金
        if cash > 0:
            outer_df.loc[len(outer_df)] = {"分类": "现金", "参考市值": cash, "目标占比": category_config["现金"]["target_ratio"]}

        total_value = outer_df["参考市值"].sum()

        # 预先格式化外层标签
        outer_data_with_label = []
        outer_name_map = {}
        for _, row in outer_df.iterrows():
            short_name = row["分类"]
            value = int(round(row["参考市值"]))
            percent = (value / total_value * 100) if total_value > 0 else 0
            target = row["目标占比"]
            label = f"{short_name}: {percent:.1f}% ({target}%)"
            outer_data_with_label.append((label, value))
            outer_name_map[label] = short_name

        # 内层债券
        bond_df = df_acc[df_acc["分类"] == "二级债基"].copy()
        inner_data_with_label = []
        inner_name_map = {}
        for _, row in bond_df.iterrows():
            short_name = row["简称"]
            value = int(round(row["参考市值"]))
            percent = (value / total_value * 100) if total_value > 0 else 0
            label = f"{short_name}: {percent:.1f}%"
            inner_data_with_label.append((label, value))
            inner_name_map[label] = short_name

        # ===================== 绘图 =====================
        c = (
            Pie()
            .add(
                series_name="债券明细",
                data_pair=inner_data_with_label,
                radius=["0%", "35%"],
                label_opts=opts.LabelOpts(
                    position="inside",
                    formatter="{b}"
                ),
            )
            .add(
                series_name="持仓分类",
                data_pair=outer_data_with_label,
                radius=["40%", "75%"],
                label_opts=opts.LabelOpts(
                    position="outside",
                    formatter="{b}"
                ),
            )
            .set_global_opts(
                title_opts=opts.TitleOpts(
                    title=f"持仓总额({fund_total}) + 现金({cash}) = {grand_total}",
                    pos_left="center", 
                    title_textstyle_opts=opts.TextStyleOpts(color="gold")
                ),
                legend_opts=opts.LegendOpts(orient="vertical", pos_left="left"),
            )
            .set_series_opts(
                tooltip_opts=opts.TooltipOpts(
                    trigger="item",
                    formatter=lambda params: f"{outer_name_map.get(params.name, params.name.split(':')[0])}: {params.value}元"
                )
            )
        )

        return c.render_notebook() if rendered else c

# 便捷函数
def from_positions(path, **readkwds):
    return position_record(path, **readkwds)