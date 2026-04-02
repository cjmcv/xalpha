import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from tavily import TavilyClient
from serpapi import GoogleSearch


class FinancialNewsFetcher:
    """双引擎财经新闻分析器"""

    CATEGORIES = {
        "美股市场": ["美股", "纳斯达克", "标普", "道指", "美联储", "美国经济", "华尔街"],
        "A股市场": ["A股", "上证", "深证", "创业板", "科创板", "北向资金", "主力"],
        "港股中概": ["港股", "恒生", "中概股", "H股", "香港股市"],
        "政策动态": ["政策", "证监会", "央行", "国务院", "发改委", "财政部", "监管", "降准", "降息"],
        "行业板块": ["新能源", "AI", "人工智能", "半导体", "芯片", "医药", "消费", "汽车", "房地产", "科技股"],
        "宏观经济": ["宏观", "GDP", "CPI", "PMI", "经济数据", "汇率", "利率", "通胀", "就业"],
        "公司要闻": ["财报", "盈利", "业绩", "营收", "收购", "合并", "发布", "CEO"]
    }

    def __init__(
        self,
        serpapi_key: Optional[str] = None,
        tavily_key: Optional[str] = None,
        cache_dir: str = ".cache"
    ):
        self.serpapi_key = serpapi_key or os.getenv("SERPAPI_API_KEY")
        self.tavily_key = tavily_key or os.getenv("TAVILY_API_KEY")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self._tavily_client = None

    @property
    def tavily(self) -> TavilyClient:
        if self._tavily_client is None:
            self._tavily_client = TavilyClient(api_key=self.tavily_key)
        return self._tavily_client

    def _cache_path(self, prefix: str = "news_prompt") -> Path:
        return self.cache_dir / f"{prefix}_{datetime.now().strftime('%Y%m%d')}.txt"

    def get_cached_prompt(self) -> Optional[str]:
        """获取当日缓存的prompt，存在则返回内容，否则返回None"""
        path = self._cache_path()
        return path.read_text(encoding="utf-8") if path.exists() else None

    def save_prompt(self, prompt: str, prefix: str = "news_prompt") -> None:
        """保存prompt到当日缓存文件"""
        self._cache_path(prefix).write_text(prompt, encoding="utf-8")

    def _classify(self, text: str) -> str:
        """文本分类"""
        text_lower = text.lower()
        best, max_cnt = "其他", 0
        for cat, kws in self.CATEGORIES.items():
            cnt = sum(1 for kw in kws if kw.lower() in text_lower)
            if cnt > max_cnt:
                max_cnt, best = cnt, cat
        return best

    def fetch_tavily(self, days: int = 1, max_results: int = 10) -> list[dict]:
        """获取Tavily国际财经新闻"""
        try:
            resp = self.tavily.search(
                query="Latest US stock market news, Fed policy, tech stocks, hot sectors, earnings",
                topic="news", days=days, search_depth="basic",
                max_results=max_results, include_raw_content=False, include_answer=True
            )
            return [{
                "title": r["title"],
                "snippet": r["content"],
                "source": r.get("source", "未知"),
                "date": r.get("published_at", "未知"),
                "link": r.get("url", ""),
                "engine": "Tavily"
            } for r in resp.get("results", [])]
        except Exception as e:
            print(f"Tavily 获取失败: {e}")
            return []

    def fetch_chinese(self, num: int = 20) -> list[dict]:
        """获取SerpAPI中文财经新闻"""
        try:
            params = {"q": "财经新闻 今日热点 A股 政策", "api_key": self.serpapi_key,
                      "hl": "zh-CN", "gl": "cn", "num": num}
            results = GoogleSearch(params).get_dict().get("organic_results", [])
            if len(results) < 5:
                params["q"] = "A股 今日行情 财经要闻 政策解读"
                results = GoogleSearch(params).get_dict().get("organic_results", [])
            return [{
                "title": r.get("title", ""),
                "snippet": r.get("snippet", ""),
                "source": r.get("source", "未知"),
                "date": r.get("date", datetime.now().strftime("%Y-%m-%d")),
                "link": r.get("link", ""),
                "engine": "SerpAPI"
            } for r in results]
        except Exception as e:
            print(f"SerpAPI 获取失败: {e}")
            return []

    def fetch_all(self, tavily_days: int = 1, tavily_max: int = 10, serpapi_num: int = 20) -> dict:
        """获取并合并所有新闻，自动分类去重"""
        international = self.fetch_tavily(tavily_days, tavily_max)
        domestic = self.fetch_chinese(serpapi_num)

        for n in international:
            n["category"] = self._classify(f"{n['title']} {n['snippet']}")
        for n in domestic:
            n["category"] = self._classify(f"{n['title']} {n['snippet']}")

        seen, combined = set(), []
        for news in international + domestic:
            key = news["title"][:50]
            if key not in seen:
                seen.add(key)
                combined.append(news)

        return {"international": international, "domestic": domestic, "combined": combined}

    def generate_prompt(self, data: dict) -> str:
        """生成分析提示词"""
        categorized = {cat: [] for cat in self.CATEGORIES}
        categorized["其他"] = []
        for news in data["combined"]:
            categorized[news.get("category", "其他")].append(news)

        parts = [
            f"**报告生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            "## 📊 新闻来源统计\n| 来源 | 数量 |\n|------|------|\n",
            f"| 国际财经 (Tavily) | {len(data['international'])} 条 |\n",
            f"| 国内财经 (SerpAPI) | {len(data['domestic'])} 条 |\n",
            f"| **合计** | **{len(data['combined'])} 条** |\n---\n## 📰 分类新闻汇总\n"
        ]

        for cat, items in categorized.items():
            if not items:
                continue
            parts.append(f"\n### 【{cat}】（{len(items)}条）\n")
            for i, item in enumerate(items[:5], 1):
                parts.append(f"**{i}. {item['title']}**\n"
                             f"- 来源：{item['source']} ({item['engine']})\n"
                             f"- 时间：{item['date']}\n"
                             f"- 摘要：{item['snippet'][:200]}\n")
                if item.get("link"):
                    parts.append(f"- 链接：{item['link']}\n")

        parts.append("""
---
## 📋 分析报告框架
请按以下结构输出分析报告：
### 一、全球市场概览
### 二、核心事件解读（3-5件）
### 三、政策动态追踪
### 四、行业热点分析
### 五、重点关注公司
### 六、宏观环境判断
### 七、风险因素提醒
### 八、投资策略建议
---
**要求**：专业客观，避免预测具体点位，侧重趋势和逻辑分析，区分短期波动和长期趋势
""")
        return "".join(parts)

    def run(self, use_cache: bool = True) -> str:
        """
        执行完整流程

        参数:
            use_cache: 是否使用当日缓存（默认True）
        返回:
            生成的prompt内容
        """
        if use_cache and (cached := self.get_cached_prompt()):
            print("✅ 找到今日缓存新闻，直接返回")
            print(f"缓存文件: {self._cache_path()}")
            return cached

        if not self.serpapi_key or not self.tavily_key:
            raise ValueError("请设置 SERPAPI_API_KEY 和 TAVILY_API_KEY")

        print("🔍 正在获取财经新闻...")
        all_news = self.fetch_all()
        prompt = self.generate_prompt(all_news)

        self.save_prompt(prompt)
        # Path("dual_engine_raw.json").write_text(
        #     json.dumps(all_news, ensure_ascii=False, indent=2), encoding="utf-8"
        # )

        print(f"📊 获取统计: Tavily {len(all_news['international'])} 条, "
              f"SerpAPI {len(all_news['domestic'])} 条, "
              f"去重后 {len(all_news['combined'])} 条")
        cats = {}
        for n in all_news["combined"]:
            cats[n.get("category", "其他")] = cats.get(n.get("category", "其他"), 0) + 1
        for cat, cnt in sorted(cats.items(), key=lambda x: -x[1]):
            print(f"   {cat}: {cnt}条")
        print(f"\n✅ 已保存到 {self._cache_path()}")

        return prompt


# ============ 使用示例 ============
if __name__ == "__main__":
    analyzer = FinancialNewsFetcher()
    prompt = analyzer.run()
    print("\n提示词预览（前800字符）：")
    print(prompt[:800])
