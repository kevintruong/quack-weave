use std::env;
use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::process::Command;

const DUCKGQL_REVISION: &str = "b4421c5cb5e3a389f9658de591a0aa6d397da991";
const DUCKDB_REVISION: &str = "8d78114e90a53823803660bf821f6073ac87da8c";
const ANTLR_VERSION: &str = "4.13.2";
const LADYBUG_VERSION: &str = "0.23.0";

fn main() {
    if env::var_os("CARGO_FEATURE_TEMPLATE_COMPAT").is_some() {
        return;
    }

    let manifest_dir = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap());
    let pinned = manifest_dir.join(format!("../../build/deps/ladybug-{LADYBUG_VERSION}"));
    let native = manifest_dir.join("src/ladybug_admission.cpp");
    let source = configured(
        "LADYBUG_SOURCE_DIR",
        pinned.join(format!("ladybug-{LADYBUG_VERSION}")),
    );
    let library = configured("LADYBUG_LIB_DIR", pinned.join("native/src"));
    let config_headers = library.join("include");
    let engine_archive = library.join("liblbug.a");
    let httpfs_archive = source.join("extension/httpfs/build/libhttpfs_static.lbug_extension");
    let macos = env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("macos");
    let ssl = env::var_os("OPENSSL_LIB_DIR")
        .map(PathBuf::from)
        .or_else(|| env::var_os("OPENSSL_ROOT_DIR").map(|root| PathBuf::from(root).join("lib")))
        .or_else(homebrew_openssl_lib)
        .expect("Set OPENSSL_LIB_DIR to the directory containing OpenSSL 3 static archives");
    let out = PathBuf::from(env::var_os("OUT_DIR").unwrap());

    for key in [
        "CXX",
        "AR",
        "NM",
        "LADYBUG_SOURCE_DIR",
        "LADYBUG_LIB_DIR",
        "OPENSSL_LIB_DIR",
        "OPENSSL_ROOT_DIR",
    ] {
        println!("cargo:rerun-if-env-changed={key}");
    }
    println!("cargo:rerun-if-changed={}", native.display());

    for path in [
        source.join("src/include/parser/parser.h"),
        config_headers.join("common/system_config.h"),
        engine_archive.clone(),
        httpfs_archive.clone(),
        ssl.join("libssl.a"),
        ssl.join("libcrypto.a"),
    ] {
        println!("cargo:rerun-if-changed={}", path.display());
        require_file(
            &path,
            "Run make native-deps and ensure OpenSSL 3 is available.",
        );
    }

    require_archive_symbol(&engine_archive, "qw_lbug_cloud_read_only_attach");
    require_archive_symbol(&httpfs_archive, "qw_lbug_cloud_verified_transport");
    let object = out.join("ladybug_admission.o");
    run(
        Command::new(env::var_os("CXX").as_deref().unwrap_or(OsStr::new("c++")))
            .args(["-std=c++20", "-fPIC", "-fvisibility=hidden", "-I"])
            .arg(source.join("src/include"))
            .arg("-I")
            .arg(&config_headers)
            .arg("-I")
            .arg(source.join("third_party/alp/include"))
            .arg("-I")
            .arg(source.join("third_party/antlr4_cypher/include"))
            .arg("-I")
            .arg(source.join("third_party/antlr4_runtime/src"))
            .arg("-c")
            .arg(&native)
            .arg("-o")
            .arg(&object),
    );
    let mut archive = Command::new(env::var_os("AR").as_deref().unwrap_or(OsStr::new("ar")));
    archive
        .arg("crs")
        .arg(out.join("libqw_ladybug_admission.a"))
        .arg(object);
    if env::var_os("CARGO_FEATURE_BENCHMARK_ENGINE_TIMING").is_some() {
        let probe = manifest_dir.join("bench/ladybug_timing.cpp");
        let object = out.join("ladybug_timing.o");
        println!("cargo:rerun-if-changed={}", probe.display());
        run(
            Command::new(env::var_os("CXX").as_deref().unwrap_or(OsStr::new("c++")))
                .args(["-std=c++20", "-fPIC", "-fvisibility=hidden", "-I"])
                .arg(source.join("src/include"))
                .arg("-I")
                .arg(&config_headers)
                .arg("-c")
                .arg(probe)
                .arg("-o")
                .arg(&object),
        );
        archive.arg(object);
    }
    run(&mut archive);

    println!("cargo:rustc-link-search=native={}", out.display());
    println!("cargo:rustc-link-lib=static=qw_ladybug_admission");
    let neo4j = env::var_os("CARGO_FEATURE_NEO4J_PROVIDER").is_some();
    build_gql(&manifest_dir, &out);
    build_duckdb_shims(&manifest_dir, &out, neo4j);

    // Link these exact archives. Apple's linker can otherwise pick their dylib
    // siblings when resolving a library by bare name.
    if !macos {
        println!("cargo:rustc-link-arg=-Wl,--start-group");
    }
    for archive in [
        engine_archive,
        httpfs_archive,
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
    if !macos {
        println!("cargo:rustc-link-arg=-Wl,--end-group");
    }
    let cpp_runtime = if macos {
        println!(
            "cargo:rustc-link-arg-cdylib=-Wl,-install_name,@rpath/quack_weave.duckdb_extension"
        );
        "c++"
    } else {
        // The vendor archives introduce references after rustc's default system
        // libraries. Resolve glibc's nonshared stubs and GCC's atomic helpers here.
        println!("cargo:rustc-link-arg=-lc");
        println!("cargo:rustc-link-arg=-lgcc");
        println!("cargo:rustc-link-arg=-Wl,-z,defs");
        "stdc++"
    };
    println!("cargo:rustc-link-lib=dylib={cpp_runtime}");
}

fn require_archive_symbol(archive: &Path, name: &str) {
    let output = Command::new(env::var_os("NM").as_deref().unwrap_or(OsStr::new("nm")))
        .arg("-g")
        .arg(archive)
        .output()
        .expect("Read the patched Ladybug archive symbols");
    let symbols = String::from_utf8_lossy(&output.stdout);
    let found = symbols.lines().any(|line| {
        let mut words = line.split_ascii_whitespace().rev();
        words
            .next()
            .is_some_and(|symbol| symbol.trim_start_matches('_') == name)
            && words
                .next()
                .is_some_and(|kind| kind.eq_ignore_ascii_case("t"))
    });
    assert!(
        output.status.success() && found,
        "{} lacks the patched Ladybug symbol {name}. Run make native-deps.",
        archive.display()
    );
}

fn build_duckdb_shims(manifest: &Path, out: &Path, neo4j: bool) {
    let source = manifest.join(format!("../../build/deps/duckdb-{DUCKDB_REVISION}"));
    require_file(
        &source.join("src/include/duckdb/main/capi_v2/capi_v2_internal.hpp"),
        "Run make native-deps.",
    );
    let grammar = manifest.join("grammar");
    println!("cargo:rerun-if-changed={}", grammar.display());
    let mut sources = [
        "graph_explain.cpp",
        "standalone.cpp",
        "graph_table.cpp",
        "watchlist.cpp",
        "runtime_watchlist.cpp",
        "aggregate_pushdown.cpp",
    ]
    .map(|file| grammar.join(file))
    .to_vec();
    if neo4j {
        sources.push(manifest.join("src/neo4j_secret.cpp"));
    }
    let mut objects = Vec::new();
    for shim in sources {
        let object = out.join(shim.file_name().unwrap()).with_extension("o");
        println!("cargo:rerun-if-changed={}", shim.display());
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
                .arg(&shim)
                .arg("-o")
                .arg(&object),
        );
        objects.push(object);
    }
    run(
        Command::new(env::var_os("AR").as_deref().unwrap_or(OsStr::new("ar")))
            .arg("crs")
            .arg(out.join("libqw_duckdb_shims.a"))
            .args(objects),
    );
    println!("cargo:rustc-link-lib=static=qw_duckdb_shims");
    // Upstream EXTENSION_STATIC_BUILD links DuckDB privately so loaders using
    // RTLD_LOCAL can resolve the C++ ABI. Keep only referenced symbols.
    let macos = env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("macos");
    let libraries = manifest.join("../../build/deps/gql-antlr").join(if macos {
        "duckdb-static-v2.0.1"
    } else {
        "duckdb-static-v2.0.1-linux-arm64"
    });
    let archive = libraries.join("libduckdb_static.a");
    require_file(&archive, "Run make native-deps.");
    if macos {
        println!("cargo:rustc-link-arg=-Wl,-dead_strip");
        println!("cargo:rustc-link-arg=-Wl,-load_hidden");
        println!("cargo:rustc-link-arg=-Xlinker");
    } else {
        println!("cargo:rustc-link-arg=-Wl,--exclude-libs,ALL");
    }
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
            "Missing {}. Run make native-deps.",
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

fn require_file(path: &Path, suggestion: &str) {
    assert!(path.is_file(), "Missing {}. {suggestion}", path.display());
    println!("cargo:rerun-if-changed={}", path.display());
}

fn run(command: &mut Command) {
    let status = command
        .status()
        .unwrap_or_else(|error| panic!("Could not start {command:?}: {error}"));
    assert!(status.success(), "Command failed ({status}): {command:?}");
}
