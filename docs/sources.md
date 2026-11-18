# Sources and acknowledgements

This bibliography covers the development preview and the research that informed
it, through **2026-11-17**. Thank you to the upstream authors and maintainers who
published source, specifications and reproducible experiments.

Links with a commit or version identify the revision examined in our research;
unversioned links are project/documentation entry points. A reference is not a
claim that its code is bundled or that its results apply to our board. Code
lineage and retained notices are recorded in [NOTICE.md](../NOTICE.md).

## Code lineage and early UEFI work

| Source | Role in NVHW-observer and the preceding research |
|---|---|
| [physicsdolphin/nv-uefi-unlocker](https://github.com/physicsdolphin/nv-uefi-unlocker/tree/62a3c7a13d3a0e87ced5ec3fd70a6ec8b36f08dd) — initial examined revision `62a3c7a` | Upstream foundation of the laboratory's Rust compute loader and early UEFI diagnostics. The Rust loader and its GPU transaction are not included in this preview. This revision identifies the initial review, not every later laboratory modification. |
| [xrip/cmp50hx-unlock](https://github.com/xrip/cmp50hx-unlock/tree/b630a493b7877fbd4472113dcb960a93749c0a78) — `b630a49` | TU102/CMP 50HX compute, driver-policy, memory-board and tuning comparisons; part of the Turing lineage referenced by the upstream UEFI project. Its patchers are not bundled. |
| [nlzy/turing-unlock](https://github.com/nlzy/turing-unlock) | Turing compute work credited by the upstream UEFI payload; examined as part of that lineage. Not a codec or dedicated-RT activation result. |
| HW_Tune host parsers and C diagnostic frontend | Our preceding laboratory implementation. The v6 extraction hashes are in [legacy-v6-provenance.json](../legacy-v6-provenance.json). The public C observer adapts the frontend's log transport and scoped PCI access; its [MIT notice](../LICENSES/MIT.txt) is retained. |

The public M1/M2 observer is a passive observation and handoff implementation.
Its relationship to a compute loader does not make that loader part of this
distribution. See [EFI scope and build instructions](../uefi/README.md).

## Primary technical references

| Reference | What we used it for |
|---|---|
| [NVIDIA open-gpu-kernel-modules, R580.178.04](https://github.com/NVIDIA/open-gpu-kernel-modules/tree/c8e699821c23e4335bf23330a54a23d15cfb95e9) — `c8e6998` | Public RM control ABI, engine enumeration and HAL/register definitions used to interpret observations. This is source-reference identity, not a claim that the reference stand runs unmodified modules. |
| [TU102 fuse definitions](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/c8e699821c23e4335bf23330a54a23d15cfb95e9/src/common/inc/swref/published/turing/tu102/dev_fuse.h) | Register names and field layouts. A header's access annotation does not establish that an override works on the physical board. |
| Linux/Nouveau v6.8: [TU102 NVDEC](https://github.com/torvalds/linux/blob/v6.8/drivers/gpu/drm/nouveau/nvkm/engine/nvdec/tu102.c), [TU102 NVENC](https://github.com/torvalds/linux/blob/v6.8/drivers/gpu/drm/nouveau/nvkm/engine/nvenc/tu102.c), [TOP parsing](https://github.com/torvalds/linux/blob/v6.8/drivers/gpu/drm/nouveau/nvkm/subdev/top/gk104.c) | Independent public implementations for engine identity, topology and initialization comparisons. Not a tested replacement driver in this release. |
| [NVIDIA NVDEC programming guide, SDK 13.0](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvdec-video-decoder-api-prog-guide/index.html) | Capability queries, decoder creation and frame processing as separate stages in laboratory tests. |
| [NVIDIA NVENC programming guide, SDK 13.0](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-video-encoder-api-prog-guide/index.html) | Encoder sessions, capability queries and actual encoded output as separate evidence. |
| [NVIDIA CUDA Driver API: OpenGL interoperability](https://docs.nvidia.com/cuda/cuda-driver-api/cuda_driver_api/group__CUDA__GL.html) | Current-context device identification and GL/CUDA buffer exchange in the public functional test. |
| [NVIDIA CUPTI](https://docs.nvidia.com/cupti/) | Recording executed CUDA kernels in the broader laboratory work, including the CUDA-assisted JPEG result. CUPTI workloads are not portable commands in this preview. |
| [NVIDIA OptiX](https://developer.nvidia.com/rtx/ray-tracing/optix) | Ray-tracing workloads and device-property investigation. A successful rendered result alone does not establish dedicated RT-core execution. |
| Khronos [OpenGL registry](https://registry.khronos.org/OpenGL/), [EGL device query](https://registry.khronos.org/EGL/extensions/EXT/EGL_EXT_device_query.txt) and [EGL device platform](https://registry.khronos.org/EGL/extensions/EXT/EGL_EXT_platform_device.txt) | OpenGL/GLX behavior and EGL operation on an explicitly selected device without a window system. |
| [Khronos Vulkan registry](https://registry.khronos.org/vulkan/) | Vulkan ray-tracing and video API investigation in the laboratory. Those workloads are not shipped CLI adapters yet. |
| [UEFI Specification 2.10](https://uefi.org/specs/UEFI/2.10/) | EFI protocols, PCI I/O, file logging and image handoff used by the C backend. |

## External tools

- [GNU-EFI](https://github.com/ncroxon/gnu-efi): external headers, startup and
  libraries for the C EFI build; not vendored. Its notices apply separately.
- [QEMU](https://www.qemu.org/documentation/) and
  [TianoCore EDK II / OVMF](https://github.com/tianocore/edk2): firmware test
  environment for the public mock controls. These runs do not emulate a TU102
  or prove that its hardware features work.
- [envytools / envydis](https://github.com/envytools/envytools/tree/f102b82381f3f11cee113d16374c87091db039d9),
  revision `f102b82`: Falcon instruction analysis in the preceding firmware
  research. Not bundled or required by the public host CLI.

## Community projects examined for hypotheses

These entries acknowledge comparative research, not additional dependencies or
patches automatically applied by NVHW-observer. Descriptions refer to the
examined snapshots; they do not promise current compatibility.

| Project / examined revision | Question it helped investigate |
|---|---|
| [amoghmunikote/cmpunlocker](https://github.com/amoghmunikote/cmpunlocker/tree/2c7e2ecd7944e791fec040d2680036beb4a9327b) — `2c7e2ec` | CMP compute and GA100 memory paths; separating architecture-specific memory changes from TU102 behavior. |
| [Icyoung/cmpunlocker GR tool](https://github.com/Icyoung/cmpunlocker/blob/bb2ae3fe2d8f5e7d6574e2a15311f2589dda33bc/tools/gr_unlock/README.md) — `bb2ae3f` | CMP 70HX/90HX graphics-policy comparisons; graphics, compute and codec enablement are distinct questions. |
| [WildFlash1st/cmp90hx-unlock](https://github.com/WildFlash1st/cmp90hx-unlock/blob/76940ae583281daa2b883518a2e89b56c11d3a46/STATUS.md) — `76940ae` | Early state, driver handoff and documented negative experiments on another CMP family. |
| [vnadein/cmp90hx_deploy](https://github.com/vnadein/cmp90hx_deploy/blob/72c31d6f41fe5dd8ee280d2283f92c78541fd444/FINAL_TEST.md) — `72c31d6` | Compute validation and deployment comparisons on CMP 90HX. |
| [DualCoder/vgpu_unlock](https://github.com/DualCoder/vgpu_unlock) and [mbilker/vgpu_unlock-rs](https://github.com/mbilker/vgpu_unlock-rs/tree/b9eedca3e4f567051bbb818e00c613fa50e0a598) — Rust snapshot `b9eedca` | vGPU identity, profile-policy fields and ABI comparisons. A virtual profile's encoder capacity is not proof of a working physical encoder. |
| [keylase/nvidia-patch](https://github.com/keylase/nvidia-patch/tree/620c4aa29cbff9ea32a0b1e29dad60eb62b9dba5) — `620c4aa` | Distinguishing NVENC session limits and NvFBC capture policy from engine availability and NVDEC decoding. |
| [dartraiden/NVIDIA-patcher](https://github.com/dartraiden/NVIDIA-patcher/tree/857547313869458f39c1abed55a2601c4459d964) — `8575473`, and [forkProj/cmppatcher](https://github.com/forkProj/cmppatcher/blob/e2ecbab9390685de0d8b4f2af01b31452de05d33/src/patcher.py) — `e2ecbab` | Windows/CMP driver-policy and codec-package comparisons, not validation on our Linux stand. |

The memory/tuning survey also examined
[RomanKern89/cmp50hx-unlock](https://github.com/RomanKern89/cmp50hx-unlock),
[cachenetics/170tune](https://github.com/cachenetics/170tune),
[PixelML/club-170hx](https://github.com/PixelML/club-170hx),
[duggasco/CMP100-210](https://github.com/duggasco/CMP100-210),
[Consensus-Protocol/cmp170hx](https://github.com/Consensus-Protocol/cmp170hx) and
[pearlfortune/cmpunlocker](https://github.com/pearlfortune/cmpunlocker).
Physical memory modifications, memory-clock tuning and capacity overrides on
other architectures must not be conflated with extra memory on our 10 GiB TU102.

## Our observations and their limits

The [2026-11-18 lifecycle M3 update](research/2026-11-18-lifecycle-m3.md) adds
first-party measurements using the existing laboratory loader and API tools.
Its [structured summary](research/2026-11-18-lifecycle-m3-summary.json) records
selected values; it is not an independently reproduced upstream result.


The dated [reference-board findings](reference-results.md) are our own
author-reported measurements. Upstream documentation supplies API definitions
and comparison points; it does not independently verify those measurements.
The public suite contains synthetic inputs rather than the private raw captures.

This preview does not establish NVDEC/NVENC or dedicated-RT activation. CUDA
compute, OpenGL/interop, rendered ray-tracing output and CUDA-assisted JPEG
decoding are recorded separately from the execution backend. Contributions
should preserve that distinction and cite the exact source revision or capture
that supports a new result.
