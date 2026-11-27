#include "duckdb/catalog/catalog_transaction.hpp"
#include "duckdb/main/capi_v2/capi_v2_internal.hpp"
#include "duckdb/main/client_context_state.hpp"
#include "duckdb/main/secret/secret_manager.hpp"

namespace {

struct SecretText {
	const char *data;
	size_t size;
};

struct CloudFields {
	SecretText key_id;
	SecretText secret;
	SecretText token;
	SecretText region;
};

using CloudVisitor = void (*)(void *, CloudFields);

using CreateScope = const void *(*)();
using DropScope = void (*)(const void *);
using ScopeVisitor = void (*)(void *, const void *);

class LadybugCloudScopeState final : public duckdb::ClientContextState {
public:
	LadybugCloudScopeState(CreateScope create, DropScope drop) : scope(create()), drop(drop) {
	}
	~LadybugCloudScopeState() override {
		if (scope) {
			drop(scope);
		}
	}

	const void *const scope;

private:
	const DropScope drop;
};

SecretText Field(const duckdb::KeyValueSecret &secret, const char *key) {
	auto entry = secret.secret_map.find(key);
	if (entry == secret.secret_map.end() || entry->second.IsNull() ||
	    entry->second.type() != duckdb::LogicalType::VARCHAR) {
		return {"", 0};
	}
	const auto &text = duckdb::StringValue::Get(entry->second);
	return {text.data(), text.size()};
}

bool MatchesObject(const duckdb::BaseSecret &secret, const duckdb::string &uri) {
	for (const auto &scope : secret.GetScope()) {
		if (scope == uri) {
			return true;
		}
		// Require a bucket and a complete prefix segment. DuckDB's default
		// scheme-only scope is too broad for a registered snapshot.
		const auto bucket_start = scope.find("://");
		if (bucket_start != duckdb::string::npos && !scope.empty() && scope.back() == '/' &&
		    uri.compare(0, scope.size(), scope) == 0) {
			const auto bucket_end = scope.find('/', bucket_start + 3);
			if (bucket_end != duckdb::string::npos && bucket_end > bucket_start + 3) {
				return true;
			}
		}
	}
	return false;
}

} // namespace

extern "C" bool qw_visit_ladybug_cloud_scope(duckdb_v2_context_handle handle, CreateScope create, DropScope drop,
                                             void *output, ScopeVisitor visit) noexcept {
	try {
		bool found = false;
		duckdb::capiv2::Convert(handle)->WithContext([&](duckdb::ClientContext &context) {
			auto state = context.registered_state->GetOrCreate<LadybugCloudScopeState>(
			    "quack_weave_ladybug_cloud_scope", create, drop);
			if (state->scope) {
				visit(output, state->scope);
				found = true;
			}
		});
		return found;
	} catch (...) {
		return false;
	}
}

extern "C" bool qw_visit_ladybug_cloud_secret(duckdb_v2_context_handle handle, const char *name,
                                              size_t name_size, const char *path, size_t path_size,
                                              bool gcs, void *state, CloudVisitor visit) noexcept {
	try {
		bool found = false;
		duckdb::capiv2::Convert(handle)->WithContext([&](duckdb::ClientContext &context) {
			auto &manager = duckdb::SecretManager::Get(context);
			auto entry = manager.GetSecretByName(duckdb::CatalogTransaction::GetSystemCatalogTransaction(context),
			                                     duckdb::string(name, name_size),
			                                     duckdb::SecretManager::CONNECTION_STORAGE_NAME);
			if (!entry || !entry->secret || entry->secret->GetType() != (gcs ? "gcs" : "s3") ||
			    !MatchesObject(*entry->secret, duckdb::string(path, path_size))) {
				return;
			}
			const auto *secret = dynamic_cast<const duckdb::KeyValueSecret *>(entry->secret.get());
			if (!secret) {
				return;
			}
			const CloudFields fields {Field(*secret, "key_id"), Field(*secret, "secret"),
			                          Field(*secret, "session_token"), Field(*secret, "region")};
			if (!fields.key_id.size || !fields.secret.size) {
				return;
			}
			visit(state, fields);
			found = true;
		});
		return found;
	} catch (...) {
		return false;
	}
}
