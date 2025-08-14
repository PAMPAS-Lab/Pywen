from __future__ import annotations
import re
import os
from openai import AsyncOpenAI
from .prompt import compression_prompt, keyword_continuity_score_prompt
from dataclasses import dataclass
from pywen.utils.llm_basics import LLMMessage
from typing import Dict, Any
from rich import print


@dataclass
class AdaptiveThreshold:

    check_interval: int = 3
    max_tokens: int = 7200
    rules: tuple[tuple[float, int], ...] = (
        (0.92, 1),
        (0.80, 1),   # ≥80 % 每 1 轮
        (0.60, 2),   # ≥60 % 每 2 轮
        (0.00, 3),   # 默认每 3 轮
    )


class MemoryMonitor:

    def __init__(self, threshold: AdaptiveThreshold | None = None):
        self.threshold = threshold
        self.model = "Qwen/Qwen3-235B-A22B-Instruct-2507"


    async def call_llm(self, prompt) -> str:
        client = AsyncOpenAI(
            api_key=os.environ["MODELSCOPE_API_KEY"],
            base_url="https://api-inference.modelscope.cn/v1/"
        )
        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                top_p=0.7,
                temperature=0
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"[bold red]Error calling LLM for memory compression: {e}[/]")


    async def run_monitored(self, iteration_counter, conversation_history):
        print(f"[bold magenta]Monitoring[/] on iteration [underline cyan]{iteration_counter}[/] :rocket:")
        if iteration_counter % self.threshold.check_interval == 0:
            alert = self.maybe_compress(conversation_history)
        else:
            return None
        if alert is not None and alert["level"] == "compress":
            print(alert["suggestion"])
            summary, original = await self.do_compress(conversation_history)
            quality = await self.quality_validation(summary, original)
            if quality["valid"]:
                print("[bold green]🚀 Memory compression success![/]")
                conversation_summary = [LLMMessage(role="user", content=summary)]
                return conversation_summary
            else:
                print("[bold green]⚠️ Memory compression fail, downgrade strategy will be executed.![/]")
                truncated_conversation = conversation_history[-10:]
                return truncated_conversation
        elif alert is not None and alert["level"] != "compress":
            print(alert["suggestion"])
        else:
            return None


    def maybe_compress(self, conversation_history) -> Dict[str, Any] | None:
        token_usage = self.count_tokens(conversation_history)
        ratio = token_usage / self.threshold.max_tokens
        print(f"Token usage: [bold cyan]{token_usage}[/], ratio: [bold magenta]{ratio:.2%}[/]")
        if ratio >= 0.92:
            return self.warning("compress", ratio)
        elif ratio >= 0.80:
            return self.warning("high", ratio)
        elif ratio >= 0.60:
            return self.warning("moderate", ratio)
        else:
            return None


    def count_tokens(self, messages: list[LLMMessage]) -> int:  # 不太准确
        if not messages:
            return 0
        for message in reversed(messages):
            if message.role == "assistant" and not message.tool_calls:
                return message.usage["total_tokens"]


    def pick_interval(self, ratio: float) -> int:
        for r, interval in self.threshold.rules:
            if ratio >= r:
                return interval


    def warning(self, level: str, ratio: float) -> Dict[str, Any]:
        check_interval = self.pick_interval(ratio)
        match ratio:
            case r if r >= 0.92:
                suggestion = f"[bold red]Memory usage {r*100:.0f}% – threshold reached! [/][red]Executing compression![/]"
            case r if r >= 0.80:
                suggestion = f"[orange1]Memory usage {r*100:.0f}% – high, checking every {check_interval} turn(s).[/] [yellow]You can restart a new conversation![/]"
            case r if r >= 0.60:
                suggestion = f"[bright_green]Memory usage {r*100:.0f}% – moderate, checking every {check_interval} turn(s).[/]"
            case _:
                suggestion = f"[dim bright_blue]Memory usage {r*100:.0f}% – low, checking every {check_interval} turn(s).[/]"
        return {
            "level": level,
            "suggestion": suggestion,
        }


    async def do_compress(self, conversation_history: list[LLMMessage]) -> tuple[str, str]:
        original = "\n".join(f"{message.role}: {message.content}" for message in conversation_history)
        prompt = compression_prompt.format(original)
        response = await self.call_llm(prompt)
        summary = response.strip()
        return summary, original
        

    def ratio_score(self, summary: str, original: str) -> float:
        return len(summary) / len(original)


    def section_score(self, summary: str) -> float:
        required = [
            "Primary Request and Intent",
            "Key Technical Concepts",
            "Files and Code Sections",
            "Errors and fixes",
            "Problem Solving",
            "All user messages",
            "Pending Tasks",
            "Current Work",
        ]
        found = [s for s in required if re.search(rf"\b{re.escape(s)}\b", summary, re.I)]
        return len(found) / len(required)


    async def keyword_continuity_score(self, summary: str, original: str):
        prompt = keyword_continuity_score_prompt.format(summary, original)
        response = await self.call_llm(prompt)
        response = response.strip()
        if not response.startswith("Result:"):
            raise ValueError("Missing 'Result:' prefix")
        _, scores = response.split("Result:", 1)
        parts = scores.strip().split()
        if len(parts) != 2:
            raise ValueError("Malformed score line")
        return float(parts[0]), float(parts[1]) 

    
    async def quality_validation(self, summary: str, original: str) -> Dict[str, Any]:
        ratio_score = self.ratio_score(summary, original)
        section_ratio = self.section_score(summary)
        keyword_ratio, continuity_ratio = await self.keyword_continuity_score(summary, original)
        fidelity = int(
            section_ratio * 100 * 0.3 +
            keyword_ratio * 100 * 0.4 +
            continuity_ratio * 100 * 0.2 +
            (100 if ratio_score <= 0.15 else 50) * 0.1
        )
        is_valid = fidelity >= 80
        suggestions = []
        if section_ratio < 0.875:
            suggestions.append(f"[red]⚠️  {section_ratio:.2%}[/red] Missing required sections; please include all 8.")
        if keyword_ratio < 0.8:
            suggestions.append(f"[orange1]⚠️  {keyword_ratio:.2%}[/orange1] Key information loss detected; compress less aggressively.")
        if ratio_score > 0.15:
            suggestions.append(f"[bright_magenta]⚠️  {ratio_score:.2%}[/bright_magenta] Compression ratio too low; consider deeper summarization.")
        if continuity_ratio < 0.6:
            suggestions.append(f"[yellow]⚠️  {continuity_ratio:.2%}[/yellow] Context flow broken; add transition phrases.")
        return {
            "valid": is_valid,
            "suggestions": suggestions,
        }

    
    def file_recover(self):
        pass

        



        


