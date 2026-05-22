#!/usr/bin/env python3
"""
Dual-Mode Redis Control

Permet de basculer à chaud (sans redémarrage) entre les modes PAPER, SHADOW et PROD
en publiant un message sur le channel Redis. Le bot écoutera ce channel.
"""
import redis
import argparse
import sys
import json
from colorama import init, Fore, Style

init(autoreset=True)

REDIS_CHANNEL = "lobstar:control:mode"

def switch_mode(mode: str, host="localhost", port=6379, db=0):
    mode = mode.upper()
    valid_modes = {"PAPER", "SHADOW", "PROD", "REPLAY"}

    if mode not in valid_modes:
        print(f"{Fore.RED}Mode invalide. Choisissez parmi: {', '.join(valid_modes)}{Style.RESET_ALL}")
        sys.exit(1)

    try:
        r = redis.Redis(host=host, port=port, db=db)
        # Test connection
        r.ping()

        payload = json.dumps({"action": "SWITCH_MODE", "mode": mode})
        subscribers = r.publish(REDIS_CHANNEL, payload)

        print(f"{Fore.GREEN}✅ Commande envoyée avec succès au channel '{REDIS_CHANNEL}'{Style.RESET_ALL}")
        print(f"{Fore.CYAN}Nouveau mode demandé : {Style.BRIGHT}{mode}{Style.RESET_ALL}")

        if subscribers > 0:
            print(f"{Fore.GREEN}📡 {subscribers} instance(s) du bot a/ont reçu la commande.{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}⚠️ Attention : Aucun abonné (bot) ne semble écouter sur ce channel actuellement.{Style.RESET_ALL}")

    except redis.ConnectionError:
        print(f"{Fore.RED}❌ Erreur de connexion à Redis ({host}:{port}). Le serveur est-il démarré ?{Style.RESET_ALL}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Redis Hot-Swap Mode Control")
    parser.add_argument("mode", type=str, choices=["PAPER", "SHADOW", "PROD", "REPLAY"], help="Le mode cible")
    parser.add_argument("--host", default="localhost", help="Redis host")
    parser.add_argument("--port", type=int, default=6379, help="Redis port")
    args = parser.parse_args()

    switch_mode(args.mode, args.host, args.port)
