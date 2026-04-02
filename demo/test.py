import akshare as ak
import pandas as pd
import sys

# ==========================================
# 基金新闻舆论获取工具（兼容最新 akshare）
# 功能：输入基金代码 → 获取全部相关新闻
# ==========================================

def get_fund_news(fund_code: str, max_count=30):
    df = ak.stock_news_em("603777") # 008929
    
    # df = ak.index_news_sentiment_scope() 
    # df = ak.macro_info_ws(date = "20260402")
    # df = ak.fund_overview_em("008929") # 基金档案-基本概况
    # df = ak.fund_announcement_report_em("008929")

    print(df)

def get_fund_announcement(fund_code: str):
    """获取基金公告（重要信息）"""
    try:
        df = ak.fund_announcement_em(symbol=fund_code)
        if df.empty:
            return ""

        ann_list = []
        for _, row in df.head(10).iterrows():
            title = row["标题"]
            date = row["日期"]
            ann_list.append(f"【公告 {date}】{title}")

        return "\n".join(ann_list)
    except:
        return ""


if __name__ == "__main__":
    print("=" * 60)
    print("       基金新闻舆论获取工具（akshare 修复版）")
    print("功能：输入基金代码 → 获取新闻 + 公告")
    print("=" * 60)

    code = "008929" # input("\n请输入基金代码：").strip()

    if not code:
        print("代码不能为空")
        sys.exit(1)

    # 获取新闻
    news = get_fund_news(code)
    # 获取公告
    ann = get_fund_announcement(code)

    print("\n" + "="*80)
    print("📰 基金新闻舆论信息")
    print("="*80 + "\n")

    print(news)

    if ann:
        print("\n【基金公告】")
        print(ann)

    print("\n✅ 获取完成！")