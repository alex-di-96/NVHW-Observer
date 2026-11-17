# Reference-board findings

These are dated, author-reported measurements from the private HW_Tune lab.
This distribution contains synthetic tests, not the original machine captures,
proprietary libraries or laboratory workloads. The public unit suite does not
independently reproduce these hardware results. They describe one CMP 50HX and
must not be generalized to every TU102 board.

## Hardware plan

| Board offered by the owner | Role | Current project status |
|---|---|---|
| CMP 50HX / TU102 reference | Physical M1 and M2 qualification | M1 90/90 and M2 91/91 valid words, PCI restore and compute handoff verified on one board; other boards remain unqualified |
| GTX 1060 | Architecture boundary and codec comparison | Pending exact PCI/chip/VBIOS identity |
| RTX 3070 | GeForce compute, codec and RT comparison | Pending exact PCI/chip/VBIOS identity |
| CMP 70HX | Second CMP family comparison | Pending exact PCI/chip/VBIOS identity |

Only the 50HX is currently installed. The Python inventory cannot enable a
register profile. The separately built M1 EFI has one explicit 50HX profile
and requires BOOT0/PROM identity as well as a unique PCI/subsystem match. Unknown devices are
inventoried without inheriting a register map. Marketing names are planning
labels, not hardware identification.

The first physical M1 run completed on 2026-11-15. All 73 shared valid words
matched the preceding frontend snapshot; all 76 shared words matched the
compute loader's input snapshot. CUDA FP32/FP16, 128 MiB memory correctness and
CUPTI kernel recording passed after handoff. NVDEC capability queries remained
unsupported, an actual NVENC session-open attempt failed, and OptiX/RM still
reported zero hardware RT capability/count. This qualifies the passive backend
on this exact board and boot chain; it does not establish a codec/RT unlock,
stock-driver operation or multi-board support.

A separate H.264 Vulkan Video attempt on the same boot reached the NVIDIA
device but failed because the driver exposed no video extensions/queues.
The CPU reference produced 12 frames; no Vulkan output frames were obtained.
Software fallback was rejected at the required hardware-download boundary.

Later the same day, a corrected Vulkan RT workload checked all 6,144 rays across
two TLAS transforms, with zero validation/synchronization errors and an
independent exact CPU reference. RM/OptiX still reported zero RT count/version;
dedicated RT execution remains unproven. A direct NVDEC decoder-create call,
with no application-side capability gate, returned `CUDA_ERROR_NOT_SUPPORTED`.
These lab workloads are preserved in HW_Tune's research archive; they are not
yet portable functional adapters included in this package.

On 2026-11-17, a private follow-up on the same 50HX/R580.178.04 B2 decoded
12 different 640×480 JPEG frames through `libnvcuvid`, despite a separate JPEG
capability query returning `supported=0` and `numNVDECs=0`. All NV12 components
were compared with independent CPU output: maximum difference was 1/255.
CUPTI recorded 36 `jpegdec_idct` and 12 `ConvertYUV420toNV12` CUDA kernels.
This establishes CUDA-assisted JPEG decoding, not a dedicated NVDEC unlock.
The test applied no new patch; whether UEFI/B2 is necessary for this JPEG path
was not measured. H.264/HEVC and the other tested video formats still failed
direct decoder creation, and NVENC session creation remained unsupported.

OpenGL/GLX pixel validation and the 64 KiB GL/CUDA exchange passed both before
and after the JPEG workload. The corrected Vulkan RT check also passed again;
dedicated RT execution remains unproven. These observations motivate separate
capability, creation, frame-validation and execution-backend evidence in future
codec adapters. **There is no portable JPEG or VDPAU CLI command in this preview.**

A later 2026-11-17 VDPAU experiment created a dedicated NVIDIA X-screen and
passed OpenGL/interop, but NVIDIA VDPAU device creation returned status 1 before
any decoder/profile calls. None of the 17 prepared profiles was executed.
The private collector initially misclassified a changed output handle after
API failure; the raw record is preserved, and a corrected collector passed five
C/mock regression tests offline. It has not been deployed. The ordinary desktop
recovered, and the joint compute/CUPTI, OpenGL and Vulkan checks passed on the
same new boot. Future adapters must distinguish API rejection, invalid outputs,
skipped work and collector errors. This is not a codec unlock.

Offline analysis of the exact VDPAU library subsequently traced this rejection
to RM `GET_CLASSLIST_V2` and a table of 14 decoder class IDs that includes
Turing C4B0. The historical 81-class RM capture reaches the diagnostic in an
instruction model. A synthetic C4B0 entry passes only that membership check;
it does not prove device creation or decoding. No live V2 response was captured.


See [design](../DESIGN.md), [commands](usage.md), [source lineage](../NOTICE.md)
and [technical references](sources.md).
