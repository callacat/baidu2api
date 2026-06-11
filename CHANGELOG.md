# Changelog

All notable changes to this project will be documented in this file. See [commit-and-tag-version](https://github.com/absolute-version/commit-and-tag-version) for commit guidelines.

## [1.4.1](https://github.com/callacat/baidu2api/compare/v1.4.0...v1.4.1) (2026-06-11)


### Bug Fixes

* inject SSE keepalive during deep thinking silent period to prevent stream timeout ([15205ff](https://github.com/callacat/baidu2api/commit/15205ff35c439dcaab5d6a85d986c6ba110e6351))

## [1.4.0](https://github.com/callacat/baidu2api/compare/v1.3.0...v1.4.0) (2026-06-11)


### Features

* admin panel force stream/non-stream override ([0439170](https://github.com/callacat/baidu2api/commit/043917076499e08bbf1334afc041efa66e4d863f))


### Bug Fixes

* end_turn check skipped after thinking chunks causing content truncation ([8294ae5](https://github.com/callacat/baidu2api/commit/8294ae5f1d55ba7384fc54466da6c0f49b66b84b))
* extract_content type safety - prevent crash on non-str returns ([4b3ad6d](https://github.com/callacat/baidu2api/commit/4b3ad6d1900b53b4da4fb0a35ef97eb03715f279))
* flush remaining SSE buffer after HTTP stream ends ([c9cf901](https://github.com/callacat/baidu2api/commit/c9cf901956ed78d0fba5f0e7d51865abc4fe4b01))
* handle Baidu API status>=1000 error, support new response format (generator.text) ([eeed8e5](https://github.com/callacat/baidu2api/commit/eeed8e5bb048407cb6a14e90f7c3018e94e26533))
* JSON mode format consistency - use JSON format for tool history injection ([2fc07e0](https://github.com/callacat/baidu2api/commit/2fc07e06d94417d3f397627a3914a099d4566147))
* JSON mode markdown block and greedy regex parsing ([a8433f8](https://github.com/callacat/baidu2api/commit/a8433f893dda7a9d02e8d3002a75c72ccaca39ae))
* prevent non-stream response from truncating SSE buffer flush ([25df8d4](https://github.com/callacat/baidu2api/commit/25df8d4278542de069355e80d2d57d9eda51a2ce))
* remove drain step, simplify to prevent stream truncation ([4ac78ba](https://github.com/callacat/baidu2api/commit/4ac78ba305b839806533fdc349a5d5d4528a74a1))
* SSE charset utf-8 + ensure_ascii to prevent UTF-8 byte splitting ([122e733](https://github.com/callacat/baidu2api/commit/122e73336285c5e1aa0964ff5f40096ccc8bb028))
* stream mode now internally uses non-stream + SSE wrapper ([3437d31](https://github.com/callacat/baidu2api/commit/3437d31d4fa16d041a1dfaa2fa37dc25208076de))
* stream truncation - don't break on end_turn ([b7b10d5](https://github.com/callacat/baidu2api/commit/b7b10d53dd2420705080bdb517d7c448f80668c5))
* streaming tool calls - add index field, separate content from tool_calls delta ([c9d6357](https://github.com/callacat/baidu2api/commit/c9d63573518392659cd906ab9756649dc1560e2b))

## [1.3.0] - 2026-05-19

### Added

- Web admin panel: force stream/non-stream override via configuration

### Fixed

- Support new Baidu API response format (generator.text) for content extraction
- extract_content type safety for non-str return values
- SSE charset utf-8 + ensure_ascii fixes for UTF-8 byte splitting
- Flush remaining SSE buffer after HTTP stream ends
- end_turn check skipped after thinking chunks causing content truncation
- Streaming tool calls: add index field, separate content from tool_calls delta
- Empty response auto-retry with token refresh on Baidu API rate limiting

## [1.2.2] - 2026-04-22

### Fixed

- JSON mode format consistency and markdown block parsing

## [1.2.1] - 2026-04-20

### Added

- Enhanced debug logging for Baidu API empty responses
- Improved extract_content to cover more data formats

## [1.2.0] - 2026-04-15

### Added

- Improved CI/CD: support Windows ARM64, Linux ARM64, macOS ARM64 builds

### Fixed

- CI workflow fixes for binary builds

## [1.1.0] - 2026-04-08

### Added

- Initial release with multi-model support
- Dual tool calling (XML + JSON)
- Web admin panel
- SSE streaming
- API Key authentication
- Docker support
