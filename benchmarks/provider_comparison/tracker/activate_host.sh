#!/usr/bin/env bash
# Actions' artifact transport strips executable modes.
set -euo pipefail
host="$PWD/build/benchmark-host"
chmod +x "$host/unittest" "$host/release/test/unittest"
case "$(uname -sm)" in
    'Linux aarch64') suffix=so ;;
    'Darwin arm64') suffix=dylib ;;
    *) exit 1 ;;
esac
test -f "$host/release/src/libduckdb.$suffix"
{
    echo "DUCKDB_LIB=$host/release/src/libduckdb.$suffix"
    echo "DUCKDB_UNITTEST=$host/unittest"
    echo "QW_DUCKDB_ARCHIVE_SHA256=$(cat "$host/upstream.sha256")"
} >> "$GITHUB_ENV"
