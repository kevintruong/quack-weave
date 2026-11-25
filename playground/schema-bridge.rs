//! Expose Quack Weave's explicit scalar schema parser to the browser.

use std::{cell::RefCell, fmt::Write};

#[path = "../crates/core/src/qw_query/schema.rs"]
#[allow(dead_code)]
mod schema;

thread_local! {
    static INPUT: RefCell<Vec<u8>> = const { RefCell::new(Vec::new()) };
    static OUTPUT: RefCell<String> = const { RefCell::new(String::new()) };
}

/// Reserve the input buffer and return its address in WebAssembly memory.
#[unsafe(no_mangle)]
pub extern "C" fn schema_input(length: usize) -> *mut u8 {
    INPUT.with_borrow_mut(|input| {
        input.resize(length, 0);
        input.as_mut_ptr()
    })
}

/// Return the address of a UTF-8 response with its status on the first line.
#[unsafe(no_mangle)]
pub extern "C" fn schema_parse() -> *const u8 {
    INPUT.with_borrow(|input| {
        OUTPUT.with_borrow_mut(|output| {
            output.clear();
            let parsed = std::str::from_utf8(input)
                .map_err(|_| "QW_ARGUMENT: Schema must be UTF-8")
                .and_then(schema::parse_schema);
            match parsed {
                Ok(columns) => {
                    output.push_str("ok\n");
                    for column in columns {
                        let sql_type = match column.data_type {
                            schema::ScalarType::Boolean => "BOOLEAN",
                            schema::ScalarType::BigInt => "BIGINT",
                            schema::ScalarType::Double => "DOUBLE",
                            schema::ScalarType::Varchar => "VARCHAR",
                            _ => unreachable!("the explicit schema accepts only scalar types"),
                        };
                        writeln!(output, "{}\t{}", column.name, sql_type).unwrap();
                    }
                }
                Err(error) => {
                    output.push_str("error\n");
                    output.push_str(error);
                }
            }
            output.as_ptr()
        })
    })
}

#[unsafe(no_mangle)]
pub extern "C" fn schema_output_length() -> usize {
    OUTPUT.with_borrow(String::len)
}
