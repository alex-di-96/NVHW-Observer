# Source lineage

This development package extracts host-side tooling from the HW_Tune research
on the owner's CMP 50HX. It is not an NVIDIA product and does not contain GPU
firmware, a ROM, the EFI compute transaction, access keys or captured machine logs.

`legacy_v6/core.py` and `legacy_v6/authority.py` come from the local
`uefi-gsp-authority-v6-20261112` analysis. Their original file hashes and import
adjustments are recorded in `legacy-v6-provenance.json`. The synthetic parser
tests share that lineage; two tests requiring private historical capture paths
are excluded from this standalone suite. The original full suite is preserved
in the laboratory archive.

The underlying experimental Rust EFI work builds on
<https://github.com/physicsdolphin/nv-uefi-unlocker>, whose workspace declares
GPL-2.0-only. That EFI is not included here. The C snapshot frontend is separate
and carries its own MIT SPDX declaration. Its log-file transport and scoped PCI
access informed/adapted the new `uefi/observer.c`; that source records the lineage.
The original frontend remains a separate artifact on the reference stand.
The MIT permission notice is retained in [LICENSES/MIT.txt](LICENSES/MIT.txt).

The new package uses GPL-2.0-only, with the standard license text in `LICENSE`.
Any future extraction of Rust/C source or third-party dependencies must preserve
its own notices and source lineage. This note does not assign redistribution
rights to NVIDIA binary assets.

GNU-EFI is an external build dependency, not vendored here. Its own licensing
applies to that dependency and any future linked EFI distribution. This initial
publication is a source preview, not a release of linked firmware executables.
Python packages used for building/testing are also installed separately.
