from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from pywen.config.manager import ConfigManager
from pywen.config.token_limits import TokenLimits
from pywen.llm.llm_basics import LLMMessage
from pywen.llm.llm_events import LLM_Events

from .prompt import (
    compression_prompt,
    first_downgrade_prompt,
    keyword_continuity_score_prompt,
    second_downgrade_prompt,
)


class MemoryMonitor:
    def __init__(self, config_mgr: ConfigManager):
        self.cfg_mgr = config_mgr
        mm = self.cfg_mgr.get_app_config().memory_monitor
        self.check_interval: int = (mm.check_interval if mm and mm.check_interval else 5)
        self.rules: List[Tuple[float, int]] = mm.rules if mm and mm.rules else [(0.92, 1), (0.80, 2), (0.60, 3), (0.0, 5)]
        self._last_checked_turn = 0

    async def run_monitored(self, llm_client, cli, history: List[LLMMessage], tokens_used: int, turn: int) -> Tuple[int, str]:
        """
        对当前对话的记忆使用情况进行监控，并在必要时执行压缩。
        参数:
            llm_client: LLM 客户端实例。
            history: 当前对话的消息历史列表。
            tokens_used: 当前对话使用的总 token 数。
            turn: 当前对话的轮次编号。
        返回:
            Tuple[int, str]: 返回压缩后使用的 token 数和压缩后的对话内容。
        """
        if (turn - self._last_checked_turn) % self.check_interval != 0:
            return 0, ""

        model_name = self.cfg_mgr.get_active_model_name() or ""
        agent_name = self.cfg_mgr.get_active_agent_name() or ""
        max_tokens = TokenLimits.get_limit(agent_name, model_name)
        ratio = 0.0 if max_tokens <= 0 else max(0.0, min(1.0, tokens_used / max_tokens))

        interval = next((interval for r, interval in self.rules if ratio >= r), self.rules[-1][1])
        self.check_interval = interval
        self._last_checked_turn = turn
        if ratio < 0.92:
            return 0, ""

        history_text = "\n".join(f"{m.role}: {m.content}" for m in history)
        prompt_text = compression_prompt.replace("<<HISTORY>>", history_text)

        cli.print("⏳ context compacting...", "yellow")
        _, summary_text = await self._llm_ask_user_prompt(llm_client, prompt_text)
        if not summary_text:
            return 0, self._fallback_compact_history(history)

        return await self._produce_valid_summary(
            llm_client, summary_text, history_text, tokens_used
        )

    async def _llm_ask_user_prompt(self, llm_client, prompt_text: str) -> Tuple[int, str]:
        """ 
        使用 LLM 客户端发送用户提示词并获取响应。
        参数: prompt_text - 用户提示词文本
        返回: 使用的 token 数以及模型回复文本
        """
        messages = [{"role": "user", "content": prompt_text}]
        model = self.cfg_mgr.get_active_model_name()
        buf: List[str] = []
        tokens_used: int = 0
        #TODO. 应该返回更详细的 usage 信息
        #usage = {"input": 0, "output": 0, "total": 0}
        try:
            async for event in llm_client.astream_response(messages=messages, api="chat", model=model):
                if event.type == LLM_Events.ASSISTANT_DELTA and event.data:
                    buf.append(str(event.data))
                elif event.type in (
                    LLM_Events.ERROR,
                    LLM_Events.RESPONSE_FINISHED,
                    LLM_Events.ASSISTANT_FINISHED,
                ):
                    break
                elif event.type == LLM_Events.TOKEN_USAGE and event.data:
                    tokens_used += int(event.data.get("input_tokens", 0)) + int(event.data.get("output_tokens", 0))
        except Exception:
            return 0, ""

        return tokens_used, "".join(buf).strip()

    async def _score_summary_quality(self, llm_client, summary_text: str, history_text: str, summary_tokens: int) -> Dict[str, Any]:
        """ 
        对模型生成的摘要文本（summary_text）进行综合质量评估 
            参数: summary_text - 模型生成的摘要文本
                  history_text - 原始对话历史文本
                  summary_tokens - 摘要所使用的 token 数
            返回: 包含质量评估结果的字典
        """
        required = [
            "Primary Request and Intent", "Key Technical Concepts", "Files and Code Sections", "Errors and fixes",
            "Problem Solving", "All user messages", "Pending Tasks", "Current Work",
        ]
        hit_keywords_num = sum(1 for s in required if re.search(rf"\b{re.escape(s)}\b", summary_text, re.I))
        section_ratio = hit_keywords_num / len(required)
        
        prompt_text = keyword_continuity_score_prompt.replace("<<SUMMARY>>",summary_text).replace("<<ORIGINAL>>", history_text)
        _, resp = await self._llm_ask_user_prompt(llm_client, prompt_text)
        
        if resp.startswith("Result"):
            try:
                _, tail = resp.split("Result", 1)
                nums = tail.replace(":", " ").split()
                keyword_ratio = float(nums[0])
                continuity_ratio = float(nums[1])
            except Exception:
                keyword_ratio, continuity_ratio = 0.0, 0.0
        else:
            keyword_ratio, continuity_ratio = 0.0, 0.0
        
        est_summary_tokens = max(1, len(summary_text) // 4) #TODO. 更改估算方法，需要llm返回，llm无法返回再估算
        ratio_score = (est_summary_tokens / summary_tokens) if summary_tokens > 0 else 1.0
        
        fidelity = int(
            section_ratio * 100 * 0.3
            + keyword_ratio * 100 * 0.4
            + continuity_ratio * 100 * 0.2
            + (100 if ratio_score <= 0.15 else 50) * 0.1
        )
        
        return {
            "valid": fidelity >= 80,
            "fidelity": fidelity,
            "section_ratio": section_ratio,
            "keyword_ratio": keyword_ratio,
            "continuity_ratio": continuity_ratio,
            "ratio_score": ratio_score,
        }

    async def _produce_valid_summary(self, llm_client, summary_text: str, original_text: str, tokens_used: int) -> Tuple[int, str]:
        """ 
        对模型生成的 summary 进行多轮质量评估，不达标则依次投入不同强度的提示词进行“降级修补”，
        以最大化得到一个可用的摘要。
        """
        # 第一次质量评估
        q = await self._score_summary_quality(llm_client, summary_text, original_text, tokens_used)
        if q["valid"]:
            return tokens_used, summary_text

        # 降级 1
        tokens_used, d1_text = await self._llm_ask_user_prompt(
            llm_client, first_downgrade_prompt.replace("<<SUMMARY>>",summary_text).replace("<<ORIGINAL>>", original_text)
        )
        if d1_text:
            q1 = await self._score_summary_quality(llm_client, d1_text, original_text, tokens_used)
            if q1["fidelity"] >= 75:
                return tokens_used, d1_text

        # 降级 2
        base = d1_text if d1_text else summary_text
        tokens_used, d2_text = await self._llm_ask_user_prompt(
            llm_client, second_downgrade_prompt.replace("<<SUMMARY>>",base).replace("<<ORIGINAL>>",original_text)
        )
        if d2_text:
            q2 = await self._score_summary_quality(llm_client, d2_text, original_text, tokens_used)
            if q2["fidelity"] >= 70:
                return tokens_used, d2_text

        return 0, ""

    def _fallback_compact_history(self, history: List[LLMMessage]) -> str:
        """ 兜底：返回最近 30%，并从最近的 user 起拼接。 """
        if not history:
            return ""

        total = len(history)
        keep = max(1, int(total * 0.3))
        candidates = history[-keep:]

        first_user_idx = next((i for i, m in enumerate(candidates) if m.role == "user"), None)
        if first_user_idx is None:
            start = None
            for i in range(total - keep - 1, -1, -1):
                if history[i].role == "user":
                    start = i
                    break
            retained = history[start:] if start is not None else history[-1:]
        else:
            retained = candidates[first_user_idx:]

        return "\n".join(
            f"{m.role}: {m.content}" for m in retained if getattr(m, "content", None)
        )
