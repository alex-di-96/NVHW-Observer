# CMP 50HX: five-phase UEFI observation and joint runtime checks

**2026-11-18 · author-reported result on one TU102 board · no new codec or
dedicated RT activation demonstrated.** [Русское резюме](#русское-резюме)

The laboratory's experimental **lifecycle M3** extends observations inside its
existing Rust compute loader. It is not a new public EFI profile or an upstream
M3 milestone. The public M1/M2 code and CLI are unchanged; the experimental
compute loader, vendor binaries and raw captures are not distributed here.
The existing compute transaction performs writes and firmware execution.
The new observation points add no GPU MMIO writes; the complete boot chain
must not be described as read-only.

Environment: CMP 50HX / TU102, R580.178.04 open modules with the laboratory's
**B2 modifications, not a stock driver**, Linux 7.0.0-42. The operator reported
completion after instructions to disconnect power for 60 seconds; the physical
disconnect and duration were not independently measured. All runtime checks
below used the same subsequent boot.

## What the new phase established

The same 90 addresses were observed at five points: before the current compute
transaction, after the FWSEC step, after verified Booter execution, after SS
override/relock, and after reconnect before OS handoff. This adds a distinct
post-FWSEC observation to the earlier four-phase protocol. All **450 reads**
returned successful transport status and usable values.

These are sequential snapshots, not a continuous or atomic trace. The interval
before the post-FWSEC snapshot includes ordinary preparation as well as FWSEC.
FWSEC actually ran on this boot; the log did not take its skip branch.

Hexadecimal values:

| Register | Before transaction | After FWSEC | After Booter | After SS/relock | Handoff |
|---|---|---|---|---|---|
| WPR2_LO `1fa824` | `1ffffe00` | `027fe000` | `02777000` | `02777000` | `02777000` |
| WPR2_HI `1fa828` | `00000000` | `027fee00` | `00000000` | `00000000` | `00000000` |
| FECS PLM `409650` | `ffffff8f` | `ffffff8f` | `ffffffff` | `ffffffef` | `ffffffef` |
| SS0 `409664` | `20020000` | `20020000` | `20020000` | `88888888` | `88888888` |
| SS1 `40966c` | `00000007` | `00000007` | `00000007` | `00000008` | `00000008` |
| FECS readout `409668` | `016db6ed` | `016db6ed` | `016db6ed` | `00000000` | `00000000` |

The other **84 addresses remained unchanged**, including all 64 sampled TOP
words. The observed fields `21378=7`, `21c24=7`, `21d68=3`, `21c04=1`,
`21168=0` and raw `118234=3ff` were identical at all five points.

The new evidence separates the working WPR2/compute transitions from those
video/display/RT fields in the sampled states. It does **not** establish OTP,
physical absence of engines, permanent disablement, or the impossibility of
another activation mechanism. The outer EFI already observed raw GFW `3ff`;
this is not a pre-devinit experiment.

Comparison with the preceding outer-frontend capture found 77 shared valid
fields. Only initial SS0 and SS1 differed: `0/0` previously, `20020000/7` now.
The cause of this cross-boot difference is unresolved. SS1's value `7` and the
NVDEC mask's value `7` belong to different addresses and do not establish an
alias or causal relationship.

## Completed work versus advertised capabilities

| Runtime check | Observed result |
|---|---|
| CUDA FP32/FP16, 256×256 | Zero error against CPU FP64 reference |
| CUDA memory, 128 MiB | Pattern readback passed |
| CUPTI | Five GEMM kernels recorded; finite output |
| OpenGL/GLX | Both plain and traced runs checked 8,192 pixels each |
| CUDA/OpenGL interop | Both runs passed the 64 KiB bidirectional readback |
| NVENC CUDA and OpenGL session creation | Status `2`, null handle in both runs |
| Direct H.264 NVDEC create, without an application caps gate | Status `801`, null handle, no frames |
| H.264, HEVC 8/10-bit and VP9 8/10-bit caps | API success with `supported=0`, decoder count `0` |
| Four-frame FFmpeg `h264_cuvid` request | Stopped at unsupported capability check; no output frames |
| Four-frame FFmpeg `h264_nvenc` request | `OpenEncodeSessionEx` rejected the device; zero-byte bitstream |
| Vulkan ray tracing | 6,144 rays across two TLAS transforms, zero mismatches or validation errors |
| OptiX RT-core version property | Query succeeded, value `0`; dedicated TTU execution unproven |

The FFmpeg decoder frontend stopped at its capability gate, but the independent
direct decoder-create call did bypass that application gate and still failed.
The encoder's “initialized successfully” diagnostic only preceded session
creation: a later unsupported-device error prevented encoding. CPU rawvideo
input processing is not evidence of NVDEC operation.

This was a correctness and availability check, not an eight-stream 1080p60
benchmark or a measurement of maximum performance. JPEG, Vulkan Video and
physical display heads were not retested on this boot. The previously reported
CUDA-assisted JPEG result remains distinct from dedicated video decoding.

## NVENC trace: availability before allocation

The CUDA/OpenGL session windows produced **544 trace events and 539 ioctl
observations**, including nested class-list responses and process mappings,
with no capture errors. RM reported seven engines (GR, COPY0–4, SW) and an
81-class list without decoder `C4B0` or encoder `C4B7`. No allocation of those
two classes appeared in these API windows.

Counts, commands, statuses, engine lists, class lists and allocation-class
counts matched the preceding trace from before this power cycle. This is a
reproducible observation, not yet an instruction-level explanation of the
unsupported-device decision. A call stack through `libnvcuvid` alone does not
prove that NVENC depends on a functioning decoder.

## Research directions

1. **NVENC and NVDEC:** connect the precise usermode rejection branch to RM/GSP
   engine and class availability. Distinguish a missing class from another
   policy condition; changing a reported status is not a working encoder.
2. **Dedicated RT:** identify backend selection and GR-context/opcode behavior.
   Correct Vulkan rays, a zero capability field and a metadata count override
   each answer different questions. Community GR addresses need TU102-specific
   owner/address/phase qualification before hardware experiments.
3. **Display:** trace the producer of `21c04` and display-IP initialization,
   refresh and removal alongside BSP/MSENC availability. Working OpenGL does
   not establish physical scanout or a common display/video enable switch.
4. **Initial SS state:** establish what initializes SS0/SS1 and which boot
   conditions account for the observed difference. Do not infer causation
   merely from a cold/warm label.

GRID/vGPU remains a future, separate hypervisor experiment, including whether
compute state survives VFIO/reset. This run establishes neither vGPU support
nor a new GRID configuration. Another UEFI run should test a qualified new
observation point or hypothesis rather than repeat these same five snapshots.

## Evidence and validation scope

The [structured summary](2026-11-18-lifecycle-m3-summary.json) is an explicitly
selected extraction of our private captures. It contains no machine addresses,
boot identifiers, credentials, raw process mappings or proprietary binaries.
It is **not a raw capture or independently reproduced result**.

Two experimental EFI builds were byte-identical; preparation passed 132 Rust
host tests, 20 Python tests and 11 QEMU scenarios. QEMU exercised synthetic
records, failure handling, cancellation and handoff, not a physical TU102.
One initial QEMU checker used a wrong row index; its failed record was retained,
and the corrected address-based check passed. Before runtime checks, a separate
metadata helper's shadowed variable was corrected so the UEFI provenance record
kept the actual log filename; three offline controls passed.

The hardware archive replay verifies 158 sealed files and 10 pinned analysis
inputs. Twelve system-health checks around the runtime work reported no driver
or kernel faults. Normal modules/system files were unchanged. The one-shot
marker was consumed; no new experiment is armed. Those laboratory counts do
not claim that this public repository ships the M3 test harness or loader.

Source lineage and API references remain in [Sources](../sources.md), notably
the upstream Rust loader, NVIDIA R580 headers, Video Codec SDK, CUPTI, OptiX
and Khronos specifications. The measurements and conclusions here are ours.

## Русское резюме

M3 штатно прошла пять фаз по90адресов. FWSEC действительно выполнился,
WPR2 изменился, затем применился compute override. Поля NVDEC/NVENC, дисплея
иRT, а также64TOPwords в снятых точках остались прежними. Это уточняет границы
поиска, но не доказывает аппаратное отключение или невозможность активации.

Compute/CUPTI/OpenGL/interop работают. NVENC отказал при открытии сессии,
NVDEC — при прямом создании декодера без caps-gate; попытки H.264 не дали
кадров или битстрима. Vulkan проверил6144луча без ошибок, но исполнение
на выделенныхRT-блоках пока не доказано. Фактический драйвер — R580/B2,
а не чистый stockR580.

Новая зацепка: начальные SS0/SS1 между двумя загрузками различаются,
причина ещё неизвестна. Далее исследуем точную ветку отказа NVENC,
формирование доступных классов RM/GSP, выбор RT-бэкенда и display-IP lifecycle.
Публичный код M1/M2 не менялся; M3 здесь опубликована как результат
исследования и JSON-сводка, а не как готовый установщик или новый unlock.
