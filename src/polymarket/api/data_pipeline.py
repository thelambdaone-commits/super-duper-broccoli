import os
import re
import json
import time
import logging
from typing import Any, Dict, Optional, Tuple
import numpy as np

from openai import AsyncOpenAI
from utils.llm_council import resolve_openrouter_api_key
from core.container import ServiceContainer

logger = logging.getLogger("DataPipeline")

class JSONLStorageEngine:
    _default_path = "data/archive_events.jsonl"
    _raw_stream_dir = "user_data/data/raw_stream"

    @classmethod
    async def archiver_evenement(cls, type_tag: str, payload: dict, custom_path: str = None) -> None:
        """
        Asynchronously archives any event payload to a JSONL file in a non-blocking manner.
        """
        timestamp = time.time()
        # Strip complex objects like Update or Client to ensure proper JSON serialization
        serializable_payload = {}
        for k, v in payload.items():
            if k == "update":
                continue
            serializable_payload[k] = v

        event = {
            "timestamp": timestamp,
            "type": type_tag,
            "payload": serializable_payload
        }

        # Resolve path
        if custom_path:
            target_path = custom_path
        else:
            date_str = time.strftime("%Y-%m-%d", time.gmtime(timestamp))
            target_path = os.path.join(cls._raw_stream_dir, f"events_{date_str}.jsonl")

        # Let's ensure directories exist
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        cls._write_event_sync(target_path, event)

    @classmethod
    def _write_event_sync(cls, path: str, event: dict) -> None:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except Exception as e:
            logger.error(f"Failed to write event to {path}: {e}")


class PredictiveOpinionEngine:
    """
    Tool-aware Market opinion engine utilizing Claude 3.5 Sonnet via OpenRouter,
    providing structured context-aware trading insights with local FastMCP tool integration.
    """
    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://openrouter.ai/api/v1") -> None:
        self.api_key = resolve_openrouter_api_key() if api_key is None else api_key
        self.base_url = base_url
        self.model = "anthropic/claude-3.5-sonnet"

    async def analyse_signal(self, raw_message: str, ticker: str = "SOL") -> dict:
        """
        Analyzes a raw trading signal message by running a tool-aware chat completion loop.
        """
        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY missing. Returning simulated mock analysis.")
            return self._mock_fallback(raw_message, ticker)

        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_ledger_state",
                    "description": "Retrieve current ledger capital summary and open positions.",
                    "parameters": {"type": "object", "properties": {}}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_market_regime",
                    "description": "Retrieve HMM regime, volatility state, dissimilarity index, and trading permission details for a specific crypto asset.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticker": {
                                "type": "string",
                                "description": "The crypto ticker symbol, e.g. BTC, ETH, SOL",
                                "default": "SOL"
                            }
                        }
                    }
                }
            }
        ]

        system_prompt = (
            "You are the LOBSTAR Wilde tactical intelligence. Your goal is to maximize portfolio profit "
            "by adjusting trading strategies based on current microstructure, ledger status, and HMM volatility regime.\n"
            "You have access to get_ledger_state and get_market_regime tools.\n"
            "Analyze the incoming signal and formulate a context-aware opinion.\n"
            "You MUST finally respond with a single, strictly valid JSON block, using EXACTLY the following structure:\n"
            "{\n"
            "  \"reasoning\": \"Explication détaillée de la structure du carnet et du régime HMM\",\n"
            "  \"confidence\": 0.85,\n"
            "  \"verdict\": \"BUY\" | \"SELL\" | \"HOLD\",\n"
            "  \"target_asset\": \"BTC\" | \"ETH\" | \"SOL\",\n"
            "  \"recommended_sizing_pct\": 10.0\n"
            "}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"New trading signal text:\n{raw_message}\nTicker context: {ticker}"}
        ]

        try:
            # First turn: model might call tools
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.0
            )

            response_message = response.choices[0].message
            tool_calls = response_message.tool_calls

            if tool_calls:
                # Append assistant message with tool calls
                messages.append(response_message)

                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments or "{}")
                    
                    # Execute tool locally
                    if function_name == "get_ledger_state":
                        result = self._execute_get_ledger_state()
                    elif function_name == "get_market_regime":
                        t = args.get("ticker", ticker)
                        result = self._execute_get_market_regime(t)
                    else:
                        result = {"error": f"Unknown tool: {function_name}"}

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": function_name,
                        "content": json.dumps(result)
                    })

                # Second turn: get final decision with tool context
                second_response = await client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.0
                )
                content = second_response.choices[0].message.content
            else:
                content = response_message.content

            # Parse content for JSON block
            return self._parse_json_result(content, ticker)

        except Exception as e:
            logger.error(f"PredictiveOpinionEngine failed: {e}")
            return self._mock_fallback(raw_message, ticker, error=str(e))

    def _execute_get_ledger_state(self) -> dict:
        container = ServiceContainer.get_instance()
        ledger = container.ledger
        if not ledger:
            return {"error": "Ledger not available in container"}
        try:
            return {
                "capital_summary": ledger.get_capital_summary(),
                "open_positions": ledger.get_open_positions(),
            }
        except Exception as e:
            return {"error": str(e)}

    def _execute_get_market_regime(self, ticker: str) -> dict:
        container = ServiceContainer.get_instance()
        hmm_filter = container.hmm
        if not hmm_filter:
            return {"error": "HMM filter not available in container", "regime": "UNKNOWN"}
        try:
            returns = np.zeros(100, dtype=np.float32)
            state, label = hmm_filter.predict_with_label(returns)
            di = hmm_filter.compute_dissimilarity_index(returns)
            allowed, reason = hmm_filter.is_trading_allowed(returns)
            return {
                "ticker": ticker,
                "hmm_state": int(state),
                "regime_label": label,
                "dissimilarity_index": round(float(di), 6),
                "trading_allowed": allowed,
                "reason": reason,
            }
        except Exception as e:
            return {"error": str(e)}

    def _parse_json_result(self, content: str, default_ticker: str) -> dict:
        if not content:
            raise ValueError("Empty response from model")
        
        # Look for JSON patterns inside response
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
        else:
            parsed = json.loads(content)

        # Standardize returns
        return {
            "reasoning": parsed.get("reasoning", "No reasoning supplied."),
            "confidence": float(parsed.get("confidence", 0.5)),
            "verdict": parsed.get("verdict", "HOLD"),
            "target_asset": parsed.get("target_asset", default_ticker),
            "recommended_sizing_pct": float(parsed.get("recommended_sizing_pct", 0.0))
        }

    def _mock_fallback(self, raw_message: str, ticker: str, error: str = None) -> dict:
        weights = {}
        if os.path.exists("data/ml_weights.json"):
            try:
                with open("data/ml_weights.json", "r") as f:
                    weights = json.load(f)
            except Exception:
                pass
        
        bias = weights.get("bias_factors", {}).get(ticker.upper(), 1.0)
        
        return {
            "reasoning": f"Simulated fallback analysis. Status: {error or 'Credentials missing'}.",
            "confidence": round(0.7 * bias, 2),
            "verdict": "HOLD",
            "target_asset": ticker,
            "recommended_sizing_pct": 0.0
        }
