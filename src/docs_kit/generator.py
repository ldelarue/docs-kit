"""Render the OpenAPI endpoints reference page (ported from docs-playground).

Ordering is sort-stable on purpose: the two API repos export semantically
identical specs whose key order and info.title differ, but the generated page
must not. Paths and schema properties are sorted, methods follow a fixed
order, parameters are sorted by name.
"""

from __future__ import annotations

METHOD_ORDER = ("get", "put", "post", "patch", "delete")

BANNER = """!!! note "Generated page"

    This page is **generated** from `openapi.json` by `docs-kit`. Do not edit
    it by hand. Run `{regen_cmd}` to regenerate it.
"""


def backtick(s: str) -> str:
    return f"`{s}`"


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    def esc(c: str) -> str:
        return c.replace("|", "\\|")

    out = ["| " + " | ".join(esc(h) for h in headers) + " |", "|" + "|".join([":-:"] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join(esc(c) if c else "-" for c in row) + " |")
    return "\n".join(out)


def code_block(lines: list[str]) -> str:
    return "```console\n" + "\n".join(lines) + "\n```"


def openapi_type(schema: dict) -> str:
    if "$ref" in schema:
        return backtick(schema["$ref"].rsplit("/", 1)[-1])
    if "anyOf" in schema:
        return " | ".join(openapi_type(s) for s in schema["anyOf"])
    if "allOf" in schema:
        return " & ".join(openapi_type(s) for s in schema["allOf"])
    if "array" in schema:
        return f"Array of {openapi_type(schema['array'])}"
    if "enum" in schema:
        enum = ", ".join(backtick(str(e)) for e in schema["enum"])
        return f"{schema.get('type', 'string')} ({enum})"
    if "const" in schema:
        return f"{schema.get('type', 'string')} (= {backtick(str(schema['const']))})"
    if "items" in schema:
        return f"Array of {openapi_type(schema['items'])}"
    return schema.get("type", "object")


def deref(spec: dict, schema: dict) -> dict:
    seen = set()
    while "$ref" in schema and schema["$ref"] not in seen:
        seen.add(schema["$ref"])
        schema = spec.get("components", {}).get("schemas", {}).get(
            schema["$ref"].rsplit("/", 1)[-1], {}
        )
    return schema


def schema_table(spec: dict, schema: dict) -> str:
    schema = deref(spec, schema)
    props = schema.get("properties", {})
    if not props:
        return ""
    required = set(schema.get("required", []))
    rows = []
    for pname, prop in sorted(props.items()):
        prop = deref(spec, prop)
        constraints = []
        if "minimum" in prop:
            constraints.append(f"min {prop['minimum']}")
        if "maximum" in prop:
            constraints.append(f"max {prop['maximum']}")
        if "pattern" in prop:
            constraints.append(f"pattern `{prop['pattern']}`")
        desc = (prop.get("description") or "").strip()
        rows.append(
            [
                backtick(pname),
                openapi_type(prop),
                "yes" if pname in required else "no",
                ", ".join(constraints) or "-",
                desc or "-",
            ]
        )
    return md_table(["Field", "Type", "Required", "Constraints", "Description"], rows)


def generate_endpoints_page(
    spec: dict,
    spec_link: str,
    regen_cmd: str = "mise run docs:refresh",
    api_page: str = "api.md",
) -> str:
    comp = spec.get("components", {}).get("schemas", {})
    parts = ["# REST API Endpoints\n", BANNER.format(regen_cmd=regen_cmd) + "\n"]
    info = spec.get("info", {})
    parts.append(
        f"Canonical specification: **`{spec_link}`** "
        f"({info.get('title', '')} v{info.get('version', '')}). The interactive view is on "
        f"the [REST API]({api_page}) page.\n"
    )
    parts.append("## Endpoints\n")
    for path in sorted(spec.get("paths", {})):
        ops = spec["paths"][path]
        for method in METHOD_ORDER:
            if method not in ops:
                continue
            op = ops[method]
            heading = f"### `{method.upper()} {path}`"
            if op.get("summary"):
                heading += f" — {op['summary']}"
            parts.append(heading + "\n")
            meta = []
            if op.get("operationId"):
                meta.append(f"operation: {backtick(op['operationId'])}")
            if op.get("tags"):
                meta.append("tags: " + ", ".join(op["tags"]))
            if meta:
                parts.append(" · ".join(meta) + "\n")
            params = ops.get("parameters", []) + op.get("parameters", [])
            if params:
                rows = []
                for p in sorted(params, key=lambda p: p["name"]):
                    p = dict(p)
                    p["schema"] = deref(spec, p.get("schema", {}))
                    rows.append(
                        [
                            backtick(p["name"]),
                            p.get("in", "-"),
                            "yes" if p.get("required") else "no",
                            openapi_type(p.get("schema", {})),
                            (p.get("description") or "").strip() or "-",
                        ]
                    )
                parts.append("**Parameters**\n\n" + md_table(["Name", "In", "Required", "Type", "Description"], rows) + "\n")
            body_ref = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
            if body_ref:
                resolved = deref(spec, body_ref)
                table = schema_table(spec, resolved)
                if table:
                    parts.append("**Request body**\n\n" + table + "\n")
            rows = []
            for status, resp in sorted(op.get("responses", {}).items()):
                resp_schema = ""
                for ct in resp.get("content", {}).values():
                    s = ct.get("schema", {})
                    resp_schema = s.get("$ref", "").rsplit("/", 1)[-1] or openapi_type(s)
                    resp_schema = backtick(resp_schema) if not resp_schema.startswith("`") else resp_schema
                rows.append([backtick(status), (resp.get("description") or "").strip(), resp_schema or "-"])
            parts.append("**Responses**\n\n" + md_table(["Status", "Description", "Schema"], rows) + "\n")
    if comp:
        parts.append("## Schemas\n")
        for cname in sorted(comp):
            s = comp[cname]
            parts.append(f"### `{cname}`\n")
            parts.append(f"**Type:** {openapi_type(s)}\n")
            if s.get("description"):
                parts.append(s["description"].strip() + "\n")
            table = schema_table(spec, s)
            if table:
                parts.append(table + "\n")
    return "\n".join(parts) + "\n"
