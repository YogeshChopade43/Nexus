from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, List, Optional

from app.core.exceptions import AppNotConnectedError
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5
MAX_TOOL_RESULT_CHARS = 8000


class Agent(ABC):
    @abstractmethod
    async def run(
        self,
        task: str,
        context: dict[str, Any] = None,
        available_tools: list[str] = None,
        llm_provider: Any = None,
        history: list[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        pass


DECLINED = "The user declined this action, so it was not done. Do not retry it; tell the user it was not done."


class BaseAgent(Agent):
    def __init__(
        self,
        tool_registry: ToolRegistry,
        app_connections: dict[str, bool] = None,
        on_event: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None,
    ):
        self._tool_registry = tool_registry
        self._app_connections = app_connections or {}
        self._on_event = on_event  # live progress for streaming: tool_call, tool_result, delta, approval_needed

    async def _emit(self, event: dict[str, Any]) -> None:
        if self._on_event:
            await self._on_event(event)

    def _policy(self, tool_name: str) -> str:
        try:
            return getattr(self._tool_registry.get_tool(tool_name), "policy", "allow")
        except Exception:
            return "allow"

    def _is_app_connected(self, app_id: str) -> bool:
        return self._app_connections.get(app_id, False)

    @staticmethod
    def _summarize_tool_result(tool_name: str, data: dict[str, Any]) -> str:
        text = " ".join(str(data.get("text") or "").split())
        return f"{tool_name}: {text[:200]}" if text else f"Executed {tool_name}"

    def _build_tool_schemas(self, tool_names: List[str]) -> List[dict[str, Any]]:
        schemas: List[dict[str, Any]] = []
        for name in tool_names:
            try:
                tool = self._tool_registry.get_tool(name)
            except Exception:
                continue
            if not tool.enabled:
                continue
            if not self._is_app_connected(tool.app_id):
                continue
            schema = tool.get_schema()
            schemas.append(schema)
        return schemas

    def _supports_llm_tool_calling(self, llm_provider: Any) -> bool:
        return hasattr(llm_provider, "chat_with_tools") and callable(getattr(llm_provider, "chat_with_tools"))

    async def _resolve_tools_via_llm(
        self,
        task: str,
        llm_provider: Any,
        tool_schemas: List[dict[str, Any]],
        events: list[dict[str, Any]],
        history: list[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        system_msg = (
            "# Nexus Agent — Tool Use Protocol\n\n"
            "You are Nexus, an AI assistant with access to external tools. Your primary role is to help users "
            "by executing actions via these tools when needed.\n\n"
            "## MANDATORY RULES\n\n"
            "### 1. TOOL USE IS NOT DEFAULT\n"
            "Most user messages do NOT require tools. Default to conversational response unless the request "
            "explicitly or implicitly requires external data/actions.\n\n"
            "### 2. USE TOOLS ONLY WHEN:\n"
            "The user asks for something that CANNOT be answered from your training knowledge and requires:\n"
            "- **Fetching live data** from external systems\n"
            "- **Performing actions** on external systems\n"
            "- **Real-time information** not in your training cutoff\n\n"
            "### 3. DO NOT USE TOOLS FOR:\n"
            "- Greetings, small talk, introductions\n"
            "- Questions about your identity, capabilities, or training\n"
            "- General knowledge questions (coding concepts, tech explanations, etc.)\n"
            "- Opinions, advice, brainstorming, creative writing\n"
            "- Follow-up questions about previous tool results (use the context provided)\n"
            "- \"What can you do?\" or \"How do you work?\" questions\n\n"
            "### 4. CONNECTED SERVERS & USER IDENTITY\n"
            "Tools come from MCP servers the user has connected, each already authenticated as the user. "
            "DO NOT ask for credentials. Tool names are prefixed with their server (server__tool).\n\n"
            "### 5. AMBIGUOUS REQUESTS\n"
            "If a request could be interpreted either way, ASK FOR CLARIFICATION instead of guessing. "
            "If no available tool fits, say which kind of MCP server would be needed.\n\n"
            "### 6. TOOL CALL FORMAT\n"
            "When tools ARE required:\n"
            "- Call ONLY the necessary tool(s)\n"
            "- Provide all required parameters\n"
            "- Do not include explanatory text outside tool calls\n"
            "- Multiple independent calls allowed in one response\n\n"
            "### 6. AFTER TOOL EXECUTION\n"
            "You will receive tool results. Summarize them naturally in your response. "
            "Do not dump raw JSON. Answer the user's original question using the tool data.\n\n"
            "## AVAILABLE TOOLS\n"
            "Tools are provided by the connected MCP servers. Only call tools that appear in the "
            "available tools list.\n\n"
            "Respond with tool calls only when the above criteria are met. Otherwise, respond conversationally."
        )

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_msg}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": task})
        state = {"task": task, "history": history or [], "messages": messages, "summaries": [], "queue": [],
                 "iteration": 0, "events": events}
        return await self._tool_loop(state, llm_provider, tool_schemas)

    async def resume(self, state: dict[str, Any], approved: bool, llm_provider: Any, tool_schemas: List[dict[str, Any]]) -> dict[str, Any]:
        """Continue a run that paused for approval of ``state['queue'][0]``."""
        return await self._tool_loop(state, llm_provider, tool_schemas, approval=approved)

    async def _tool_loop(
        self, state: dict[str, Any], llm_provider: Any, tool_schemas: List[dict[str, Any]], approval: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Call tools until the model answers. Pauses (returns needs_approval) before any tool whose policy is 'ask'.

        ``state`` is plain JSON so a paused run can be stored with the chat session and resumed later.
        """
        messages, summaries, events = state["messages"], state["summaries"], state["events"]
        content = ""
        while True:
            while state["queue"]:
                call = state["queue"][0]
                needs_ok = self._policy(call["name"]) == "ask"
                if needs_ok and approval is None:
                    action = {"tool": call["name"], "arguments": call["arguments"]}
                    await self._emit({"type": "approval_needed", **action})
                    return {
                        "status": "needs_approval", "events": events, "pending": state, "pending_action": action,
                        "summary": f"Waiting for approval to run {call['name']}",
                        "message": f"Nexus wants to run {call['name']}. Approve or deny it to continue.",
                        "response": f"Nexus wants to run {call['name']}. Approve or deny it to continue.",
                    }
                state["queue"].pop(0)
                if needs_ok and approval is False:
                    events.append({"type": "tool_declined", "tool_name": call["name"], "arguments": call["arguments"]})
                    await self._emit({"type": "tool_result", "tool": call["name"], "ok": False, "summary": "Declined by you"})
                    output = DECLINED
                else:
                    await self._emit({"type": "tool_call", "tool": call["name"], "arguments": call["arguments"]})
                    output = await self._execute_tool_call(call["name"], call["arguments"], events, summaries)
                    ok = events[-1]["type"] == "tool_executed"
                    await self._emit({"type": "tool_result", "tool": call["name"], "ok": ok,
                                      "summary": events[-1].get("summary") or events[-1].get("error", "")})
                if needs_ok:
                    approval = None  # an approval covers exactly one call
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})

            if state["iteration"] >= MAX_TOOL_ITERATIONS:
                content = ""
                break
            state["iteration"] += 1
            result = await llm_provider.chat_with_tools(messages=messages, tools=tool_schemas)
            content = result.get("content") or ""
            tool_calls = result.get("tool_calls") or []
            if not tool_calls:
                break

            calls = []
            for index, tool_call in enumerate(tool_calls):
                arguments = tool_call.get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments) if arguments.strip() else {}
                    except (json.JSONDecodeError, TypeError):
                        arguments = {}
                calls.append({
                    "id": tool_call.get("id") or f"call_{state['iteration']}_{index}",
                    "name": tool_call.get("name", ""),
                    "arguments": arguments if isinstance(arguments, dict) else {},
                })
            # One assistant turn carries every tool call, followed by one result per call:
            # the shape both OpenAI-style and Anthropic APIs require.
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                    for c in calls
                ],
            })
            state["queue"] = calls
            content = ""

        if content:
            await self._emit({"type": "delta", "text": content})
            final_content = content
        else:
            final_content = await self._generate_llm_response(
                state["task"], llm_provider, " ".join(summaries), events, state["history"],
                tool_results=[m["content"] for m in messages if m.get("role") == "tool"],
            )
        final_content = final_content or "Completed without a text response."
        return {
            "status": "completed",
            "events": events,
            "summary": f"Agent completed task: {state['task']}. {len(summaries)} tool(s) executed.",
            "message": final_content,
            "response": final_content,
        }

    async def _execute_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        events: list[dict[str, Any]],
        summaries: List[str],
    ) -> str:
        """Run one tool call, record the event, and return the text the LLM sees."""
        try:
            tool = self._tool_registry.get_tool(tool_name)
            if not self._is_app_connected(tool.app_id):
                raise AppNotConnectedError(f"{tool.app_id} is not connected")
            exec_result = await self._tool_registry.execute_tool(tool_name, arguments)
        except AppNotConnectedError:
            events.append({"type": "tool_error", "tool_name": tool_name, "error": "App not connected to Nexus"})
            return "Error: the app for this tool is not connected to Nexus."
        except Exception as exc:
            logger.warning("Tool error in LLM path: %s: %s", tool_name, exc)
            events.append({"type": "tool_error", "tool_name": tool_name, "error": str(exc)})
            return f"Error: {exc}"

        data = exec_result.get("data", {})
        try:
            tool_summary = self._summarize_tool_result(tool_name, data)
        except Exception:
            tool_summary = f"Executed {tool_name}"
        events.append({
            "type": "tool_executed",
            "tool_name": tool_name,
            "arguments": arguments,
            "event": exec_result["event"],
            "data": data,
            "summary": tool_summary,
            "app_id": tool.app_id,
        })
        summaries.append(tool_summary)
        # The model needs the actual data to answer follow-ups, not just the one-line summary.
        payload = json.dumps(data, default=str)
        if len(payload) > MAX_TOOL_RESULT_CHARS:
            payload = payload[:MAX_TOOL_RESULT_CHARS] + "... [truncated]"
        return f"{tool_summary}\n\nData: {payload}"

    async def run(
        self,
        task: str,
        context: dict[str, Any] = None,
        available_tools: list[str] = None,
        llm_provider: Any = None,
        history: list[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        ctx = context or {}
        if history is None:
            history = clean_history(ctx.get("previousMessages", []))
        requested_tools = available_tools or self._tool_registry.list_tool_names()
        tool_schemas = self._build_tool_schemas(requested_tools)

        if not llm_provider:
            message = "No LLM provider configured. Add one in Settings > AI."
            return {
                "status": "no_match",
                "events": events,
                "summary": f"No LLM provider: {task}",
                "message": message,
                "response": message,
            }

        if tool_schemas and self._supports_llm_tool_calling(llm_provider):
            try:
                return await self._resolve_tools_via_llm(task, llm_provider, tool_schemas, events, history)
            except NotImplementedError:
                pass
            except Exception as exc:
                logger.warning("LLM tool calling failed: %s", exc)
                events.append({"type": "llm_error", "task": task, "error": str(exc)})

        if not tool_schemas:
            events.append({"type": "intent_no_match", "task": task, "reason": "No tools available for this request"})
        response = await self._generate_llm_response(task, llm_provider, "", events, history)
        failed = any(event["type"] == "llm_error" for event in events)
        return {
            "status": "error" if failed else "completed",
            "events": events,
            "summary": f"Responded to: {task}",
            "message": response,
            "response": response,
        }

    async def _generate_llm_response(
        self,
        task: str,
        llm_provider: Any,
        context_summary: str,
        events: list[dict[str, Any]],
        history: list[dict[str, Any]] = None,
        tool_results: Optional[list[str]] = None,
    ) -> str:
        if not llm_provider:
            return context_summary
        system_msg = (
            "You are Nexus, a helpful AI assistant that connects natural-language requests "
            "to tools provided by the user's MCP servers. Be concise and helpful."
        )
        if context_summary:
            system_msg += f"\n\nResults from tools run for this request: {context_summary}"
        if tool_results:
            system_msg += "\n\nTool outputs:\n" + "\n---\n".join(tool_results)[:MAX_TOOL_RESULT_CHARS]
        messages = [{"role": "system", "content": system_msg}, *(history or []), {"role": "user", "content": task}]
        try:
            if self._on_event and hasattr(llm_provider, "chat_stream"):
                parts: list[str] = []
                async for chunk in llm_provider.chat_stream(messages=messages):
                    parts.append(chunk)
                    await self._emit({"type": "delta", "text": chunk})
                return "".join(parts) or context_summary or "The language model returned an empty response."
            result = await llm_provider.chat(messages=messages)
            return result.get("content") or context_summary or "The language model returned an empty response."
        except Exception as exc:
            logger.warning("LLM provider error: %s", exc)
            events.append({"type": "llm_error", "task": task, "error": str(exc)})
            return context_summary or f"The language model request failed: {exc}"


def clean_history(messages: Any) -> list[dict[str, Any]]:
    """Keep only well-formed user/assistant text turns."""
    if not isinstance(messages, list):
        return []
    return [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if isinstance(m, dict)
        and m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str)
        and m["content"]
    ]
