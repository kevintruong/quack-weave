.DEFAULT_GOAL := native

.PHONY: clean clean_all native native-release native-deps native-test
.PHONY: native-stabilization-test native-stabilization-test-prebuilt public-client-test public-client-test-prebuilt
.PHONY: native-provider-test native-neo4j-tls-test

PROJ_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

EXTENSION_NAME ?= rusty_quack

# Mark the extension as C_STRUCT_UNSTABLE: DuckDB 2.x requires the _init_c_api_v2 entrypoint.
# Binaries load only in the exact TARGET_DUCKDB_VERSION, not in newer DuckDB releases.
USE_UNSTABLE_C_API=1
CAPI_VERSION=2

# Target DuckDB version
TARGET_DUCKDB_VERSION=v2.0.1

ifeq ($(or $(CI_EXTENSION_NAME),$(EXTENSION_NAME)),quack_weave)
.PHONY: configure_ci release test_release community-deps
COMMUNITY_ARTIFACT := build/release/extension/quack_weave/quack_weave.duckdb_extension
COMMUNITY_TOOLS := $(abspath build/deps/gql-antlr)
COMMUNITY_PYTHON ?= $(or $(wildcard /opt/python/cp312-cp312/bin/python),python3)
COMMUNITY_DUCKDB := $(COMMUNITY_TOOLS)/duckdb-cli-$(DUCKDB_PLATFORM)/duckdb
COMMUNITY_LBUG := $(COMMUNITY_TOOLS)/ladybug-cli-$(DUCKDB_PLATFORM)/lbug
COMMUNITY_GRAPH := $(abspath build/distribution-fixture/$(DUCKDB_PLATFORM).lbdb)
ifeq ($(shell uname -s),Linux)
export OPENSSL_LIB_DIR := $(COMMUNITY_TOOLS)/openssl-static
endif

configure_ci:
ifeq ($(LINUX_CI_IN_DOCKER),0)
	$(COMMUNITY_PYTHON) -B scripts/prepare_distribution_deps.py $(DUCKDB_PLATFORM) --clients-only
	$(COMMUNITY_PYTHON) -B test/cypher_acceptance.py --duckdb '$(COMMUNITY_DUCKDB)' --lbug '$(COMMUNITY_LBUG)' --prepare-release-fixture '$(COMMUNITY_GRAPH)'
endif

community-deps: native-deps
	$(COMMUNITY_PYTHON) -B scripts/prepare_distribution_deps.py $(DUCKDB_PLATFORM)

release: community-deps
	$(call package_native,$(NATIVE_CARGO_DIR),--release,release,$(COMMUNITY_ARTIFACT))
	$(call check_community_release)

test_release:
	$(call check_community_release)

else
all: configure debug

# Include makefiles from DuckDB
-include extension-ci-tools/makefiles/c_api_extensions/base.Makefile
-include extension-ci-tools/makefiles/c_api_extensions/rust.Makefile

# Build workspace libraries rather than the CI tools' Wasm example target.
IS_EXAMPLE=
ifneq ($(DUCKDB_WASM_PLATFORM),)
	TARGET_INFO=--target $(TARGET) --package rusty_quack_wasm
else
	TARGET_INFO+=--package rusty_quack --no-default-features --features template-compat
endif

configure: venv platform extension_version

debug: build_extension_library_debug build_extension_with_metadata_debug
release: build_extension_library_release build_extension_with_metadata_release

test: test_debug
test_debug: test_extension_debug
test_release: test_extension_release

clean: clean_build clean_rust
clean_all: clean_configure clean
endif

# Native packages with pinned vendor archives.
NATIVE_EXTENSION_VERSION := v0.2.0
NATIVE_HOST := $(shell uname -s):$(shell uname -m)
ifeq ($(NATIVE_HOST),Linux:aarch64)
NATIVE_TARGET := aarch64-unknown-linux-gnu
NATIVE_PLATFORM := linux_arm64
NATIVE_SUFFIX := so
else ifeq ($(NATIVE_HOST),Linux:x86_64)
NATIVE_TARGET := x86_64-unknown-linux-gnu
NATIVE_PLATFORM := linux_amd64
NATIVE_SUFFIX := so
else ifeq ($(NATIVE_HOST),Darwin:arm64)
NATIVE_TARGET := aarch64-apple-darwin
NATIVE_PLATFORM := osx_arm64
NATIVE_SUFFIX := dylib
endif
NATIVE_LIBRARY := librusty_quack.$(NATIVE_SUFFIX)
CARGO_BUILD_ROOT := $(if $(CARGO_TARGET_DIR),$(CARGO_TARGET_DIR),target)
NATIVE_CARGO_DIR ?= $(CARGO_BUILD_ROOT)/native
NATIVE_TLS_CARGO_DIR ?= $(CARGO_BUILD_ROOT)/native-test-tls
NATIVE_DEBUG_ARTIFACT ?= build/native/debug/extension/quack_weave/quack_weave.duckdb_extension
NATIVE_RELEASE_ARTIFACT ?= build/native/release/extension/quack_weave/quack_weave.duckdb_extension
NEO4J_TLS_TEST_ARTIFACT := build/native/test-tls/extension/quack_weave/quack_weave.duckdb_extension

PYTHON_BIN ?= $(or $(COMMUNITY_PYTHON),python3)
DUCKDB ?= duckdb
LBUG ?= lbug
ifneq ($(wildcard build/benchmark-host/release/src/libduckdb.$(NATIVE_SUFFIX)),)
DUCKDB_UNITTEST ?= build/benchmark-host/unittest
DUCKDB_LIB ?= build/benchmark-host/release/src/libduckdb.$(NATIVE_SUFFIX)
else
DUCKDB_UNITTEST ?= build/duckdb-v2.0.1/test/unittest
DUCKDB_LIB ?= build/duckdb-v2.0.1/src/libduckdb.$(NATIVE_SUFFIX)
endif
STABILIZATION_REPORT_DIR ?= build/stabilization-reports

native-deps:
	$(PYTHON_BIN) -B scripts/prepare_ladybug_deps.py
	$(PYTHON_BIN) -B scripts/prepare_gql_deps.py

define build_native
	@test -n '$(NATIVE_TARGET)' || { echo 'Unsupported native build host $(NATIVE_HOST)' >&2; exit 1; }
	@test -z '$(DUCKDB_PLATFORM)' || test '$(DUCKDB_PLATFORM)' = '$(NATIVE_PLATFORM)' || { echo 'DuckDB platform $(DUCKDB_PLATFORM) does not match native host $(NATIVE_HOST)' >&2; exit 1; }
	cargo build --locked --package rusty_quack --target $(NATIVE_TARGET) --target-dir '$(1)' $(2)
endef

define package_native
	$(call build_native,$(1),$(2) $(if $(5),--features '$(5)'))
	$(PYTHON_BIN) -B scripts/package_native.py '$(1)/$(NATIVE_TARGET)/$(3)/$(NATIVE_LIBRARY)' '$(4)' $(TARGET_DUCKDB_VERSION) $(NATIVE_PLATFORM) $(NATIVE_EXTENSION_VERSION)
endef

define check_native
	QUACK_WEAVE_TEST_ARTIFACT='$(1)' $(PYTHON_BIN) -B test/native_package_test.py
	$(PYTHON_BIN) -B test/cypher_acceptance.py --duckdb '$(or $(2),$(DUCKDB))' --lbug '$(or $(3),$(LBUG))' --extension '$(1)'
	$(PYTHON_BIN) -B test/gql_bind_test.py --duckdb '$(or $(2),$(DUCKDB))' --lbug '$(or $(3),$(LBUG))' --extension '$(1)'
	$(PYTHON_BIN) -B test/gql_acceptance.py --duckdb '$(or $(2),$(DUCKDB))' --lbug '$(or $(3),$(LBUG))' --extension '$(1)'
endef

ifeq ($(LINUX_CI_IN_DOCKER),1)
define check_community_release
	QUACK_WEAVE_TEST_ARTIFACT='$(COMMUNITY_ARTIFACT)' $(COMMUNITY_PYTHON) -B test/native_package_test.py
	$(COMMUNITY_PYTHON) -B test/cypher_acceptance.py --duckdb '$(COMMUNITY_DUCKDB)' --extension '$(COMMUNITY_ARTIFACT)' --release-fixture '$(COMMUNITY_GRAPH)'
endef
else
define check_community_release
	$(call check_native,$(COMMUNITY_ARTIFACT),$(COMMUNITY_DUCKDB),$(COMMUNITY_LBUG))
endef
endif

native:
	$(call package_native,$(NATIVE_CARGO_DIR),,debug,$(NATIVE_DEBUG_ARTIFACT))

native-release:
	$(call package_native,$(NATIVE_CARGO_DIR),--release,release,$(NATIVE_RELEASE_ARTIFACT))

native-provider-test: native-release
	$(call build_native,$(NATIVE_CARGO_DIR),--release --example relate_fixture)
	$(PYTHON_BIN) -B test/relate/run.py --duckdb-unittest '$(DUCKDB_UNITTEST)' --fixture-builder '$(NATIVE_CARGO_DIR)/$(NATIVE_TARGET)/release/examples/relate_fixture' --extension '$(NATIVE_RELEASE_ARTIFACT)' --lbug '$(LBUG)'
	$(MAKE) native-neo4j-tls-test

native-neo4j-tls-test:
	$(call package_native,$(NATIVE_TLS_CARGO_DIR),,debug,$(NEO4J_TLS_TEST_ARTIFACT),neo4j-test-fixture)
	$(PYTHON_BIN) -B test/neo4j/run.py --duckdb-unittest '$(DUCKDB_UNITTEST)' --extension '$(NEO4J_TLS_TEST_ARTIFACT)'

native-test: native native-release
	$(call check_native,$(NATIVE_DEBUG_ARTIFACT))
	$(call check_native,$(NATIVE_RELEASE_ARTIFACT))

public-client-test: native-release
public-client-test public-client-test-prebuilt:
	$(PYTHON_BIN) -B test/public_client/run.py --duckdb-unittest '$(DUCKDB_UNITTEST)' --duckdb-library '$(DUCKDB_LIB)' --lbug '$(LBUG)' --extension '$(NATIVE_RELEASE_ARTIFACT)'

stabilization_slt = $(PYTHON_BIN) -B test/stabilization/run_sqllogictest.py --duckdb-unittest '$(DUCKDB_UNITTEST)' --lbug '$(LBUG)'
stabilization_observer = $(PYTHON_BIN) -B test/stabilization/run_observer_audit.py --duckdb-unittest '$(DUCKDB_UNITTEST)' --duckdb-library '$(DUCKDB_LIB)' --lbug '$(LBUG)' --extension '$(NATIVE_RELEASE_ARTIFACT)' --report-dir '$(STABILIZATION_REPORT_DIR)/observer' $(if $(OBSERVER_TEST_DIR),--observer-test-dir '$(OBSERVER_TEST_DIR)')

define record_stabilization
	$(2) > '$(STABILIZATION_REPORT_DIR)/$(1).log' 2>&1 || { qw_gate_exit=$$?; cat '$(STABILIZATION_REPORT_DIR)/$(1).log' >&2; exit $$qw_gate_exit; }
	@cat '$(STABILIZATION_REPORT_DIR)/$(1).log'
endef

native-stabilization-test: native native-release
native-stabilization-test native-stabilization-test-prebuilt:
	mkdir -p '$(STABILIZATION_REPORT_DIR)'
	$(call record_stabilization,native-debug,$(stabilization_slt) --extension '$(NATIVE_DEBUG_ARTIFACT)')
	$(call record_stabilization,native-release,$(stabilization_slt) --extension '$(NATIVE_RELEASE_ARTIFACT)')
	$(call record_stabilization,observer,$(stabilization_observer))
	$(PYTHON_BIN) -B test/stabilization/check_coverage.py --report-dir '$(STABILIZATION_REPORT_DIR)'
