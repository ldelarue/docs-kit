"""docs-kit: scaffold and regenerate a Zensical API docs site from OpenAPI.

Doc generation is pure file I/O; the sole exception is the task-layer sync
(`pull-tasks`, and init's best-effort shim update), which shells out to git
to pin the shared/mise payload at this package's version tag.
"""

__version__ = "0.3.0"
