#include "duckdb/main/capi_v2/capi_v2_internal.hpp"
#include "duckdb/main/secret/secret_manager.hpp"

namespace duckdb {
namespace {

constexpr const char *NEO4J_SECRET_TYPE = "quack_weave_neo4j";
constexpr const char *NEO4J_SECRET_PROVIDER = "config";

const Value &RequiredOption(const CreateSecretInput &input, const char *key, const char *label) {
	auto entry = input.options.find(key);
	if (entry == input.options.end() || entry->second.IsNull() || StringValue::Get(entry->second).empty()) {
		throw InvalidInputException("QW_CONFIG: Neo4j secret requires a nonempty %s", label);
	}
	return entry->second;
}

unique_ptr<BaseSecret> CreateNeo4jConfigSecret(ClientContext &, CreateSecretInput &input) {
	const auto &origin = RequiredOption(input, "origin", "ORIGIN");
	const auto &username = RequiredOption(input, "username", "USERNAME");
	const auto &password = RequiredOption(input, "password", "PASSWORD");
	if (StringValue::Get(username).find(':') != string::npos) {
		throw InvalidInputException("QW_CONFIG: Neo4j secret usernames must exclude colons");
	}

	auto secret = make_uniq<KeyValueSecret>(input.scope, input.type, input.provider, input.name);
	secret->secret_map["origin"] = origin;
	secret->secret_map["username"] = username;
	secret->secret_map["password"] = password;
	secret->redact_keys.insert("username");
	secret->redact_keys.insert("password");
	return secret;
}

} // namespace
} // namespace duckdb

extern "C" bool qw_register_neo4j_secret(duckdb_v2_factory_handle handle) noexcept {
	try {
		auto &manager = duckdb::SecretManager::Get(duckdb::capiv2::Convert(handle)->GetDatabase());
		duckdb::SecretType type;
		type.name = duckdb::NEO4J_SECRET_TYPE;
		type.deserializer = duckdb::KeyValueSecret::Deserialize<duckdb::KeyValueSecret>;
		type.default_provider = duckdb::NEO4J_SECRET_PROVIDER;
		type.extension = "quack_weave";
		manager.RegisterSecretType(type);

		duckdb::CreateSecretFunction config;
		config.secret_type = duckdb::NEO4J_SECRET_TYPE;
		config.provider = duckdb::NEO4J_SECRET_PROVIDER;
		config.function = duckdb::CreateNeo4jConfigSecret;
		for (const auto *key : {"origin", "username", "password"}) {
			config.named_parameters[key] = duckdb::LogicalType::VARCHAR;
		}
		manager.RegisterSecretFunction(std::move(config), duckdb::OnCreateConflict::ERROR_ON_CONFLICT);
		return true;
	} catch (...) {
		return false;
	}
}
