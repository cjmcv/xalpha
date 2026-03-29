# -*- coding: utf-8 -*-
"""
扩展 record 模块以支持持仓CSV格式 —— 已修复基金代码6位补0问题
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

    def v_positions(self, rendered=True):
        df = self.df.copy()
        fund_total = int(round(self.total_market_value if not np.isnan(self.total_market_value) else 0, 0))
        cash = self.cash

        # ===================== 归类规则 =====================
        def classify(name):
            if "纳斯达克100" in name:
                return "纳斯达克100"
            elif "标普500" in name:
                return "标普500"
            elif "恒生科技" in name:
                return "恒生科技"
            elif "港股通" in name:
                return "港股通信息技术"
            elif "A500" in name:
                return "中证A500"
            elif "消费红利" in name:
                return "主要消费红利"
            elif "黄金" in name or "上海金" in name:
                return "黄金"
            elif "债券" in name or "瑞锦混合" in name:
                return "债券"
            else:
                return "其他"

        df["分类"] = df["简称"].apply(classify)

        # ===================== 外层：所有分类 + 现金 =====================
        outer_df = df.groupby("分类")["参考市值"].sum().reset_index()
        outer_data = [(row["分类"], int(round(row["参考市值"], 0))) for _, row in outer_df.iterrows()]
        if cash > 0:
            outer_data.append(("现金", cash))

        # ===================== 内层：只显示债券明细 =====================
        bond_df = df[df["分类"] == "债券"].copy()
        inner_data = [(row["简称"], int(round(row["参考市值"], 0))) for _, row in bond_df.iterrows()]

        # ===================== 绘图 =====================
        c = (
            Pie()
            .add(
                series_name="债券明细",
                data_pair=inner_data,
                radius=["0%", "35%"],
                label_opts=opts.LabelOpts(formatter="{b}: {d}%"),
            )
            .add(
                series_name="持仓分类",
                data_pair=outer_data,
                radius=["40%", "75%"],
                label_opts=opts.LabelOpts(formatter="{b}: {c}元 ({d}%)"),
            )
            .set_global_opts(
                title_opts=opts.TitleOpts(
                    title=f"持仓总额({fund_total}) + 现金({cash}) = {cash + fund_total}",
                    pos_left="center"
                ),
                legend_opts=opts.LegendOpts(orient="vertical", pos_left="left"),
            )
        )

        if rendered:
            return c.render_notebook()
        return c


# 便捷函数
def from_positions(path, **readkwds):
    return position_record(path, **readkwds)