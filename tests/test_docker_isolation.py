import os

os.environ["DOCKER_HOST"] = "tcp://127.0.0.1:2375"
os.environ["HOST_WORKSPACE_DIR"] = os.path.abspath("./workspace")
os.environ["WORKSPACE_DIR"] = os.path.abspath("./workspace")

from src.tools.code_exec import python_repl_tool, bash_exec_tool  # noqa: I001

os.environ["DOCKER_HOST"] = "tcp://127.0.0.1:2375"
os.environ["HOST_WORKSPACE_DIR"] = os.path.abspath("./data/workspace")

if __name__ == "__main__":
    print("Test 1: Python REPL (Math)")
    result1 = python_repl_tool({"code": "print(2**10)"})
    print(result1)

    print("\nTest 2: Bash Exec (Network restricted)")
    result2 = bash_exec_tool(
        {"command": "curl -I https://google.com || echo 'Network is isolated!'"}
    )
    print(result2)

    print("\nTest 3: Python REPL (Memory Bomb limiting)")
    result3 = python_repl_tool(
        {"code": "a = 'x' * 1024 * 1024 * 300\nprint('Done without OOM')"}
    )
    print(result3)
