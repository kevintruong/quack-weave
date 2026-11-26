//! Read-only Cypher over AuraDB's Query API v2.

use std::{
    env,
    time::{Duration, Instant},
};

use base64::{Engine as _, engine::general_purpose::STANDARD};
use duckdb_neo::connection::Context;
use rusty_quack_core::qw_query::{
    BackendError, BatchReader, ColumnSpec, GraphParameter, ReadBackend, ReadSession,
    RemoteCredential, RemoteSource, ScanLimits,
};
use serde_json::{Map, Value, json};
use ureq::http::header::{ACCEPT, ACCEPT_ENCODING, AUTHORIZATION, CONTENT_TYPE, HeaderValue};

use crate::{cypher_read::admit, neo4j_secret};

mod rows;

const TYPED_JSON: &str = "application/vnd.neo4j.query.v1.2";
const AURA_DOMAIN: &str = ".databases.neo4j.io";

pub(crate) struct Neo4jBackend;

#[derive(Debug, PartialEq, Eq)]
enum Origin {
    Aura(String),
    #[cfg(feature = "neo4j-test-fixture")]
    Fixture(u16),
}

impl Origin {
    fn parse(value: &str) -> Option<Self> {
        let authority = value.strip_prefix("https://")?;
        let host = authority.strip_suffix(":443").unwrap_or(authority);
        if host.strip_suffix(AURA_DOMAIN).is_some_and(|instance| {
            !instance.is_empty()
                && !instance.starts_with('-')
                && !instance.ends_with('-')
                && instance
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
        }) {
            return Some(Self::Aura(host.to_owned()));
        }
        #[cfg(feature = "neo4j-test-fixture")]
        if let Some(port) = authority.strip_prefix("127.0.0.1:")
            && port.bytes().all(|byte| byte.is_ascii_digit())
            && let Ok(port) = port.parse::<u16>()
            && port != 0
        {
            return Some(Self::Fixture(port));
        }
        None
    }
}

enum CredentialReference<'a> {
    Environment(String),
    Secret(&'a str),
}

enum Authorization {
    Environment(String),
    Secret(HeaderValue),
}

impl Authorization {
    fn header(self) -> Result<HeaderValue, BackendError> {
        match self {
            Self::Environment(prefix) => {
                let read = |name| {
                    env::var(format!("{prefix}_{name}"))
                        .ok()
                        .filter(|value| !value.is_empty())
                        .ok_or(BackendError::RemoteAuth)
                };
                let username = read("USERNAME")?;
                if username.contains(':') {
                    return Err(BackendError::RemoteAuth);
                }
                basic_authorization(&username, &read("PASSWORD")?)
            }
            Self::Secret(header) => Ok(header),
        }
    }
}

fn basic_authorization(username: &str, password: &str) -> Result<HeaderValue, BackendError> {
    let mut header = HeaderValue::from_str(&format!(
        "Basic {}",
        STANDARD.encode(format!("{username}:{password}"))
    ))
    .map_err(|_| BackendError::RemoteAuth)?;
    header.set_sensitive(true);
    Ok(header)
}

struct Endpoint {
    query_url: String,
    origin: Origin,
}

impl Endpoint {
    fn configured(source: &RemoteSource) -> Result<(Self, CredentialReference<'_>), BackendError> {
        let origin = Origin::parse(&source.endpoint).ok_or(BackendError::RemoteConfig)?;
        if !source
            .database
            .starts_with(|c: char| c.is_ascii_alphanumeric())
            || source.database.eq_ignore_ascii_case("system")
            || !source
                .database
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.'))
        {
            return Err(BackendError::RemoteConfig);
        }
        let credential = match &source.credential {
            RemoteCredential::Environment(reference) => {
                #[cfg(feature = "neo4j-test-fixture")]
                if matches!(origin, Origin::Fixture(_)) && reference != "fixture" {
                    return Err(BackendError::RemoteConfig);
                }
                if reference.is_empty()
                    || !reference
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b == b'_')
                {
                    return Err(BackendError::RemoteConfig);
                }
                let prefix = format!("QW_NEO4J_{}", reference.to_ascii_uppercase());
                // Host-supplied references retain their exact environment origin pin.
                if env::var(format!("{prefix}_ENDPOINT")).ok().as_deref()
                    != Some(source.endpoint.as_str())
                {
                    return Err(BackendError::RemoteConfig);
                }
                CredentialReference::Environment(prefix)
            }
            RemoteCredential::Secret(name) => {
                #[cfg(feature = "neo4j-test-fixture")]
                if matches!(origin, Origin::Fixture(_))
                    && env::var("QW_NEO4J_FIXTURE_ENDPOINT").ok().as_deref()
                        != Some(source.endpoint.as_str())
                {
                    return Err(BackendError::RemoteConfig);
                }
                CredentialReference::Secret(name)
            }
        };
        Ok((
            Self {
                query_url: format!("{}/db/{}/query/v2", source.endpoint, source.database),
                origin,
            },
            credential,
        ))
    }

    fn secret_authorization(
        &self,
        context: &Context,
        name: &str,
    ) -> Result<HeaderValue, BackendError> {
        neo4j_secret::with_credentials(context, name, |origin, username, password| {
            if Origin::parse(origin).as_ref() != Some(&self.origin) || username.contains(':') {
                return None;
            }
            basic_authorization(username, password).ok()
        })
        .ok_or(BackendError::RemoteAuth)
    }

    fn agent(&self, timeout: Duration) -> Result<ureq::Agent, BackendError> {
        let config = ureq::Agent::config_builder()
            .https_only(true)
            .proxy(None)
            .max_redirects(0)
            .http_status_as_error(false)
            .timeout_global(Some(timeout));
        let config = match self.origin {
            Origin::Aura(_) => config,
            #[cfg(feature = "neo4j-test-fixture")]
            Origin::Fixture(_) => {
                use ureq::tls::{Certificate, RootCerts, TlsConfig};
                let path = env::var_os("QW_NEO4J_FIXTURE_CA").ok_or(BackendError::RemoteConfig)?;
                let pem = std::fs::read(path).map_err(|_| BackendError::RemoteConfig)?;
                let ca = Certificate::from_pem(&pem).map_err(|_| BackendError::RemoteConfig)?;
                config.tls_config(
                    TlsConfig::builder()
                        .root_certs(RootCerts::new_with_certs(&[ca]))
                        .build(),
                )
            }
        };
        Ok(ureq::Agent::new_with_config(config.build()))
    }
}

impl ReadBackend for Neo4jBackend {
    fn validate_remote(&self, source: &RemoteSource) -> Result<(), BackendError> {
        Endpoint::configured(source).map(|_| ())
    }

    fn open_remote(
        &self,
        context: &Context,
        source: &RemoteSource,
        limits: &ScanLimits,
        schema: &[ColumnSpec],
    ) -> Result<Box<dyn ReadSession>, BackendError> {
        let (endpoint, reference) = Endpoint::configured(source)?;
        let authorization = match reference {
            CredentialReference::Environment(prefix) => Authorization::Environment(prefix),
            CredentialReference::Secret(name) => {
                Authorization::Secret(endpoint.secret_authorization(context, name)?)
            }
        };
        Ok(Box::new(Session {
            endpoint,
            authorization,
            timeout: Duration::from_millis(limits.timeout_ms),
            max_bytes: limits.max_response_bytes,
            schema: schema.to_vec(),
        }))
    }
}

struct Session {
    endpoint: Endpoint,
    authorization: Authorization,
    timeout: Duration,
    max_bytes: usize,
    schema: Vec<ColumnSpec>,
}

fn transport_error(error: ureq::Error) -> BackendError {
    match error {
        ureq::Error::Timeout(_) => BackendError::Timeout,
        ureq::Error::Io(error) if error.kind() == std::io::ErrorKind::TimedOut => {
            BackendError::Timeout
        }
        ureq::Error::BodyExceedsLimit(_) => BackendError::ResponseBudget,
        _ => BackendError::RemoteTransport,
    }
}

fn bind_parameter(parameter: &GraphParameter) -> Result<Value, BackendError> {
    Ok(match parameter {
        GraphParameter::Null => json!({"$type": "Null", "_value": null}),
        GraphParameter::Boolean(value) => json!({"$type": "Boolean", "_value": value}),
        GraphParameter::Integer(value) => json!({"$type": "Integer", "_value": value.to_string()}),
        GraphParameter::Double(value) if value.is_finite() => {
            json!({"$type": "Float", "_value": value.to_string()})
        }
        GraphParameter::Text(value) => json!({"$type": "String", "_value": value}),
        _ => return Err(BackendError::Admission),
    })
}

impl ReadSession for Session {
    fn execute_with_params(
        self: Box<Self>,
        cypher: &str,
        params: &[(String, GraphParameter)],
    ) -> Result<Box<dyn BatchReader>, BackendError> {
        admit(cypher, |_| Ok(()))?;
        let mut bindings = Map::new();
        for (name, parameter) in params {
            if bindings
                .insert(name.clone(), bind_parameter(parameter)?)
                .is_some()
            {
                return Err(BackendError::Admission);
            }
        }
        let body = serde_json::to_vec(&json!({"statement": cypher, "parameters": bindings}))
            .map_err(|_| BackendError::Admission)?;
        // ureq's limit reports a full buffer as overflow even when the next byte is EOF.
        let probe_bytes = (self.max_bytes as u64)
            .checked_add(1)
            .ok_or(BackendError::ResponseBudget)?;
        let start = Instant::now();
        let agent = self.endpoint.agent(self.timeout)?;
        let response = agent
            .post(&self.endpoint.query_url)
            .header(AUTHORIZATION, self.authorization.header()?)
            .header(ACCEPT, TYPED_JSON)
            .header(ACCEPT_ENCODING, "identity")
            .header(CONTENT_TYPE, TYPED_JSON)
            .send(&body[..])
            .map_err(transport_error)?;
        match response.status().as_u16() {
            200 | 202 => (),
            401 | 403 => return Err(BackendError::RemoteAuth),
            _ => return Err(BackendError::RemoteTransport),
        }
        let typed = response
            .headers()
            .get(CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .and_then(|media_type| media_type.split(';').next())
            .is_some_and(|media_type| media_type.trim().eq_ignore_ascii_case(TYPED_JSON));
        let bytes = response
            .into_body()
            .into_with_config()
            .limit(probe_bytes)
            .read_to_vec()
            .map_err(transport_error)?;
        if bytes.len() > self.max_bytes {
            return Err(BackendError::ResponseBudget);
        }
        let result = rows::decode(self.schema, &bytes, typed)?;
        if start.elapsed() >= self.timeout {
            return Err(BackendError::Timeout);
        }
        Ok(Box::new(result))
    }
}

#[cfg(test)]
mod tests {
    use super::Origin;

    #[test]
    fn aura_origin_is_strict_and_normalizes_default_https_port() {
        let canonical = Origin::parse("https://demo.databases.neo4j.io").unwrap();
        assert_eq!(
            Origin::parse("https://demo.databases.neo4j.io:443"),
            Some(canonical)
        );
        assert_ne!(
            Origin::parse("https://demo.databases.neo4j.io"),
            Origin::parse("https://other.databases.neo4j.io")
        );
        for invalid in [
            "http://demo.databases.neo4j.io",
            "https://DEMO.databases.neo4j.io",
            "https://demo.databases.neo4j.io:444",
            "https://demo.databases.neo4j.io/",
            "https://demo.databases.neo4j.io?query",
            "https://demo.databases.neo4j.io#fragment",
            "https://demo.databases.neo4j.io.example",
            "https://user@demo.databases.neo4j.io",
        ] {
            assert!(Origin::parse(invalid).is_none(), "{invalid}");
        }
    }

    #[cfg(not(feature = "neo4j-test-fixture"))]
    #[test]
    fn production_rejects_the_loopback_fixture_origin() {
        assert!(Origin::parse("https://127.0.0.1:8443").is_none());
    }
}
