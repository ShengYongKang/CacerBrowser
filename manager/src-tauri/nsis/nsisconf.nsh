; The browser and fingerprint fonts exceed 2 GiB unpacked.
; Use per-file LZMA so NSIS does not map the entire uncompressed payload.
; NSISCONFDIR loads this before Tauri's installer template and its includes.
SetCompressor /FINAL lzma
