from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _repo_rel(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return (REPO_ROOT / candidate).resolve()


def list_repository_files(path: str = ".") -> list[str]:
    base = _repo_rel(path)
    results: list[str] = []
    if not base.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    for child in sorted(base.rglob("*")):
        if child.is_file():
            try:
                rel = child.relative_to(REPO_ROOT)
            except ValueError:
                rel = child
            results.append(rel.as_posix())
    return results


def read_text_file(path: str) -> str:
    file_path = _repo_rel(path)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    return file_path.read_text(encoding="utf-8")


def get_notebook_summary(path: str) -> dict[str, Any]:
    file_path = _repo_rel(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Notebook not found: {path}")
    if file_path.suffix.lower() != ".ipynb":
        raise ValueError(f"Not a notebook: {path}")

    payload = json.loads(file_path.read_text(encoding="utf-8"))
    cells = payload.get("cells", [])
    title = ""
    for cell in cells[:5]:
        source = "".join(cell.get("source", []))
        first_line = source.strip().splitlines()[0] if source.strip() else ""
        if first_line.startswith("#"):
            title = first_line.lstrip("# ")
            break
    return {
        "path": file_path.relative_to(REPO_ROOT).as_posix(),
        "title": title,
        "cell_count": len(cells),
        "kernelspec": payload.get("metadata", {}).get("kernelspec", {}),
    }


def read_csv_summary(path: str = "data/atlantis.csv") -> dict[str, Any]:
    file_path = _repo_rel(path)
    if not file_path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    with file_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        columns = reader.fieldnames or []

    return {
        "path": file_path.relative_to(REPO_ROOT).as_posix(),
        "columns": columns,
        "row_count": len(rows),
        "preview": rows[:5],
    }


def get_project_overview() -> dict[str, Any]:
    notebook_paths = sorted(p for p in REPO_ROOT.glob("notebooks/*.ipynb"))
    csv_paths = sorted(p for p in REPO_ROOT.glob("data/*.csv"))
    return {
        "repository": REPO_ROOT.name,
        "notebooks": [p.relative_to(REPO_ROOT).as_posix() for p in notebook_paths],
        "data_files": [p.relative_to(REPO_ROOT).as_posix() for p in csv_paths],
        "description": "A small notebook-and-data project for exploring population and ML examples.",
    }


def _tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "name": "list_repository_files",
            "description": "List all files in the repository with optional path filtering.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Relative path inside the repository to search from."}},
                "required": [],
            },
        },
        {
            "name": "read_text_file",
            "description": "Read a text file from the repository.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Relative path to the file."}},
                "required": ["path"],
            },
        },
        {
            "name": "read_csv_summary",
            "description": "Summarize a CSV file and return its columns, row count, and a preview.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Relative path to the CSV file."}},
                "required": [],
            },
        },
        {
            "name": "get_notebook_summary",
            "description": "Summarize the contents of a Jupyter notebook.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Relative path to the notebook."}},
                "required": ["path"],
            },
        },
        {
            "name": "get_project_overview",
            "description": "Get a lightweight overview of the repository's data and notebook assets.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    ]


def _handle_tool_call(name: str, arguments: dict[str, Any] | None) -> Any:
    args = arguments or {}
    if name == "list_repository_files":
        return list_repository_files(args.get("path", "."))
    if name == "read_text_file":
        return read_text_file(args["path"])
    if name == "read_csv_summary":
        return read_csv_summary(args.get("path", "data/atlantis.csv"))
    if name == "get_notebook_summary":
        return get_notebook_summary(args["path"])
    if name == "get_project_overview":
        return get_project_overview()
    raise ValueError(f"Unknown tool: {name}")


def _handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")

    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"ok": True}}

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
            },
            "serverInfo": {
                "name": "special-trout",
                "version": "0.1.0",
            },
        }
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": _tool_schemas()}}

    if method == "tools/call":
        tool_name = message.get("params", {}).get("name")
        arguments = message.get("params", {}).get("arguments")
        try:
            result = _handle_tool_call(tool_name, arguments)
            return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}}
        except Exception as exc:  # pragma: no cover - defensive CLI path
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": str(exc), "data": {"type": type(exc).__name__}},
            }

    if method == "resources/list":
        project = get_project_overview()
        resources = [
            {"uri": "file:///README.md", "name": "README", "mimeType": "text/markdown"},
            {"uri": "file:///data/atlantis.csv", "name": "Atlantis population data", "mimeType": "text/csv"},
            {"uri": "file:///notebooks/population.ipynb", "name": "Population notebook", "mimeType": "application/json"},
        ]
        if project["notebooks"]:
            for path in project["notebooks"]:
                resources.append({"uri": f"file:///{path}", "name": Path(path).name, "mimeType": "application/json"})
        return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": resources}}

    if method == "resources/read":
        uri = message.get("params", {}).get("uri")
        if not uri:
            raise ValueError("Missing resource uri")
        resource_path = uri.replace("file:///", "", 1)
        try:
            content = read_text_file(resource_path)
        except FileNotFoundError:
            raise
        return {"jsonrpc": "2.0", "id": request_id, "result": {"contents": [{"uri": uri, "mimeType": "text/plain", "text": content}]}}

    if method == "notifications/initialized":
        return None

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}", "data": {"method": method}},
    }


def main() -> None:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive CLI path
            print(
                json.dumps(
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Invalid JSON: {exc.msg}"}},
                ),
                flush=True,
            )
            continue

        response = _handle_message(message)
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
