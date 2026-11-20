//! Generate TypeScript API declarations at an explicitly supplied path.
use std::{env, fs, io};

fn main() -> io::Result<()> {
    let path = env::args_os()
        .nth(1)
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "supply an output file path"))?;
    fs::write(path, http_api::options::typescript())
}
