# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased] - TBD

### Fixed

- **Non-stream response drain bug**: `_non_stream_response` now uses `__anext__()` + drain pattern
  instead of `async for + break`, preventing `aclose()` from truncating the generator epilogue
  and losing buffered SSE events. Fixes intermittent empty content in non-stream mode.

### Changed

- **GitHub Workflow**: Removed Docker Hub push (fork-specific). Only push to GHCR.
  Added `provenance: false`/`sbom: false` to avoid permission errors.
  Added automatic orphan image cleanup (keep 3 latest).

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
