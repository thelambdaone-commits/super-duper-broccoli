import requests

def main():
    eoa_address = "0xdc5585f67b57b9f5e1f7b57b9f5e1f7b57cf614E"
    print(f"Checking EOA: {eoa_address}")

    # Try querying positions from data api
    try:
        url = f"https://data-api.polymarket.com/positions?user={eoa_address}"
        print(f"Querying: {url}")
        resp = requests.get(url, timeout=10)
        print(f"Status: {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            print(f"Received positions: {len(data)} items")
            if data and isinstance(data, list):
                for item in data[:5]:
                    proxy = item.get("proxyWallet")
                    if proxy:
                        print(f"🎯 FOUND PROXY WALLET VIA POSITIONS API: {proxy}")
                        return
        else:
            print(f"Response content: {resp.text}")
    except Exception as e:
        print(f"Failed to query positions API: {e}")

    # Try querying trades from data api
    try:
        url = f"https://data-api.polymarket.com/trades?user={eoa_address}"
        print(f"Querying: {url}")
        resp = requests.get(url, timeout=10)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"Received trades: {len(data)} items")
            if data and isinstance(data, list):
                for item in data[:5]:
                    proxy = item.get("proxyWallet") or item.get("maker")
                    if proxy:
                        print(f"🎯 FOUND PROXY WALLET VIA TRADES API: {proxy}")
                        return
    except Exception as e:
        print(f"Failed to query trades API: {e}")

    # Try querying activity from data api
    try:
        url = f"https://data-api.polymarket.com/activity?user={eoa_address}"
        print(f"Querying: {url}")
        resp = requests.get(url, timeout=10)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"Received activity: {len(data)} items")
            if data and isinstance(data, list):
                for item in data[:5]:
                    proxy = item.get("proxyWallet") or item.get("user")
                    if proxy:
                        print(f"🎯 FOUND PROXY WALLET VIA ACTIVITY API: {proxy}")
                        return
    except Exception as e:
        print(f"Failed to query activity API: {e}")

if __name__ == "__main__":
    main()
