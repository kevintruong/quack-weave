.DEFAULT_GOAL := mvp1

.PHONY: clean clean_all mvp1 mvp1-release mvp1-deps mvp1-test

PROJ_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

EXTENSION_NAME=rusty_quack

# Mark the extension as C_STRUCT_UNSTABLE: DuckDB 2.x requires the _init_c_api_v2 entrypoint.
# Binaries load only in the exact TARGET_DUCKDB_VERSION, not in newer DuckDB releases.
USE_UNSTABLE_C_API=1
CAPI_VERSION=2

# Target DuckDB version
TARGET_DUCKDB_VERSION=v2.0.1

all: configure debug

# Include makefiles from DuckDB
-include extension-ci-tools/makefiles/c_api_extensions/base.Makefile
-include extension-ci-tools/makefiles/c_api_extensions/rust.Makefile

# Build workspace libraries rather than the CI tools' Wasm example target.
IS_EXAMPLE=
ifneq ($(DUCKDB_WASM_PLATFORM),)
	TARGET_INFO=--target $(TARGET) --package rusty_quack_wasm
else
	TARGET_INFO+=--package rusty_quack --features template-compat
endif

configure: venv platform extension_version

debug: build_extension_library_debug build_extension_with_metadata_debug
release: build_extension_library_release build_extension_with_metadata_release

test: test_debug
test_debug: test_extension_debug
test_release: test_extension_release

clean: clean_build clean_rust
clean_all: clean_configure clean

# MVP1 packages the native macOS arm64 build without the template CI tooling.
MVP1_DUCKDB_VERSION := v2.0.1
MVP1_EXTENSION_VERSION := v0.1.0
MVP1_TARGET := aarch64-apple-darwin
MVP1_CARGO_DIR := $(if $(CARGO_TARGET_DIR),$(CARGO_TARGET_DIR),target)
MVP1_DEBUG_ARTIFACT := build/debug/extension/quack_weave/quack_weave.duckdb_extension
MVP1_RELEASE_ARTIFACT := build/release/extension/quack_weave/quack_weave.duckdb_extension

PYTHON_BIN ?= python3
DUCKDB ?= duckdb
LBUG ?= lbug

mvp1-deps:
	$(PYTHON_BIN) scripts/prepare_mvp1_deps.py

define make_mvp1
	@test "$$(uname -s):$$(uname -m)" = "Darwin:arm64" || { echo 'MVP1 builds on macOS arm64.' >&2; exit 1; }
	cargo build --locked --package rusty_quack --target $(MVP1_TARGET) $(1)
	$(PYTHON_BIN) scripts/package_mvp1.py '$(MVP1_CARGO_DIR)/$(MVP1_TARGET)/$(2)/librusty_quack.dylib' '$(3)' $(MVP1_DUCKDB_VERSION) osx_arm64 $(MVP1_EXTENSION_VERSION)
endef

mvp1:
	$(call make_mvp1,,debug,$(MVP1_DEBUG_ARTIFACT))

mvp1-release:
	$(call make_mvp1,--release,release,$(MVP1_RELEASE_ARTIFACT))

mvp1-test: mvp1
	QUACK_WEAVE_TEST_ARTIFACT='$(MVP1_DEBUG_ARTIFACT)' $(PYTHON_BIN) test/native_package_test.py
	$(PYTHON_BIN) test/mvp1_acceptance.py --duckdb '$(DUCKDB)' --lbug '$(LBUG)' --extension '$(MVP1_DEBUG_ARTIFACT)'
