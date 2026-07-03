"""JSON extraction from LLM responses (P2-6).

Isolates the first '{'..last '}' block -- tolerant of surrounding prose and
```json fences -- WITHOUT the nested-JSON corruption of a blanket
{{->{ / }}->} replace. The salvage step collapses a double-braced {{...}}
template-echo ONLY on the already-failed path, so valid nested JSON (which
parses on the first attempt) is never touched.
"""
import json
import re

_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> dict:
    """Parse the JSON object embedded in `text`.

    Raises json.JSONDecodeError if no valid object is found -- the calling
    retry loops treat that as a transient failure and re-call the model.
    """
    m = _BLOCK.search(text or "")
    candidate = m.group(0) if m else (text or "")
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Salvage an intermittent {{...}} template-echo. Reached only after
        # clean parse failed, so nested JSON is never corrupted here.
        return json.loads(candidate.replace("{{", "{").replace("}}", "}"))
