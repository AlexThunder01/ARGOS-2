#!/usr/bin/env python3
import os
import json
import requests
import sys

# La porta default di n8n è 5678
N8N_URL = "http://localhost:5678/api/v1/workflows"

def inject_workflows():
    print("="*50)
    print("🚀 ARGOS AUTOMATED WORKFLOW INJECTOR FOR N8N")
    print("="*50)

    # 1. Load the API Key from the .env configuration file
    from dotenv import load_dotenv
    load_dotenv()
    
    api_key = os.getenv("N8N_API_KEY", "").strip()

    if not api_key:
        print("❌ Error: Missing or empty N8N_API_KEY variable within the .env file.")
        print("👉 Please provision a key within n8n (Settings -> API) and append it to your .env file as follows:")
        print("N8N_API_KEY=\"your_api_key_here\"")
        sys.exit(1)

    headers = {
        "X-N8N-API-KEY": api_key,
        "Accept": "application/json"
    }

    # 2. Retrieve all JSON workflow manifests within the workflows directory
    workflow_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workflows")
    
    if not os.path.exists(workflow_dir):
        print(f"❌ Error: Directory '{workflow_dir}' could not be located.")
        sys.exit(1)

    json_files = sorted([f for f in os.listdir(workflow_dir) if f.endswith('.json')])

    if not json_files:
        print(f"⚠️  No valid workflows detected within {workflow_dir}.")
        sys.exit(0)

    print(f"\n📂 Identified {len(json_files)} workflows. Initiating injection sequence...\n")

    # 3. Iterate over the files and push to the n8n REST server
    for filename in json_files:
        filepath = os.path.join(workflow_dir, filename)
        
        with open(filepath, 'r', encoding='utf-8') as file:
            try:
                workflow_data = json.load(file)
            except json.JSONDecodeError as e:
                print(f"❌ Corrupted file detected {filename}: {e}")
                continue

        print(f"🔄 Injecting workflow: {workflow_data.get('name', filename)}...")
        
        try:
            # The n8n REST API strictly dictates schema variables. Extraneous keys must be purged prior to POST execution.
            allowed_keys = ["name", "nodes", "connections", "settings", "staticData", "tags"]
            clean_workflow = {k: v for k, v in workflow_data.items() if k in allowed_keys}
            
            if "settings" not in clean_workflow:
                clean_workflow["settings"] = {}
                
            response = requests.post(N8N_URL, headers=headers, json=clean_workflow)
            
            if response.status_code == 200:
                print(f"   ✅ [SUCCESS] Workflow '{workflow_data.get('name')}' uploaded successfully.")
            elif response.status_code in [401, 403]:
                print(f"   ❌ [AUTH ERROR] The provided API Key is invalid or lacking permissions. Please verify your credentials.")
                sys.exit(1)
            else:
                print(f"   ⚠️  [WARNING] SERVER ERROR {response.status_code}: {response.text}")
                
        except requests.exceptions.ConnectionError:
            print("❌ CRITICAL ERROR: The n8n server instance appears unreachable. Ensure it is executing prior to script evaluation.")
            sys.exit(1)

    print("\n🎉 Operation concluded successfully. Access http://localhost:5678 to inspect your injected workflows.")

if __name__ == "__main__":
    inject_workflows()
