//! Configuration for an immutable Ladybug database object.
use duckdb_neo::{Result, error::Error};
use serde::{Deserialize, Serialize};

use super::ConfigInput;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CloudStorage {
    S3,
    Gcs,
    Xet,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct CloudSource {
    pub storage: CloudStorage,
    pub uri: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub secret: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub(super) struct CloudConfig {
    pub(super) alias: String,
    pub(super) source: CloudSource,
    pub(super) timeout_ms: Option<u64>,
    pub(super) max_batch_bytes: Option<usize>,
}

impl CloudConfig {
    pub(super) fn from_input(input: ConfigInput) -> Result<Self> {
        let storage = snapshot_storage(&input.path)?;
        let secret = match (storage, input.secret) {
            (CloudStorage::Xet, None) => None,
            (CloudStorage::Xet, Some(_)) => {
                return Err(Error::invalid_input(
                    "QW_CONFIG: Public Hugging Face Xet snapshots do not accept a secret",
                ));
            }
            (_, Some(name)) if !name.trim().is_empty() && !name.contains('\0') => Some(name),
            _ => {
                return Err(Error::invalid_input(
                    "QW_CONFIG: A Ladybug cloud graph requires a nonempty secret name",
                ));
            }
        };
        Ok(Self {
            alias: input.alias,
            source: CloudSource {
                storage,
                uri: input.path,
                secret,
            },
            timeout_ms: input.timeout_ms,
            max_batch_bytes: input.max_batch_bytes,
        })
    }
}

fn snapshot_storage(uri: &str) -> Result<CloudStorage> {
    let invalid = || Error::invalid_input("QW_CONFIG: Invalid Ladybug cloud snapshot URI");
    let (scheme, object) = uri.split_once("://").ok_or_else(invalid)?;
    let storage = match scheme {
        "s3" => CloudStorage::S3,
        "gs" | "gcs" => CloudStorage::Gcs,
        "xet" if valid_xet_snapshot(object) => return Ok(CloudStorage::Xet),
        "xet" => {
            return Err(Error::invalid_input(
                "QW_CONFIG: Expected a revision-pinned public Hugging Face Xet snapshot URI",
            ));
        }
        _ => {
            return Err(Error::invalid_input(
                "QW_CONFIG: Unsupported Ladybug cloud storage scheme",
            ));
        }
    };
    let (bucket, key) = object.split_once('/').ok_or_else(invalid)?;
    let bucket_label = |label: &str| {
        let alnum = |byte: &u8| byte.is_ascii_lowercase() || byte.is_ascii_digit();
        label.as_bytes().first().is_some_and(alnum)
            && label.as_bytes().last().is_some_and(alnum)
            && label.bytes().all(|byte| alnum(&byte) || byte == b'-')
    };
    // Accept one unambiguous spelling. The same URI goes to credential lookup
    // and Ladybug without decoding, normalization or interpolation of URL options.
    if !bucket.split('.').all(bucket_label) || !valid_snapshot_path(key) {
        return Err(invalid());
    }
    Ok(storage)
}

fn valid_snapshot_path(path: &str) -> bool {
    path.ends_with(".lbdb")
        && path.split('/').all(|part| {
            !matches!(part, "" | "." | "..")
                && part.bytes().all(|byte| {
                    byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-' | b'~')
                })
        })
}

fn valid_xet_snapshot(object: &str) -> bool {
    let Some(dataset) = object.strip_prefix("datasets/") else {
        return false;
    };
    let mut parts = dataset.splitn(4, '/');
    let (Some(owner), Some(repo), Some(revision), Some(path)) =
        (parts.next(), parts.next(), parts.next(), parts.next())
    else {
        return false;
    };
    let valid_repo_part = |part: &str| {
        !matches!(part, "" | "." | "..")
            && part
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    };
    valid_repo_part(owner)
        && valid_repo_part(repo)
        && revision.len() == 40
        && revision.bytes().all(|byte| byte.is_ascii_hexdigit())
        && valid_snapshot_path(path)
}

#[cfg(test)]
mod tests {
    use super::*;

    const PINNED_XET: &str = "xet://datasets/example-owner/example_repo/0123456789abcdef0123456789abcdef01234567/nested/demo.lbdb";

    #[test]
    fn keeps_the_public_xet_uri_without_a_secret() {
        let input =
            super::super::parse_config(&format!(r#"{{"alias":"cloud","path":"{PINNED_XET}"}}"#))
                .unwrap();
        let source = CloudConfig::from_input(input).unwrap().source;
        assert_eq!(source.storage, CloudStorage::Xet);
        assert_eq!(source.uri, PINNED_XET);
        assert!(source.secret.is_none());
        let serialized = serde_json::to_value(&source).unwrap();
        assert!(serialized.get("secret").is_none());
        let restored: CloudSource = serde_json::from_value(serialized).unwrap();
        assert_eq!(restored.uri, PINNED_XET);
    }

    #[test]
    fn rejects_mutable_or_ambiguous_xet_uris_and_explicit_secrets() {
        for uri in [
            PINNED_XET.replace("0123456789abcdef0123456789abcdef01234567", "main"),
            PINNED_XET.replace("0123456789abcdef0123456789abcdef01234567", "0123456"),
            PINNED_XET.replace(
                "0123456789abcdef0123456789abcdef01234567",
                "0123456789abcdef0123456789abcdef0123456g",
            ),
            PINNED_XET.replace("/datasets/", "/models/"),
            PINNED_XET.replace("xet://", "xet://huggingface.co/"),
            PINNED_XET.replace("example_repo/", "example_repo/resolve/"),
            PINNED_XET.replace("example_repo/", "example_repo//"),
            PINNED_XET.replace("example-owner/", "example%2Downer/"),
            PINNED_XET.replace("nested/", "nested/../"),
            format!("{PINNED_XET}?download=true"),
            format!("{PINNED_XET}#fragment"),
        ] {
            assert!(snapshot_storage(&uri).is_err(), "{uri}");
        }
        for secret in ["quack_test_secret", ""] {
            let input = super::super::parse_config(&format!(
                r#"{{"alias":"cloud","path":"{PINNED_XET}","secret":"{secret}"}}"#
            ))
            .unwrap();
            let err = CloudConfig::from_input(input).unwrap_err();
            assert!(
                err.to_string()
                    .contains("Public Hugging Face Xet snapshots do not accept a secret")
            );
        }
    }

    #[test]
    fn keeps_the_uri_used_for_secret_lookup_and_attach() {
        for (scheme, expected) in [
            ("s3", CloudStorage::S3),
            ("gs", CloudStorage::Gcs),
            ("gcs", CloudStorage::Gcs),
        ] {
            let uri = format!("{scheme}://example.graphs/Graphs/immutable-1.lbdb");
            let input = super::super::parse_config(&format!(
                r#"{{"alias":"cloud","path":"{uri}","secret":"named_secret"}}"#
            ))
            .unwrap();
            let source = CloudConfig::from_input(input).unwrap().source;
            assert_eq!(source.storage, expected);
            assert_eq!(source.uri, uri);
            assert_eq!(source.secret.as_deref(), Some("named_secret"));
        }
    }

    #[test]
    fn rejects_ambiguous_or_unqualified_object_paths() {
        for uri in [
            "az://example/graph.lbdb",
            "abfss://container@example/graph.lbdb",
            "s3://someone@example/graph.lbdb",
            "s3://example..com/graph.lbdb",
            "s3://example:9443/graph.lbdb",
            "s3://example//graph.lbdb",
            "s3://example/../graph.lbdb",
            "s3://example/%2E%2E/graph.lbdb",
            "s3://example/graph.lbdb?token=not-a-secret",
            "gs://example/graph.lbdb#object",
            "gs://example/data.parquet",
        ] {
            assert!(snapshot_storage(uri).is_err(), "{uri}");
        }
    }
}
