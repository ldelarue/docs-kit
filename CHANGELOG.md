# Changelog

## [0.2.0](https://github.com/ldelarue/docs-kit/compare/v0.1.0...v0.2.0) (2026-09-18)


### Features

* `docs-kit serve` CLI command (port leasing + zensical/uvx); docs:serve mise task and docs now delegate to it ([515a2cd](https://github.com/ldelarue/docs-kit/commit/515a2cd0878a127a8d52ae82c43c84918214694d))
* docs:serve port leasing via shared/scripts/lease-port + self-healing init integration ([ffd2883](https://github.com/ldelarue/docs-kit/commit/ffd288383c55a8c82ff1dcadf510a0744dd560a6))
* init in shim mode writes docs:kit-sync task and .gitignore entry (makes way-2 setup one command) ([a191f32](https://github.com/ldelarue/docs-kit/commit/a191f32e674ee2937123207f402722174ccf18fe))
* mise tasks to build wheels and install them locally ([d914831](https://github.com/ldelarue/docs-kit/commit/d914831c38b5f3ef550798580021c70053d76998))
* move docs:kit-sync logic into shared/scripts/kit-sync engine; emitted task delegates (inline fallback keeps pre-engine layers working) ([6c91b32](https://github.com/ldelarue/docs-kit/commit/6c91b3238a36be2609fc4a859e144752d474976f))
* scaffold consumers with tag-pinned docs-kit CI checkout ([97f72a0](https://github.com/ldelarue/docs-kit/commit/97f72a09cde0d69fef43053578db96762ac8209b))
* shim mode writes everything to mise.local.toml (tracked config stays clean), version pull fetches only /shared/mise (task renamed docs:pull-tasks; engine moved into the payload) ([a02fd52](https://github.com/ldelarue/docs-kit/commit/a02fd521d8c3f2c973dedfcf4f749b2503ca56b5))


### Bug Fixes

* in_range triggers shellcheck SC2015 on runner (A && B || C form) ([1b0efca](https://github.com/ldelarue/docs-kit/commit/1b0efca8338f265ba14494c63efc4e5a0cf7a633))


### Documentation

* formal tone; publish: maintain a movable latest branch + document as default uv ref ([c6f6ee2](https://github.com/ldelarue/docs-kit/commit/c6f6ee2d934074ec3f7b553d751122e9464866ca))
* install matrix (uv git-pins / clone / local build), release flow; drop ROADMAP.md ([295b7c9](https://github.com/ldelarue/docs-kit/commit/295b7c90c20a0a84603936652eac911ceeedcf6d))
* rewrite README: uv CLI install, version-locked shared tasks (.docs-kit shim), local clone, full CLI usage reference ([4b4600c](https://github.com/ldelarue/docs-kit/commit/4b4600c829f34fc280b3ac8e7859f99af2e4bb10))
