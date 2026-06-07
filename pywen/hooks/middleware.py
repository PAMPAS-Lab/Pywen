from typing import Any, Tuple


class Middleware:
    async def before_prompt_submit(self, prompt: str) -> Tuple[bool, str | None, dict]:
        return True, None, {}
    async def on_event(self, event: dict, agent: Any) -> bool | None:
        return None
    async def on_tool_result(self, event: dict, agent: Any) -> None:
        ...
    async def on_turn_stop(self, result: str, event: dict, agent: Any, user_input: str) -> None:
        ...

class MiddlewareChain:
    def __init__(self, middlewares: list[Middleware]) -> None:
        self._mws = middlewares

    async def before_prompt_submit(self, prompt: str):
        merged = {}
        for mw in self._mws:
            if hasattr(mw, "before_prompt_submit"):
                ok, msg, extra = await mw.before_prompt_submit(prompt)
                if extra:
                    merged.update(extra)
                if not ok:
                    return ok, msg, merged
        return True, None, merged

    async def on_event(self, event: dict, agent: Any) -> bool:
        for mw in self._mws:
            if hasattr(mw, "on_event"):
                cont = await mw.on_event(event, agent)
                if cont is False:
                    return False
        return True

    async def on_tool_result(self, event: dict, agent: Any) -> None:
        for mw in self._mws:
            if hasattr(mw, "on_tool_result"):
                await mw.on_tool_result(event, agent)

    async def on_turn_stop(self, result: str, event: dict, agent: Any, user_input: str) -> None:
        for mw in self._mws:
            if hasattr(mw, "on_turn_stop"):
                await mw.on_turn_stop(result, event, agent, user_input)
