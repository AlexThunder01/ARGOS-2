#!/usr/bin/env python3
import os
import sys
import requests
from dotenv import load_dotenv

N8N_URL = "http://localhost:5678/api/v1/workflows"

def clear_workflows(target=None):
    print("="*50)
    print("🧹 ARGOS WORKFLOW CLEANUP UTILITY FOR N8N")
    print("="*50)
    print("="*50)

    load_dotenv()
    api_key = os.getenv("N8N_API_KEY", "").strip()

    if not api_key:
        print("❌ Error: Missing or empty N8N_API_KEY variable within the .env file.")
        sys.exit(1)

    headers = {
        "X-N8N-API-KEY": api_key,
        "Accept": "application/json"
    }

    try:
        response = requests.get(N8N_URL, headers=headers)
    except requests.exceptions.ConnectionError:
        print("❌ CRITICAL ERROR: The n8n server instance appears unreachable. Ensure it is executing prior to script evaluation.")
        sys.exit(1)

    if response.status_code != 200:
        print(f"❌ Error retrieving workflows: {response.status_code} - {response.text}")
        sys.exit(1)

    data = response.json()
    workflows = data.get("data", [])
    
    if not workflows:
        print("✅ No established workflows detected on the n8n instance. Initialization state is clear.")
        return

    to_delete = []
    
    # Apply filter targeting either workflow ID or Name string sequence
    if target:
        for wf in workflows:
            if target == str(wf.get("id")) or target.lower() in wf.get("name", "").lower():
                to_delete.append(wf)
        
        if not to_delete:
            print(f"⚠️ No workflow matching the target query '{target}' was identified.")
            return
    else:
        to_delete = workflows

    print(f"\n🗑️ Proceeding with the deletion of {len(to_delete)} identified workflows...\n")

    for wf in to_delete:
        wf_id = wf.get("id")
        wf_name = wf.get("name", "Unknown")
        print(f"➖ Executing deletion: [{wf_id}] {wf_name}")
        
        delete_url = f"{N8N_URL}/{wf_id}"
        del_resp = requests.delete(delete_url, headers=headers)
        
        if del_resp.status_code == 200:
            print(f"   ✅ Successfully deleted.")
        else:
            print(f"   ❌ Deletion failure encountered: {del_resp.status_code} - {del_resp.text}")

    print("\n🎉 Cleanup process successfully concluded.")

if __name__ == "__main__":
    # Bash positional arguments are utilized to explicitly filter the target workflow query
    target_wf = sys.argv[1] if len(sys.argv) > 1 else None
    clear_workflows(target_wf)
