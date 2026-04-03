import os
from datetime import datetime
from pathlib import Path

import anthropic


class LLMNewsAnalyzer:
    """LLM 财经新闻分析器"""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "MiniMax-M2.7",
        max_tokens: int = 4000,
        cache_dir: str = ".cache"
    ):
        self.client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        self.model = model
        self.max_tokens = max_tokens
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

    def _report_path(self) -> Path:
        """获取当日报告缓存路径"""
        return self.cache_dir / f"analysis_report_{datetime.now().strftime('%Y%m%d')}.txt"

    def get_cached_report(self) -> str | None:
        """获取当日缓存报告"""
        path = self._report_path()
        return path.read_text(encoding="utf-8") if path.exists() else None

    def save_report(self, content: str) -> None:
        """保存报告到缓存"""
        self._report_path().write_text(content, encoding="utf-8")

    def analyze(
        self,
        news_prompt: str,
        use_cache: bool = True,
        system: str = "你是一位专业的财经分析师，擅长从海量新闻中提取关键信息，进行市场分析。",
        stream: bool = False
    ) -> str:
        """
        发送新闻prompt到LLM获取分析结果

        参数:
            news_prompt: 新闻提示词
            use_cache: 是否使用当日缓存（默认True）
            system: 系统提示词
            stream: 是否流式输出

        返回:
            LLM生成的文本内容
        """
        if use_cache and (cached := self.get_cached_report()):
            print(f"✅ 找到今日缓存报告: {self._report_path()}")
            return cached

        with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": news_prompt}]
        ) as stream:
            response = stream.get_final_message()

        text_blocks = []
        for block in response.content:
            if block.type == "thinking":
                print(f"Thinking:\n{block.thinking}\n")
            elif block.type == "text":
                text_blocks.append(block.text)

        result = "\n".join(text_blocks)
        self.save_report(result)
        print(f"✅ 报告已保存到: {self._report_path()}")

        return result


# ============ 使用示例 ============
if __name__ == "__main__":
    from financial_news import FinancialNewsFetcher

    # 1. 获取新闻
    news_analyzer = FinancialNewsFetcher()
    news_prompt = news_analyzer.run()

    # 2. LLM 分析
    llm = LLMNewsAnalyzer()
    result = llm.analyze(news_prompt)

    print("\n" + "=" * 60)
    print("LLM 分析结果：")
    print("=" * 60)
    print(result)
