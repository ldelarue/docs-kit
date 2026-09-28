"""Where docs-kit reads and writes inside a consumer repository."""

from __future__ import annotations

REGEN_CMD = "docs-kit refresh"

API_SPEC_DEFAULT = "openapi.json"
VENDORED_SPEC = "docs/reference/openapi.json"
SWAGGER_PAGE = "docs/reference/swagger.html"
API_PAGE = "docs/references/api.md"
ENDPOINTS_PAGE = "docs/references/endpoints.md"

CLI_DIR = "cli"
KDL_SUFFIX = ".usage.kdl"
KDL_EXTRA_SUFFIX = ".usage.extra.kdl"
CLI_PAGE_DIR = "docs/references/cli"
CLI_STANDARD_PAGE = "docs/references/cli-standard.md"

ZENSICAL_CONFIG = "zensical.toml"
WORKFLOW = ".github/workflows/docs.yml"
MISE_LOCAL = "mise.local.toml"

# the [tools] line both mise modes pin so `usage` renders the CLI pages
USAGE_TOOL_PIN = 'usage = "latest"'
