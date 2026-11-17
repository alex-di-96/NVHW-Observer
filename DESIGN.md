# Design and validation plan

## Separate reusable mechanics from device knowledge

1. **Evidence transport:** run/build identity, complete records, timestamps,
   PCI access restoration, log persistence and explicit abort outcomes.
2. **Device profile:** measured PCI/subsystem identity, chip identification,
   VBIOS/PROM hash with acquisition method and byte range, reviewed register
   allowlist, read semantics and applicability. BDF selects an instance; it does
   not identify a model or establish compatibility.
3. **Experiment adapter:** passive UEFI capture, an explicitly selected compute
   transaction, or a version-specific Linux/GSP observation. These are different
   adapters with different effects. Default collection must not imply a reset,
   firmware launch or privilege change.
4. **Analysis:** raw value, transport status, validity, derived interpretation
   and confidence stay separate. A failed read cannot become zero, an empty list
   or proof that an engine does not exist.
5. **Functional validation:** independent compute, NVDEC, NVENC, hardware RT and OpenGL
   checks. API exposure and completed workloads are distinct observations.

Record each functional boundary separately: advertised capability, session
creation, submitted work, completed output and output validation. A negative
capability query is not itself a failed frame-decode experiment. A successful
ray-tracing workload does not by itself identify dedicated RT execution.
Select the intended GPU explicitly. Distinguish CPU fallback, CUDA-assisted
processing, fixed-function hardware and an unestablished execution backend.
Neither CPU nor CUDA decoding is proof of dedicated NVDEC execution; validated
CUDA decoding is still a useful capability and must not disappear from the report.
Keep independent CPU decoding as a separately labelled correctness reference.

This preview includes host inventory, the existing v6 decoder and a new passive
M1 EFI transport with one pinned 50HX register profile. Multi-card register
profiles and codec/compute/RT adapters remain future work. The first portable
functional adapter is the explicit Linux NVIDIA OpenGL/EGLDevice shader test.
The Linux R580 boundary observer has its own ABI/protocol and
will need a separate adapter; it is not a generic GSP debugger.

## Common report v1

`hwt.observation.v1` contains tool version, capture time, kind, device identities
or parsed log evidence, and all four `functional_results` fields. The current
kinds are `pci_inventory`, `uefi_v6_log` and `uefi_passive_m1`. None may claim a functional
pass. `not_measured` is explicit, never interchangeable with `unsupported`,
`invalid`, `fail`, or `not_applicable`.

An independently pinned EFI/source pair accompanies v6 parsing. A self-reported
hash is useful provenance but is not an attestation of executed code. Reads are
sequential snapshots, not atomic state. External EFI observation begins after
platform POST/GFW; it cannot by itself establish a pre-GFW execution history.

## Functional report v1

`nvhw.functional.v1` is separate from the historical observation schema and has
five functional fields including `opengl`. A successful OpenGL render cannot
promote any of the other four fields. Context/backend, PCI mapping, driver name,
renderer, shader hashes, two output hashes and exact pixel errors are recorded.
The worker keeps flushed boundary checkpoints for timeout/crash diagnostics.
GLVND can enumerate a physical PCI device through multiple drivers; select by
BDF and driver identity, never the first matching ordinal. A headless EGL pbuffer
does not establish visible scanout, an enabled display object or remote input.

OpenGL is now part of the common regression protocol alongside CUDA, both codecs
and RT. GLX shader/pixel and optional GL/CUDA buffer interoperability checks are
implemented separately from EGL. GLX verifies the current context's exclusive
PCI GPU through `cuGLGetDevices`; an ordinal or renderer name alone is insufficient.
The interop path respects GL/CUDA map/unmap ownership and checks both transfer
directions. Its success is not an NVENC/NVDEC or CUDA kernel result.
Visible output and remote input remain separate unimplemented checks. On each new card run
the same shader/pixel test before considering architecture-specific MMIO profiles.

## Multi-card protocol

### Evidence case: JPEG with negative advertised support

The private 50HX/R580.178.04 B2 experiment on 2026-11-17 produced 12 verified
JPEG frames while a separate JPEG caps query returned success/unsupported.
CUPTI recorded CUDA IDCT and format-conversion kernels. No new driver or EFI
patch was applied, so this establishes an available path, not patch causality.
OpenGL/GLX and GL/CUDA interoperability passed before and after the workload.

Use this as a regression case when a portable codec adapter is implemented:

- Record the exact codec/profile, bit depth, chroma, API, creation flags, GPU,
  driver and context. Never generalize JPEG success to H.264/HEVC or NVENC.
- Keep advertised support separate from direct creation and actual-frame results.
  A negative query can be reported without silently skipping an explicitly
  requested, bounded and reviewed functional probe. A skipped probe stays unmeasured.
- Label observed CUDA kernels as backend evidence without claiming that all
  parsing/decoding runs on GPU or that a dedicated decoder has been enabled.
- Validate all output samples with an independent reference and a declared
  tolerance; reject a wrong-frame reference and detect stale/repeated output.
- Preserve timeout, cleanup and per-case receipts. Dry-run descriptor fields must
  not overwrite actual execution metadata in derived summaries.
- Report the JPEG workload independently; do not promote the existing `nvdec`
  or `hardware_rt` result to hardware PASS from this result.

This is a design requirement, not an implemented schema extension. The current
v1 schemas and CLI are unchanged. The private JPEG probe still contains bench-
and version-specific guards; a portable adapter needs reviewed ABI/version and
explicit device selection first. A separate VDPAU direct-create/frame probe on
a verified NVIDIA X-screen is the next lab candidate; no such adapter is ready yet.

### Comparison sequence

| Step | Evidence required | What it resolves |
|---|---|---|
| 0. Identity | PCI/subsystem/chip, VBIOS version and hash method, motherboard/boot mode, driver and kernel | Which exact hardware/configuration is being compared |
| 1. Ordinary OS baseline | Correct compute output; decoded known frames; valid encoded bitstream decoded independently; RT capability plus a validated RT workload; OpenGL shaders and checked pixels on the selected GPU | What works before any experimental boot; API success alone is insufficient |
| 2. Passive EFI profile | Reviewed bounded allowlist, identity refusal, PCI restore, timeout/cancel/no-target controls, cold-boot provenance | Which state can be observed without the compute transaction |
| 3. Paired experiment | One explicit intervention, same workloads/settings, normal boot recovery and preserved logs | Whether that intervention caused a functional change |
| 4. Performance | Warmup, repeated timed runs, clocks/power/temperature, correctness, latency and dropped frames | Acceleration and sustained CV throughput rather than feature exposure |

Use the same methodology on all four cards. Do not force the same register list,
firmware mechanism, API or expected engine count on different architectures.
GTX 1060 checks architecture boundaries; RTX 3070 is a GeForce comparison;
CMP 70HX checks transfer to another CMP family. A genuine unsupported path must
be an explicit result, not a test failure disguised as success. Confirm the exact
chips before filling architecture-specific fields.

The 8×1080p60 H.264 + YOLO/every-frame workload remains an end-to-end goal.
First establish hardware decode and correct inference independently; record CPU
fallback explicitly. CV correctness or a render alone does not prove NVDEC or
dedicated RT execution. Do not promise equal throughput across these cards.

## Publication boundary

The source export is controlled by `public-files.txt`; `tools/release.py`
checks its contents, local documentation links and common private-data patterns.
It never exports the parent workspace or Git history. A wheel contains the host
CLI; the source release also includes tests, GNU-EFI source and synthetic QEMU
controls. CI checks Python 3.10/3.12/3.14, packaging and both EFI profiles.

Public QEMU tests require no external compute loader. The mode0 no-GPU and outer
one-shot-chain checks still need external lab inputs and are explicitly skipped
when absent. Emulation proves control flow, not physical GPU behavior. Only the
reference board has physical qualification. The profiles and hardware source
are unchanged by publication preparation.

## Lessons from private analysis

The [reference results](docs/reference-results.md) are author-reported lab
findings, not raw data bundled with this preview. Preserve these distinctions:

- Accept output handles only after successful API status; distinguish collector
  errors, API rejection, skipped work and GPU faults.
- Keep pointer provenance, owner, argument use, address geometry, value and
  lifecycle separate. An offset or nearby constant alone is not object identity.
- Execute complete applicable HAL groups in models and retain overwrite order.
  Typed architecture selectors are not interchangeable runtime flags.
- Preserve indirect calls, unknown offsets, unsupported instructions and search
  budgets. Zero matches cannot prove absence of hardware writers.
- A DEVICE_MAPPING pointer is distinct from its subsequent CPU-base load.
  Read/write widths and filter callbacks may change the transaction path.
- An arithmetic alias from an invalid index is not a supported caller path.
  A conditional producer/consumer alias is not measured execution.

## Remaining milestones

A portable JPEG/VDPAU/compute/RT adapter needs explicit device selection,
ABI handling, independent output validation, measured backend and cleanup tests.
Private workload success does not imply that such an adapter is shipped.

Qualify another board/platform before extending EFI compatibility. Recover and
document any external compute successor separately, preserving source lineage
and build inputs. Do not remove identity checks to obtain compatibility.

Keep the common compute/CUPTI, NVDEC, NVENC, hardware RT and OpenGL/interop
protocol as adapters are added. Publication does not qualify new register
profiles or establish a codec/RT unlock.
