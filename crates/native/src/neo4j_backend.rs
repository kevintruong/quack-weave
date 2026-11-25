//! Read-only Cypher over AuraDB's Query API v2.

use std::{
    env,
    time::{Duration, Instant},
};

use base64::{Engine as _, engine::general_purpose::STANDARD};
use rusty_quack_core::qw_query::{
    BackendError, BatchReader, ColumnSpec, GraphParameter, ReadBackend, ReadSession, RemoteSource,
    ScanLimits,
};
use serde_json::{Map, Value, json};
use ureq::http::header::{ACCEPT, ACCEPT_ENCODING, AUTHORIZATION, CONTENT_TYPE, HeaderValue};

use crate::cypher_read::admit;

mod rows;

const TYPED_JSON: &str = "application/vnd.neo4j.query.v1.2";
const AURA_DOMAIN: &str = ".databases.neo4j.io";

pub(crate) struct Neo4jBackend;

enum EndpointPolicy {
    Aura,
    #[cfg(feature = "neo4j-test-fixture")]
    Fixture,
}

struct Endpoint {
    query_url: String,
    credential_prefix: String,
    policy: EndpointPolicy,
}

impl Endpoint {
    fn new(source: &RemoteSource) -> Result<Self, BackendError> {
        let authority = source
            .endpoint
            .strip_prefix("https://")
            .ok_or(BackendError::RemoteConfig)?;
        let host = authority.strip_suffix(":443").unwrap_or(authority);
        let policy = if host.strip_suffix(AURA_DOMAIN).is_some_and(|instance| {
            !instance.is_empty()
                && !instance.starts_with('-')
                && !instance.ends_with('-')
                && instance
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
        }) {
            EndpointPolicy::Aura
        } else {
            #[cfg(feature = "neo4j-test-fixture")]
            {
                if source.credential_ref != "fixture"
                    || authority
                        .strip_prefix("127.0.0.1:")
                        .and_then(|port| port.parse::<u16>().ok())
                        .is_none_or(|port| port == 0)
                {
                    return Err(BackendError::RemoteConfig);
                }
                EndpointPolicy::Fixture
            }
            #[cfg(not(feature = "neo4j-test-fixture"))]
            return Err(BackendError::RemoteConfig);
        };

        if !source
            .database
            .starts_with(|c: char| c.is_ascii_alphanumeric())
            || source.database.eq_ignore_ascii_case("system")
            || !source
                .database
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.'))
            || source.credential_ref.is_empty()
            || !source
                .credential_ref
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'_')
        {
            return Err(BackendError::RemoteConfig);
        }
        let credential_prefix = format!("QW_NEO4J_{}", source.credential_ref.to_ascii_uppercase());
        // Pin each host-supplied credential reference to an exact origin before lookup or send.
        if env::var(format!("{credential_prefix}_ENDPOINT"))
            .ok()
            .as_deref()
            != Some(source.endpoint.as_str())
        {
            return Err(BackendError::RemoteConfig);
        }
        Ok(Self {
            query_url: format!("{}/db/{}/query/v2", source.endpoint, source.database),
            credential_prefix,
            policy,
        })
    }

    fn authorization(&self) -> Result<HeaderValue, BackendError> {
        let read_credential = |name| {
            env::var(format!("{}_{name}", self.credential_prefix))
                .ok()
                .filter(|value| !value.is_empty())
                .ok_or(BackendError::RemoteAuth)
        };
        let user = read_credential("USERNAME")?;
        if user.contains(':') {
            return Err(BackendError::RemoteAuth);
        }
        let password = read_credential("PASSWORD")?;
        let mut header = HeaderValue::from_str(&format!(
            "Basic {}",
            STANDARD.encode(format!("{user}:{password}"))
        ))
        .map_err(|_| BackendError::RemoteAuth)?;
        header.set_sensitive(true);
        Ok(header)
    }

    fn agent(&self, timeout: Duration) -> Result<ureq::Agent, BackendError> {
        let config = ureq::Agent::config_builder()
            .https_only(true)
            .proxy(None)
            .max_redirects(0)
            .http_status_as_error(false)
            .timeout_global(Some(timeout));
        let config = match self.policy {
            EndpointPolicy::Aura => config,
            #[cfg(feature = "neo4j-test-fixture")]
            EndpointPolicy::Fixture => {
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
        Endpoint::new(source).map(|_| ())
    }

    fn open_remote(
        &self,
        source: &RemoteSource,
        limits: &ScanLimits,
        schema: &[ColumnSpec],
    ) -> Result<Box<dyn ReadSession>, BackendError> {
        Ok(Box::new(Session {
            endpoint: Endpoint::new(source)?,
            timeout: Duration::from_millis(limits.timeout_ms),
            max_bytes: limits.max_response_bytes,
            schema: schema.to_vec(),
        }))
    }
}

struct Session {
    endpoint: Endpoint,
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
            .header(AUTHORIZATION, self.endpoint.authorization()?)
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
