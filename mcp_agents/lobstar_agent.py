import json
import logging
import os
import time
from typing import Optional, List, Dict, Any

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


LOBSTAR_SYSTEM_PROMPT = (
    "You are LOBSTAR Wilde, an autonomous HFT risk engine specialized in Polymarket and Solana CLOB. "
    "Your task is to parse unstructured Telegram signals and output a strict JSON object. "
    "JSON Format: {\"ticker\": str, \"side\": \"YES\"|\"NO\"|\"BUY\"|\"SELL\", "
    "\"price_limite\": float, \"size\": float, \"confidence\": float} "
    "If the signal is invalid, unreadable, or missing critical data, return exactly: "
    "{\"error\": \"INVALID_SIGNAL\"} "
    "Do not include conversational prose, markdown blocks, or thinking tags. Output ONLY raw JSON."
)


class LobstarAgent:
    def __init__(self, api_key: Optional[str] = None) -> None:
        self.logger = logging.getLogger("LobstarAgent")
        
        # Priority 1: Groq (Current default)
        self._groq_key = api_key or os.getenv("GROQ_API_KEY")
        self._nvidia_key = os.getenv("NVIDIA_API_KEY")
        self._mistral_key = os.getenv("MISTRAL_API_KEY")
        self._deepseek_key = os.getenv("DEEPSEEK_API_KEY")

        self.clients: Dict[str, AsyncOpenAI] = {}
        
        # Distributed Memory Access
        self._swarm = None
        try:
            from core.swarm_supervisor import get_swarm_supervisor
            self._swarm = get_swarm_supervisor()
        except ImportError:
            self.logger.warning("SwarmSupervisor not available, using local memory cache only.")

        if self._groq_key:
            self.clients["GROQ"] = AsyncOpenAI(api_key=self._groq_key, base_url="https://api.groq.com/openai/v1")
        if self._nvidia_key:
            self.clients["NVIDIA"] = AsyncOpenAI(api_key=self._nvidia_key, base_url="https://integrate.api.nvidia.com/v1")
        if self._mistral_key:
            self.clients["MISTRAL"] = AsyncOpenAI(api_key=self._mistral_key, base_url="https://api.mistral.ai/v1")
        if self._deepseek_key:
            self.clients["DEEPSEEK"] = AsyncOpenAI(api_key=self._deepseek_key, base_url="https://api.deepseek.com")

        self._cache: dict[str, tuple[float, Optional[dict]]] = {}
        self._consecutive_failures = 0
        self._fallback_active = False
        self._next_health_check = 0.0

        # Tool definitions for Function Calling
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_market_data",
                    "description": "Get live order book stats for a ticker (YES/NO odds, spread, liquidity).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string", "description": "Ticker symbol or token ID"},
                        },
                        "required": ["ticker"],
                    },
                },
            }
        ]

    def _regex_fallback(self, texte_signal: str) -> Optional[dict]:
        import re
        match = re.search(r"\b(BUY|SELL|YES|NO)\s+([A-Za-z0-9_]+)\b", texte_signal, re.IGNORECASE)
        if match:
            side = match.group(1).upper()
            ticker = match.group(2).upper()
            return {"ticker": ticker, "side": side, "price_limite": 0.0, "size": 0.0, "confidence": 0.5, "source": "REGEX_FALLBACK"}
        return None

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(min=1, max=4),
        retry=retry_if_exception_type(Exception),
    )
    async def _call_provider(
        self, 
        provider: str, 
        texte_signal: str, 
        ml_context: Optional[dict] = None,
        tool_map: Optional[dict] = None
    ) -> dict:
        client = self.clients.get(provider)
        if not client:
            raise ValueError(f"Provider {provider} not configured")

        model_map = {
            "GROQ": "llama-3.3-70b-versatile",
            "NVIDIA": "meta/llama-3.1-8b-instruct",
            "MISTRAL": "mistral-tiny",
            "DEEPSEEK": "deepseek-chat"
        }
        
        model = model_map.get(provider, "gpt-4o-mini")
        
        system_prompt = LOBSTAR_SYSTEM_PROMPT
        if ml_context:
            system_prompt += f"\n\nML CONTEXT: {json.dumps(ml_context)}"
            
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": texte_signal},
        ]
        
        # Extra params for specific providers
        extra_params = {}
        # Only Groq and NVIDIA support tools/json_object consistently here
        if provider in ("GROQ", "NVIDIA"):
            if tool_map:
                extra_params["tools"] = self.tools
                extra_params["tool_choice"] = "auto"
            else:
                extra_params["response_format"] = {"type": "json_object"}
            
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.0,
            max_tokens=300,
            **extra_params
        )
        
        message = response.choices[0].message
        
        # Handle Tool Calls
        if message.tool_calls:
            messages.append(message)
            for tool_call in message.tool_calls:
                func_name = tool_call.function.name
                func_args = json.loads(tool_call.function.arguments)
                
                self.logger.info(f"🛠️ LLM ({provider}) calling tool: {func_name}({func_args})")
                
                if tool_map and func_name in tool_map:
                    result = await tool_map[func_name](**func_args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": func_name,
                        "content": json.dumps(result),
                    })
                else:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": func_name,
                        "content": "{\"error\": \"TOOL_NOT_AVAILABLE\"}",
                    })
            
            # Second call after tools
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.0,
                max_tokens=200,
                response_format={"type": "json_object"} if provider == "GROQ" else None
            )
            content = response.choices[0].message.content.strip()
        else:
            content = message.content.strip()

        # Basic JSON cleanup if not using json_object mode
        if not content.startswith("{"):
            import re
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                content = json_match.group(0)
                
        data = json.loads(content)
        data["provider"] = provider
        return data

    async def analyser_signal_contextuel(
        self, 
        texte_signal: str,
        ml_context: Optional[dict] = None,
        tool_map: Optional[dict] = None
    ) -> Optional[dict]:
        now = time.time()
        # Clean expired local keys (60 seconds expiration TTL)
        self._cache = {k: (ts, val) for k, (ts, val) in self._cache.items() if now - ts < 60.0}

        # 1. Check local cache first (L1)
        if texte_signal in self._cache:
            self.logger.info("Semantic inference cache hit (L1: local) for signal context")
            return self._cache[texte_signal][1]

        # 2. Check Swarm distributed cache (L2: Redis)
        import hashlib
        h = hashlib.md5(texte_signal.encode("utf-8")).hexdigest()
        cache_key = f"lobstar:cache:{h}"
        if self._swarm:
            distributed_val = await self._swarm.get_shared_value_async(cache_key)
            if distributed_val:
                # Validate TTL for distributed value (stored as [ts, data])
                ts, data = distributed_val
                if now - ts < 60.0:
                    self.logger.info("Semantic inference cache hit (L2: distributed) for signal context")
                    self._cache[texte_signal] = (ts, data) # Sync L1
                    return data

        if self._fallback_active:
            if now < self._next_health_check:
                return self._regex_fallback(texte_signal)
            else:
                self._fallback_active = False
                self._consecutive_failures = 0

        # LLM Fallback Chain: GROQ -> NVIDIA -> MISTRAL -> DEEPSEEK
        providers_to_try = ["GROQ", "NVIDIA", "MISTRAL", "DEEPSEEK"]
        
        for provider in providers_to_try:
            if provider not in self.clients:
                continue
                
            try:
                data = await self._call_provider(
                    provider, 
                    texte_signal, 
                    ml_context=ml_context, 
                    tool_map=tool_map
                )
                self._consecutive_failures = 0
                
                if "error" in data and data["error"] == "INVALID_SIGNAL":
                    self._cache[texte_signal] = (now, None)
                    if self._swarm:
                        self._swarm.set_shared_value(cache_key, [now, None])
                    return None

                # Update L1 & L2 caches
                self._cache[texte_signal] = (now, data)
                if self._swarm:
                    self._swarm.set_shared_value(cache_key, [now, data])
                    
                self.logger.info(f"✅ Signal parsed successfully via {provider}")
                return data

            except Exception as e:
                self.logger.warning(f"⚠️ Provider {provider} failed: {e}")
                continue # Try next provider

        # If all LLM providers fail
        self._consecutive_failures += 1
        self.logger.error(f"❌ All LLM providers failed (Total consecutive: {self._consecutive_failures})")
        
        if self._consecutive_failures >= 3:
            self._fallback_active = True
            self._next_health_check = now + 300.0
            self.logger.critical("🚨 LLM STACK UNRESPONSIVE. DETERMINISTIC FALLBACK ACTIVATED for 5 minutes.")
        
        return self._regex_fallback(texte_signal)
