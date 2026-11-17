# Contributing

The first useful contributions are reproducible parser bugs, sanitized inventory
results and functional checks on additional boards. Follow the distinction
between advertised capability, creation, submitted work, validated output and
execution backend. A correct ray-tracing image alone does not identify RT cores.

Use Python 3.10+ and GCC. From a source checkout:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 tools/release.py check
```

Tests use synthetic input and compile the standalone SHA-256 helper; they do not
access a physical GPU. The CI workflow also builds packages and runs EFI mocks
in QEMU without network or GPU passthrough. Hardware testing is separate.

Add new public source files to the sorted `public-files.txt` and `MANIFEST.in`.
Keep generated reports, build outputs, credentials, ROMs and vendor binaries out
of source commits. The release checker uses explicit inclusion plus pattern and
link checks; it does not replace reviewing the selected files.

Changing a device profile requires evidence for identity, read semantics, PCI
restoration and applicable architecture. Never enable a profile from a marketing
name alone or weaken a guard to make a new board pass. Keep failed reads and
skipped checks explicit. Preserve old evidence rather than rewriting its result.

Contributions to this project are under GPL-2.0-only. Preserve third-party
notices and identify adapted code in [NOTICE.md](NOTICE.md). Keep changes focused
and explain their validation and remaining limits in the pull request.
