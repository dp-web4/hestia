import json
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/scratchpad/kimi-review-sage-622")
from sage.gateway.being_gate_client import ollama_tools
from sage.gateway.being_tool_loop import salvage_tool_calls

TOOLS = ollama_tools(["memory_write"])
CASES = {
    "negated_json_in_prose": 'I will not do this: {"name":"memory_write","arguments":{"path":"notes/x","content":"draft"}}',
    "fenced_json_example": 'For example:\n```json\n{"name":"memory_write","arguments":{"path":"notes/x","content":"draft"}}\n```',
    "hypothetical_python": 'Hypothetical only; do not execute:\n```python\nmemory_write(path="notes/x", content="draft")\n```',
    "valid_json_then_unreachable_python": '```json\n{"name":"memory_write","arguments":{"path":"notes/x","content":"draft"}}\n```\n```python\nif False:\n    memory_write(path="notes/y", content="other")\n```',
    "unrelated_tools_import": '```python\nfrom elsewhere import tools\ntools.memory_write(path="notes/x", content="draft")\n```',
    "unsupported_python_qualifier": '```python\nmemory_write(path="notes/x", content="draft", dry_run=True)\n```',
    "flat_json_qualifier": '{"name":"memory_write","path":"notes/x","content":"draft","dry_run":true}',
    "straight_line_positive": '```python\nx = "draft"\nresult = memory_write(path="notes/x", content=x)\nprint(result)\n```',
    "attribute_positive": 'memory_write path="notes/x" content="draft"',
}
for name, text in CASES.items():
    calls = salvage_tool_calls(text, TOOLS)
    print(json.dumps({"case": name, "calls": calls}, sort_keys=True))
