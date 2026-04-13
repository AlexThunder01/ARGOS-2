import json
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv(".env")
api_key = os.environ.get("ARGOS_API_KEY", "")
url = "http://localhost:8000/api/chat/stream"
headers = {"X-ARGOS-API-KEY": api_key, "Content-Type": "application/json"}


# ANSI colors
class c:
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    MAGENTA = "\033[95m"
    RED = "\033[91m"
    END = "\033[0m"
    BOLD = "\033[1m"


def chat(task, history, max_steps=10):
    print(f"{c.BLUE}YOU:{c.END} {task}")
    print(f"{c.GREEN}ARGOS:{c.END} ", end="")

    start_time = time.time()
    try:
        resp = requests.post(
            url,
            headers=headers,
            json={"task": task, "history": history, "max_steps": max_steps},
            stream=True,
            timeout=120,
        )
    except Exception as e:
        print(f"\n{c.RED}[CRITICAL ERROR] Connection failed: {e}{c.END}")
        return ""

    if resp.status_code != 200:
        print(f"\n{c.RED}[HTTP ERROR {resp.status_code}] {resp.text}{c.END}")
        return ""

    agent_msg = ""
    for line in resp.iter_lines(decode_unicode=True):
        if line.startswith("data: "):
            payload = line.replace("data: ", "")
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload).get("chunk", "")
                agent_msg += chunk
                print(chunk, end="", flush=True)
            except Exception:
                pass

    dt = time.time() - start_time
    print(f"\n{c.MAGENTA}[Risposta completata in {dt:.2f}s]{c.END}\n")
    return agent_msg


def run_suite():
    print(f"{c.BOLD}=== INIZIO TESTING COMPLETO ARGOS E2E ==={c.END}\n")

    # Svuoto la memoria a breve termine per forzare la lettura tramite RAG dal DB PostgreSQL.
    h_rag = []
    q_r1 = "Qual è il mio frutto preferito e il mio lavoro reale di cui ti ho parlato precedentemente? Te ne avevo parlato molto tempo fa, frugati bene in memoria."
    a_r1 = chat(q_r1, h_rag)

    print(f"{c.BOLD}=== FINE TESTING COMPLETO ==={c.END}")


if __name__ == "__main__":
    run_suite()
