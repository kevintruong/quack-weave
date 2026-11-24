use std::env;
use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::process::Command;

const DUCKGQL_REVISION: &str = "b4421c5cb5e3a389f9658de591a0aa6d397da991";
const DUCKDB_REVISION: &str = "8d78114e90a53823803660bf821f6073ac87da8c";
const ANTLR_VERSION: &str = "4.13.2";

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
    if env::var_os("CARGO_FEATURE_GQL").is_some() {
        build_gql(&manifest_dir, &out);
        build_graph_grammar(&manifest_dir, &out);
    }

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

fn build_graph_grammar(manifest: &Path, out: &Path) {
    let source = manifest.join(format!("../../build/deps/duckdb-{DUCKDB_REVISION}"));
    require_file(&source.join("src/include/duckdb/parser/grammar_extension.hpp"));
    let sources = manifest.join("grammar");
    println!("cargo:rerun-if-changed={}", sources.join("graph_table.hpp").display());
    let mut objects = Vec::new();
    for unit in ["standalone", "graph_table"] {
        let grammar = sources.join(format!("{unit}.cpp"));
        let object = out.join(format!("{unit}.o"));
        println!("cargo:rerun-if-changed={}", grammar.display());
        run(
            Command::new(env::var_os("CXX").as_deref().unwrap_or(OsStr::new("c++")))
                .args([
                    "-std=c++17",
                    "-O2",
                    "-DNDEBUG",
                    "-fPIC",
                    "-fvisibility=hidden",
                    "-I",
                ])
                .arg(source.join("src/include"))
                .arg("-I")
                .arg(source.join("third_party/utf8proc/include"))
                .arg("-c")
                .arg(&grammar)
                .arg("-o")
                .arg(&object),
        );
        objects.push(object);
    }
    run(
        Command::new(env::var_os("AR").as_deref().unwrap_or(OsStr::new("ar")))
            .arg("crs")
            .arg(out.join("libqw_grammar.a"))
            .args(objects),
    );
    println!("cargo:rustc-link-lib=static=qw_grammar");
    // Upstream EXTENSION_STATIC_BUILD links DuckDB privately so loaders using
    // RTLD_LOCAL can resolve the C++ parser ABI. Keep only referenced symbols.
    let libraries = manifest.join("../../build/deps/gql-antlr/duckdb-static-v2.0.1");
    let archive = libraries.join("libduckdb_static.a");
    require_file(&archive);
    println!("cargo:rustc-link-arg=-Wl,-dead_strip");
    println!("cargo:rustc-link-arg=-Wl,-load_hidden");
    println!("cargo:rustc-link-arg=-Xlinker");
    println!("cargo:rustc-link-arg={}", archive.display());
}

fn build_gql(manifest_dir: &Path, out: &Path) {
    let dependencies = manifest_dir.join("../../build/deps/gql-antlr");
    let runtime = dependencies
        .join(format!("antlr4-{ANTLR_VERSION}"))
        .join("runtime/Cpp/runtime/src");
    let generated = dependencies
        .join(format!("duckdb-gql-{DUCKGQL_REVISION}"))
        .join("src/parser/generated");
    for path in [
        runtime.join("antlr4-runtime.h"),
        generated.join("GQLParser.cpp"),
    ] {
        assert!(
            path.is_file(),
            "Missing {}. Run make mvp2-deps.",
            path.display()
        );
    }

    let bridge = manifest_dir.join("src/gql_parser.cpp");
    let cmake_source = manifest_dir.join("gql");
    let cmake_build = out.join("gql");
    for path in [&bridge, &runtime, &generated, &cmake_source] {
        println!("cargo:rerun-if-changed={}", path.display());
    }
    println!("cargo:rerun-if-env-changed=CMAKE");
    let cmake = env::var_os("CMAKE").unwrap_or_else(|| "cmake".into());
    let mut configure = Command::new(&cmake);
    configure
        .arg("-S")
        .arg(&cmake_source)
        .arg("-B")
        .arg(&cmake_build)
        .arg("-DCMAKE_BUILD_TYPE=Release")
        .arg(path_definition("QW_ANTLR_SOURCE", &runtime))
        .arg(path_definition("QW_GQL_GENERATED", &generated))
        .arg(path_definition("CMAKE_ARCHIVE_OUTPUT_DIRECTORY", out));
    if env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("macos") {
        println!("cargo:rerun-if-env-changed=MACOSX_DEPLOYMENT_TARGET");
        configure.arg(format!(
            "-DCMAKE_OSX_DEPLOYMENT_TARGET={}",
            macos_deployment_target()
        ));
    }
    run(&mut configure);
    let jobs = env::var_os("NUM_JOBS").unwrap_or_else(|| "1".into());
    run(Command::new(cmake)
        .arg("--build")
        .arg(cmake_build)
        .arg("--parallel")
        .arg(jobs));
    println!("cargo:rustc-link-lib=static=qw_gql_parser");
}

fn macos_deployment_target() -> String {
    let output = Command::new(env::var_os("RUSTC").expect("Cargo rustc"))
        .args(["--print", "deployment-target", "--target"])
        .arg(env::var_os("TARGET").expect("Cargo target"))
        .output()
        .expect("Read the Rust macOS deployment target");
    assert!(
        output.status.success(),
        "Could not read the Rust deployment target"
    );
    let output = String::from_utf8(output.stdout).expect("UTF-8 rustc output");
    output
        .trim()
        .strip_prefix("MACOSX_DEPLOYMENT_TARGET=")
        .expect("Rust macOS deployment target")
        .to_owned()
}

fn path_definition(name: &str, path: &Path) -> std::ffi::OsString {
    let mut argument = std::ffi::OsString::from(format!("-D{name}="));
    argument.push(path);
    argument
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
