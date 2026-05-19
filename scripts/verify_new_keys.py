#!/usr/bin/env python3
import os
import sys
import time
import asyncio
import json
import requests
from dotenv import load_dotenv

# Colors for premium CLI styling
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
NC = "\033[0m"

load_dotenv()

async def test_nvidia():
    key = os.getenv("NVIDIA_API_KEY")
    if not key:
        return {"status": "SKIPPED", "msg": "NVIDIA_API_KEY not configured."}
    
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    # Correct NVIDIA NIM endpoint (build.nvidia.com)
    payload = {
        "model": "meta/llama-3.1-8b-instruct",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5
    }
    t0 = time.perf_counter()
    try:
        r = requests.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=8.0
        )
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            return {"status": "SUCCESS", "latency": f"{dt:.1f}ms", "msg": "NVIDIA API is valid."}
        else:
            return {"status": "FAILED", "msg": f"HTTP {r.status_code}: {r.text[:100]}"}
    except Exception as e:
        return {"status": "FAILED", "msg": str(e)}

async def test_mistral():
    key = os.getenv("MISTRAL_API_KEY")
    if not key:
        return {"status": "SKIPPED", "msg": "MISTRAL_API_KEY not configured."}
    
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "mistral-tiny",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5
    }
    t0 = time.perf_counter()
    try:
        r = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=8.0
        )
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            return {"status": "SUCCESS", "latency": f"{dt:.1f}ms", "msg": "Mistral API is valid."}
        else:
            return {"status": "FAILED", "msg": f"HTTP {r.status_code}: {r.text[:100]}"}
    except Exception as e:
        return {"status": "FAILED", "msg": str(e)}

async def test_deepseek():
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        return {"status": "SKIPPED", "msg": "DEEPSEEK_API_KEY not configured."}
    
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5
    }
    t0 = time.perf_counter()
    try:
        r = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers=headers,
            json=payload,
            timeout=8.0
        )
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            return {"status": "SUCCESS", "latency": f"{dt:.1f}ms", "msg": "DeepSeek API is valid."}
        else:
            return {"status": "FAILED", "msg": f"HTTP {r.status_code}: {r.text[:100]}"}
    except Exception as e:
        return {"status": "FAILED", "msg": str(e)}

async def test_huggingface():
    key = os.getenv("HUGGINGFACE_API_KEY")
    if not key:
        return {"status": "SKIPPED", "msg": "HUGGINGFACE_API_KEY not configured."}
    
    headers = {"Authorization": f"Bearer {key}"}
    t0 = time.perf_counter()
    try:
        # Testing by querying the user info
        r = requests.get(
            "https://huggingface.co/api/whoami-v2",
            headers=headers,
            timeout=8.0
        )
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            return {"status": "SUCCESS", "latency": f"{dt:.1f}ms", "msg": "Hugging Face API is valid."}
        else:
            return {"status": "FAILED", "msg": f"HTTP {r.status_code}: {r.text[:100]}"}
    except Exception as e:
        return {"status": "FAILED", "msg": str(e)}

async def test_groq():
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return {"status": "SKIPPED", "msg": "GROQ_API_KEY not configured."}
    
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5
    }
    t0 = time.perf_counter()
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=8.0
        )
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            return {"status": "SUCCESS", "latency": f"{dt:.1f}ms", "msg": "Groq API is valid."}
        else:
            return {"status": "FAILED", "msg": f"HTTP {r.status_code}: {r.text[:100]}"}
    except Exception as e:
        return {"status": "FAILED", "msg": str(e)}

async def test_coingecko():
    key = os.getenv("COINGECKO_API_KEY")
    if not key:
        return {"status": "SKIPPED", "msg": "COINGECKO_API_KEY not configured."}
    
    t0 = time.perf_counter()
    try:
        # Testing CoinGecko Pro/Demo API key
        r = requests.get(
            f"https://api.coingecko.com/api/v3/ping?x_cg_demo_api_key={key}",
            timeout=8.0
        )
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            return {"status": "SUCCESS", "latency": f"{dt:.1f}ms", "msg": "CoinGecko API is valid."}
        else:
            # Try Pro endpoint if Demo fails
            r_pro = requests.get(
                f"https://pro-api.coingecko.com/api/v3/ping?x_cg_pro_api_key={key}",
                timeout=8.0
            )
            if r_pro.status_code == 200:
                return {"status": "SUCCESS", "latency": f"{dt:.1f}ms", "msg": "CoinGecko Pro API is valid."}
            return {"status": "FAILED", "msg": f"HTTP {r.status_code}: {r.text[:100]}"}
    except Exception as e:
        return {"status": "FAILED", "msg": str(e)}

async def run_diagnostics():
    print("\n" + "═" * 70)
    print(" 🔎 NEW AI PROVIDERS & COINGECKO CONNECTIVITY AUDIT")
    print("═" * 70)

    results = {}
    
    tests = [
        ("NVIDIA", test_nvidia),
        ("Groq", test_groq),
        ("Mistral", test_mistral),
        ("DeepSeek", test_deepseek),
        ("Hugging Face", test_huggingface),
        ("CoinGecko", test_coingecko),
    ]

    for name, test_func in tests:
        print(f" • Testing {name}... ", end="", flush=True)
        res = await test_func()
        results[name] = res
        if res["status"] == "SUCCESS":
            print(f"{GREEN}SUCCESS{NC} ({res['latency']})")
        elif res["status"] == "SKIPPED":
            print(f"{YELLOW}SKIPPED{NC} ({res['msg']})")
        else:
            print(f"{RED}FAILED{NC} ({res['msg']})")

    print("\n" + "═" * 70)
    print(" SUMMARY REPORT:")
    for key, val in results.items():
        if val["status"] == "FAILED":
            print(f"   - {key:<15}: {RED}FAIL{NC} ({val['msg']})")
        elif val["status"] == "SUCCESS":
            print(f"   - {key:<15}: {GREEN}OK{NC} (Latency: {val['latency']})")
        else:
            print(f"   - {key:<15}: {YELLOW}SKIPPED{NC} ({val['msg']})")
    
    print("═" * 70 + "\n")

if __name__ == "__main__":
    asyncio.run(run_diagnostics())
