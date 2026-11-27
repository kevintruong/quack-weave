//! Configuration for an immutable Ladybug database object.
use duckdb_neo::{Result, error::Error};
use serde::{Deserialize, Serialize};

use super::ConfigInput;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CloudStorage {
    S3,
    Gcs,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct CloudSource {
    pub storage: CloudStorage,
    pub uri: String,
    pub secret: String,
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
        let secret = input
            .secret
            .filter(|name| !name.trim().is_empty() && !name.contains('\0'))
            .ok_or_else(|| {
                Error::invalid_input(
                    "QW_CONFIG: A Ladybug cloud graph requires a nonempty secret name",
                )
            })?;
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
    let key_part = |part: &str| {
        !matches!(part, "" | "." | "..")
            && part.bytes().all(|byte| {
                byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-' | b'~')
            })
    };
    // Accept one unambiguous spelling. The same URI goes to credential lookup
    // and Ladybug without decoding, normalization or interpolation of URL options.
    if !bucket.split('.').all(bucket_label)
        || !key.ends_with(".lbdb")
        || !key.split('/').all(key_part)
    {
        return Err(invalid());
    }
    Ok(storage)
}

#[cfg(test)]
mod tests {
    use super::*;

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
            assert_eq!(source.secret, "named_secret");
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
