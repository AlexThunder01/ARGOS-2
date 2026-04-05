#!/usr/bin/env python3
"""
ARGOS Automated Workflow Injector — Full Zero-Touch Setup

This script performs a complete n8n environment bootstrap:
  1. Creates Telegram API credentials from .env
  2. Creates Gmail OAuth2 credential shell from .env (user must authorize once in n8n UI)
  3. Injects all workflow JSON files from the workflows/ directory
  4. Dynamically links credential IDs and Telegram Chat ID into workflow nodes
"""

import copy
import json
import os
import sys
import time

import requests
from n8n_client import get_n8n_config


def wait_for_n8n(base_url, headers, retries=30, delay=3):
    """Polls n8n until it responds or times out."""
    print(f"  ⏳ Waiting for n8n at {base_url}...", flush=True)
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(f"{base_url}/workflows", headers=headers, timeout=5)
            if r.status_code < 500:
                print(f"  ✅ n8n is ready (HTTP {r.status_code})")
                return
        except requests.exceptions.ConnectionError:
            pass
        print(f"  [{attempt}/{retries}] Not ready yet, retrying in {delay}s...", flush=True)
        time.sleep(delay)
    print("❌ n8n did not become ready in time. Aborting.")
    sys.exit(1)

# ==============================================================================
# Phase 1: Credential Creation
# ==============================================================================


def create_telegram_credential(base_url, headers, bot_token):
    """Creates a Telegram API credential in n8n and returns its ID."""
    payload = {
        "name": "Telegram account",
        "type": "telegramApi",
        "data": {"accessToken": bot_token},
    }
    resp = requests.post(
        f"{base_url}/credentials", headers=headers, json=payload, timeout=10
    )
    if resp.status_code in [200, 201]:
        resp_data = resp.json()
        cred_id = resp_data.get("id") or resp_data.get("data", {}).get("id")
        print(f"  ✅ Telegram credential created (ID: {cred_id})")
        return str(cred_id)
    else:
        print(
            f"  ⚠️  Telegram credential creation failed: {resp.status_code} - {resp.text}"
        )
        return None


def create_gmail_credential(base_url, headers, client_id, client_secret):
    """Creates a Gmail OAuth2 credential shell in n8n. User must authorize in the UI."""
    payload = {
        "name": "Gmail account",
        "type": "gmailOAuth2",
        "data": {
            "clientId": client_id,
            "clientSecret": client_secret,
            "serverUrl": "",
            "sendAdditionalBodyProperties": False,
            "additionalBodyProperties": "{}",
        },
    }
    resp = requests.post(
        f"{base_url}/credentials", headers=headers, json=payload, timeout=10
    )
    if resp.status_code in [200, 201]:
        resp_data = resp.json()
        cred_id = resp_data.get("id") or resp_data.get("data", {}).get("id")
        print(f"  ✅ Gmail OAuth2 credential created (ID: {cred_id})")
        return str(cred_id)
    else:
        print(
            f"  ⚠️  Gmail credential creation failed: {resp.status_code} - {resp.text}"
        )
        return None


# ==============================================================================
# Phase 2: Workflow Patching (Credential Linking + Chat ID Injection)
# ==============================================================================


def patch_workflow(
    workflow_data,
    telegram_cred_id,
    gmail_cred_id,
    telegram_chat_id,
    chat_bot_cred_id=None,
    is_chat_workflow=False,
):
    """
    Patches a workflow JSON in-memory:
      - Replaces 'REPLACE_WITH_YOUR_CREDENTIAL_ID' placeholders with real credential IDs
      - Replaces 'YOUR_TELEGRAM_CHAT_ID' with the actual chat ID
      - For chat bot workflows (05_*), uses chat_bot_cred_id instead of telegram_cred_id
    """
    patched = copy.deepcopy(workflow_data)

    # Select the correct Telegram credential based on workflow type
    tg_cred = chat_bot_cred_id if is_chat_workflow else telegram_cred_id
    tg_name = "Telegram Chat Bot" if is_chat_workflow else "Telegram account"

    for node in patched.get("nodes", []):
        # --- Inject Telegram Chat ID ---
        params = node.get("parameters", {})
        if params.get("chatId") == "YOUR_TELEGRAM_CHAT_ID" and telegram_chat_id:
            params["chatId"] = telegram_chat_id

        # --- Link Telegram Credentials ---
        creds = node.get("credentials", {})
        if "telegramApi" in creds and tg_cred:
            creds["telegramApi"]["id"] = tg_cred
            creds["telegramApi"]["name"] = tg_name

        # --- Link Gmail OAuth2 Credentials ---
        if "gmailOAuth2" in creds and gmail_cred_id:
            creds["gmailOAuth2"]["id"] = gmail_cred_id

        # --- Handle Gmail nodes (n8n-nodes-base.gmail / gmailTrigger) ---
        node_type = node.get("type", "")
        if (
            node_type in ["n8n-nodes-base.gmail", "n8n-nodes-base.gmailTrigger"]
            and gmail_cred_id
        ):
            if "credentials" not in node:
                node["credentials"] = {}
            node["credentials"]["gmailOAuth2"] = {
                "id": gmail_cred_id,
                "name": "Gmail account",
            }

        # --- Handle Telegram Trigger / Telegram nodes ---
        if (
            node_type in ["n8n-nodes-base.telegramTrigger", "n8n-nodes-base.telegram"]
            and tg_cred
        ):
            if "credentials" not in node:
                node["credentials"] = {}
            node["credentials"]["telegramApi"] = {"id": tg_cred, "name": tg_name}

    return patched


# ==============================================================================
# Phase 3: Main Injection Pipeline
# ==============================================================================


def inject_workflows():
    print("=" * 60)
    print("🚀 ARGOS AUTOMATED WORKFLOW INJECTOR (Full Zero-Touch Setup)")
    print("=" * 60)

    base_url, headers = get_n8n_config()
    wait_for_n8n(base_url, headers)
    endpoint = f"{base_url}/workflows"

    # --- Load environment variables ---
    from dotenv import load_dotenv

    load_dotenv()

    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip().strip('"')
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip().strip('"')
    google_client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip().strip('"')
    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip().strip('"')

    chat_bot_token = os.getenv("TELEGRAM_CHAT_BOT_TOKEN", "").strip().strip('"')

    # --- Phase 1: Create Credentials ---
    print("\n📦 Phase 1: Creating n8n Credentials...")

    telegram_cred_id = None
    gmail_cred_id = None
    chat_bot_cred_id = None

    if telegram_token:
        telegram_cred_id = create_telegram_credential(base_url, headers, telegram_token)
    else:
        print("  ⏭️  Skipping Telegram HITL: TELEGRAM_BOT_TOKEN not set in .env")

    if chat_bot_token:
        # Create a separate credential for the Chat Bot
        payload = {
            "name": "Telegram Chat Bot",
            "type": "telegramApi",
            "data": {"accessToken": chat_bot_token},
        }
        resp = requests.post(
            f"{base_url}/credentials", headers=headers, json=payload, timeout=10
        )
        if resp.status_code in [200, 201]:
            resp_data = resp.json()
            chat_bot_cred_id = str(
                resp_data.get("id") or resp_data.get("data", {}).get("id")
            )
            print(f"  ✅ Telegram Chat Bot credential created (ID: {chat_bot_cred_id})")
        else:
            print(
                f"  ⚠️  Chat Bot credential creation failed: {resp.status_code} - {resp.text}"
            )
    else:
        print(
            "  ⏭️  Skipping Telegram Chat Bot: TELEGRAM_CHAT_BOT_TOKEN not set in .env"
        )

    if google_client_id and google_client_secret:
        gmail_cred_id = create_gmail_credential(
            base_url, headers, google_client_id, google_client_secret
        )
    else:
        print(
            "  ⏭️  Skipping Gmail: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set in .env"
        )

    if not telegram_chat_id:
        print(
            "  ⏭️  No TELEGRAM_CHAT_ID found — chat ID placeholder will not be replaced."
        )

    # --- Phase 2: Inject Workflows ---
    print(f"\n📦 Phase 2: Injecting Workflows to {base_url}...")

    workflow_dir = "workflows"
    if not os.path.exists(workflow_dir):
        print(f"❌ Error: Directory '{workflow_dir}' not found.")
        return

    json_files = sorted([f for f in os.listdir(workflow_dir) if f.endswith(".json")])
    if not json_files:
        print("ℹ️  No JSON workflows found.")
        return

    injected_ids = []

    for filename in json_files:
        filepath = os.path.join(workflow_dir, filename)

        try:
            with open(filepath, "r", encoding="utf-8") as file:
                workflow_data = json.load(file)
        except Exception as e:
            print(f"  ❌ Failed to read {filename}: {e}")
            continue

        # Determine if this is a chat bot workflow (05_telegram_chat)
        is_chat_wf = filename.startswith("05_telegram")

        # Patch the workflow with real credentials and chat ID
        patched = patch_workflow(
            workflow_data,
            telegram_cred_id,
            gmail_cred_id,
            telegram_chat_id,
            chat_bot_cred_id=chat_bot_cred_id,
            is_chat_workflow=is_chat_wf,
        )

        print(f"  📤 Injecting: {filename}...", end=" ", flush=True)

        try:
            response = requests.post(
                endpoint, headers=headers, json=patched, timeout=15
            )

            if response.status_code in [200, 201]:
                wf_id = response.json().get("id", "??")
                injected_ids.append(wf_id)
                print(f"✅ [SUCCESS] ID: {wf_id}")
            elif response.status_code in [401, 403]:
                print("\n  ❌ [AUTH ERROR] Invalid N8N API Key.")
                sys.exit(1)
            else:
                print(
                    f"\n  ⚠️  [WARNING] HTTP {response.status_code}: {response.text[:200]}"
                )

        except requests.exceptions.ConnectionError:
            print(f"\n  ❌ [CONNECTION ERROR] Could not reach n8n at {base_url}.")
            sys.exit(1)
        except Exception as e:
            print(f"\n  ❌ [CRITICAL ERROR] {e}")

    # --- Phase 3: Auto-Activate Workflows ---
    if injected_ids:
        print(f"\n📦 Phase 3: Activating {len(injected_ids)} workflows...")
        for wf_id in injected_ids:
            r = requests.post(
                f"{endpoint}/{wf_id}/activate", headers=headers, timeout=10
            )
            status = "✅ Active" if r.status_code == 200 else f"⚠️  {r.status_code}"
            print(f"  [{wf_id}] {status}")

    # --- Summary ---
    print("\n" + "=" * 60)
    print("✨ Injection Complete!")
    print("=" * 60)

    if gmail_cred_id:
        print("\n⚠️  IMPORTANT: Gmail OAuth2 requires one-time authorization.")
        print("   1. Open n8n at http://localhost:5678")
        print("   2. Go to Credentials → Gmail account")
        print("   3. Click 'Sign in with Google' to complete the OAuth flow.")

    if not telegram_chat_id:
        print(
            "\n⚠️  REMINDER: Set TELEGRAM_CHAT_ID in your .env to receive notifications."
        )

    print()


if __name__ == "__main__":
    inject_workflows()
