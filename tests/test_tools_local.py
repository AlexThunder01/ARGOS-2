import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.tools import TOOLS
import platform

def run_test(name, payload):
    print(f"\n--- Testing {name} ---")
    try:
        res = TOOLS[name](payload)
        success = not str(res).startswith(("Error", "Errore"))
        status = "✅ OK" if success else "❌ FAILED"
        print(f"{status} | Payload: {payload}")
        print(f"Result Preview: {str(res)[:150]}...")
        return success
    except Exception as e:
        print(f"❌ CRASH | {e}")
        return False

def main():
    print("🧪 ARGOS Local Tools Diagnostic Suite")
    
    tests = [
        ("finance_price", {"asset": "AAPL"}),
        ("crypto_price", {"coin": "bitcoin"}),
        ("system_stats", {}),
        ("web_search", {"query": "python programming"}),
        ("list_files", {"path": "~"}),
    ]
    
    # File System Lifecycle Test
    desktop = os.path.join(os.path.expanduser("~"), "Scrivania")
    if not os.path.exists(desktop): desktop = os.path.expanduser("~")
    
    test_file = os.path.join(desktop, "argos_test_fs.txt")
    test_file_renamed = os.path.join(desktop, "argos_test_fs_renamed.txt")
    test_dir = os.path.join(desktop, "argos_test_dir")
    
    fs_tests = [
        ("create_file", {"path": test_file, "content": "Hello World"}),
        ("read_file", {"path": test_file}),
        ("modify_file", {"path": test_file, "old_text": "World", "new_text": "ARGOS"}),
        ("rename_file", {"old_path": test_file, "new_path": test_file_renamed}),
        ("delete_file", {"path": test_file_renamed}),
        ("create_directory", {"path": test_dir}),
        ("delete_directory", {"path": test_dir}),
    ]
    
    results = []
    
    print("\nPhase 1: Benign & Data Tools")
    for t, p in tests:
        results.append(run_test(t, p))
        
    print("\nPhase 2: File System Manipulation")
    for t, p in fs_tests:
        results.append(run_test(t, p))
        
    print("\nPhase 3: GUI/OS Tools (Simulated)")
    app = "calc" if platform.system() == "Windows" else "gnome-calculator"
    # Just echo something to not actually open calculator
    results.append(run_test("launch_app", {"command": f"echo 'Launching {app}'"}))
    
    print("\n" + "="*40)
    print(f"Total Tests: {len(results)}")
    print(f"Passed: {results.count(True)}")
    print(f"Failed: {results.count(False)}")
    print("="*40)

if __name__ == "__main__":
    main()
