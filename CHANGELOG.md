# Changelog

## Research update — 2026-11-18

- Published the five-phase laboratory M3 result and a structured measurement summary.
- Recorded actual NVENC/NVDEC failures alongside passing compute, OpenGL/interop and Vulkan ray checks.
- Documented the FWSEC boundary, unresolved initial SS state and next codec/RT/display investigations.
- Documentation/data only; public CLI and M1/M2 EFI behavior are unchanged.

## 0.2.0.dev0 — initial public development preview

- Linux PCI inventory with explicit device identity and no register access.
- Strict archived-v6 and passive-M1/M2 decoders, preserving invalid and missing data.
- NVIDIA EGL/GLX pixel validation and optional GL/CUDA buffer interoperability.
- Reference CMP50HX M1/M2 EFI source with scoped PCI restoration and pinned handoff.
- Standalone synthetic tests, public QEMU controls, Python packaging and CI.
- Explicit public-file export with checksums and deterministic source archive.
- English/Russian introduction, contribution templates and dated reference results.

This is a research preview. Only one board has physical EFI qualification.
The compute successor, driver patches, vendor binaries and raw lab captures
are not distributed. No dedicated video-engine or RT-core unlock is claimed.
