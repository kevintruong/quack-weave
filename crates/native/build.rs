use std::env;
use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::process::Command;

fn main() {
    if env::var_os("CARGO_FEATURE_TEMPLATE_COMPAT").is_some() {
        return;
    }

    let manifest_dir = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap());
    let pinned = manifest_dir.join("../../build/deps/ladybug-0.22.3");
    let native = manifest_dir.join("src/ladybug_admission.cpp");
    let source = configured("LADYBUG_SOURCE_DIR", pinned.join("ladybug-0.22.3"));
    let library = configured("LADYBUG_LIB_DIR", pinned.join("static"));
    let ssl = env::var_os("OPENSSL_LIB_DIR")
        .map(PathBuf::from)
        .or_else(homebrew_openssl_lib)
        .expect("Set OPENSSL_LIB_DIR to the directory containing OpenSSL 3 static archives");
    let out = PathBuf::from(env::var_os("OUT_DIR").unwrap());

    for key in [
        "CXX",
        "AR",
        "LADYBUG_SOURCE_DIR",
        "LADYBUG_LIB_DIR",
        "OPENSSL_LIB_DIR",
    ] {
        println!("cargo:rerun-if-env-changed={key}");
    }
    println!("cargo:rerun-if-changed={}", native.display());

    require_file(&source.join("src/include/parser/parser.h"));
    require_file(&library.join("liblbug.a"));
    require_file(&ssl.join("libssl.a"));
    require_file(&ssl.join("libcrypto.a"));

    let object = out.join("ladybug_admission.o");
    run(
        Command::new(env::var_os("CXX").as_deref().unwrap_or(OsStr::new("c++")))
            .args(["-std=c++20", "-fPIC", "-fvisibility=hidden", "-I"])
            .arg(source.join("src/include"))
            .arg("-c")
            .arg(&native)
            .arg("-o")
            .arg(&object),
    );
    run(
        Command::new(env::var_os("AR").as_deref().unwrap_or(OsStr::new("ar")))
            .arg("crs")
            .arg(out.join("libqw_ladybug_admission.a"))
            .arg(object),
    );

    println!("cargo:rustc-link-search=native={}", out.display());
    println!("cargo:rustc-link-lib=static=qw_ladybug_admission");
    let macos = env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("macos");
    // Link these exact archives. Apple's linker can otherwise pick their dylib
    // siblings when resolving a library by bare name.
    for archive in [
        library.join("liblbug.a"),
        ssl.join("libssl.a"),
        ssl.join("libcrypto.a"),
    ] {
        if macos {
            // Keep vendor symbols out of DuckDB's global dynamic namespace.
            println!("cargo:rustc-link-arg=-Wl,-load_hidden");
            println!("cargo:rustc-link-arg=-Xlinker");
        }
        println!("cargo:rustc-link-arg={}", archive.display());
    }
    let cpp_runtime = if macos {
        println!(
            "cargo:rustc-link-arg-cdylib=-Wl,-install_name,@rpath/quack_weave.duckdb_extension"
        );
        "c++"
    } else {
        "stdc++"
    };
    println!("cargo:rustc-link-lib=dylib={cpp_runtime}");
}

fn configured(name: &str, default: PathBuf) -> PathBuf {
    env::var_os(name).map_or(default, PathBuf::from)
}

fn homebrew_openssl_lib() -> Option<PathBuf> {
    let output = Command::new("brew")
        .args(["--prefix", "openssl@3"])
        .output()
        .ok()?;
    output
        .status
        .success()
        .then(|| PathBuf::from(String::from_utf8_lossy(&output.stdout).trim()).join("lib"))
}

fn require_file(path: &Path) {
    assert!(
        path.is_file(),
        "Missing {}. Run make mvp1-deps and ensure OpenSSL 3 is available.",
        path.display()
    );
    println!("cargo:rerun-if-changed={}", path.display());
}

fn run(command: &mut Command) {
    let status = command
        .status()
        .unwrap_or_else(|error| panic!("Could not start {command:?}: {error}"));
    assert!(status.success(), "Command failed ({status}): {command:?}");
}
