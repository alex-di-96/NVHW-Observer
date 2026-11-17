# Preparing a source release

The reviewed boundary is this standalone project, not its parent laboratory
workspace. Keep the existing private Git repository and archives intact.

## Check and export

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 tools/release.py check
python3 tools/release.py export --out ../NVHW-observer-public \
  --archive ../NVHW-observer-source.tar.gz
```

Both outputs must be new. The exporter copies only `public-files.txt`, rejects
symlinks and unreviewed files, checks common credentials/private paths and local
Markdown links, and writes `SHA256SUMS`. Its gzip/tar metadata is deterministic.
It never copies `.git`, parent directories, caches, captures or vendor binaries.
Pattern matching is a screening aid; manually review the selected files too.

`SHA256SUMS` covers all listed source files, including the inclusion list itself.
It is not a signature or an attestation. The export can be checked independently:

```sh
cd ../NVHW-observer-public
python3 tools/release.py check
sha256sum -c SHA256SUMS
```

## Build from the export

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install build twine
python -m build
python -m twine check dist/*
```

Test the wheel in another virtual environment from outside the checkout, with
`nvhw-observer --version`, `profiles`, synthetic inventory and log fixtures.
Extract the sdist to a fresh directory and run its full suite; it includes the
EFI source required by SHA-256 and profile tests. The wheel intentionally
contains only the host CLI and license notices.

## EFI validation

See [the EFI guide](../uefi/README.md). Build both profiles in independent output
directories and compare mode0 bytes. Run QEMU controls with no GPU passthrough.
Without external lab artifacts the mode0/no-GPU and outer one-shot-chain cases
are recorded as skipped, not passed. Do not attach EFI binaries or an automatic
installation script to this initial source preview.

The CI workflow uses read-only repository permissions and pinned action commits.
It checks three Python versions, packaging and both EFI profiles. A prepared
workflow is not evidence of a completed GitHub-hosted CI run. Action usage follows
the official [checkout](https://github.com/actions/checkout) and
[setup-python](https://github.com/actions/setup-python) documentation.

## Publish a reviewed snapshot

Use a fresh Git repository rooted at the checked export. Do not add a public
remote to the private research repository or push its history. Select the owning
GitHub account explicitly and inspect the staged filenames before the first
commit. Source preparation itself does not create a remote or publish anything.

The initial title is **NVHW-observer 0.2.0.dev0 — research preview**. Use
[CHANGELOG.md](../CHANGELOG.md) for release notes, mark the GitHub release as a
prerelease and include the reviewed source archive/checksums. Publishing to PyPI
and distributing executable EFI builds are separate future steps.
