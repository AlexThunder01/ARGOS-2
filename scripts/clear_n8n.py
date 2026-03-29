#!/usr/bin/env python3
import os
import requests
import sys

from scripts.n8n_client import get_n8n_config

def clear_n8n():
    print("="*50)
    print("🗑️  ARGOS N8N WORKFLOW CLEANER")
    print("="*50)

    base_url, headers = get_n8n_config()
    endpoint = f"{base_url}/workflows"

    try:
        # 1. Fetch all workflows
        print(f"🔍 Fetching workflows from {base_url}...")
        resp = requests.get(endpoint, headers=headers, timeout=10)
        
        if resp.status_code != 200:
            print(f"❌ Failed to fetch: {resp.status_code} - {resp.text}")
            return

        workflows = resp.json()
        if not workflows:
            print("ℹ️  No workflows found. Nothing to delete.")
            return

        # 2. Safety Confirmation
        print(f"⚠️  WARNING: You are about to delete {len(workflows)} workflows.")
        confirm = input("👉 To proceed, type 'CONFIRM': ").strip()
        if confirm != "CONFIRM":
            print("🚫 Operation cancelled by user.")
            return

        # 3. Batch Delete
        for wf in workflows:
            wf_id = wf['id']
            wf_name = wf['name']
            
            print(f"🔥 Deleting [{wf_id}] {wf_name}...", end=" ", flush=True)
            
            del_url = f"{endpoint}/{wf_id}"
            del_resp = requests.delete(del_url, headers=headers, timeout=10)
            
            if del_resp.status_code in [200, 204]:
                print("✅ Deleted.")
            else:
                print(f"❌ Failed ({del_resp.status_code}).")

        print(f"\n✨ Cleanup complete. {len(workflows)} workflows removed.")

    except requests.exceptions.ConnectionError:
        print(f"❌ [CONNECTION ERROR] Could not reach n8n at {base_url}.")
    except Exception as e:
        print(f"❌ [ERROR] {e}")

if __name__ == "__main__":
    clear_n8n()
