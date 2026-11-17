# NVHW-observer passive EFI M1/M2

M1 qualifies the new standalone passive transport on the owner's CMP 50HX.
It does not repeat v6's FWSEC authority experiment. It captures one pre-compute
snapshot, then starts an independently pinned existing compute loader, which
retains its Space/Enter confirmation. Platform POST/GFW has already run.

M2 appends one observation to the unchanged M1 set: `0x21d68`. In the pinned
R580.178.04 GSP, the complete TU102 MSENC HAL initializer selects callback
`0x5555568` at slot `0x208`; that callback reads BAR0+`0x21d68` and uses its
low three bits in a selection mask. It does not establish physical engine
count or successful encoding. The new register is not written. M2 completed
its first reference-board run on 2026-11-16. Its 91-word profile is restricted to
the same PCI/subsystem/BOOT0/PROM/successor identity as M1.

The explicit profile contains a PCI/subsystem pair, BOOT0, the previously
measured SHA-256 of 64 KiB PROM, and 90 known register addresses. Those addresses
are the union of the earlier v6 core/TOP and baseline video core/TOP sets.
There are no new unknown register ranges. `0x625488` is excluded. The profile
includes shared TOP enumeration plus NVDEC, RT, compute and early-boot state;
it cannot independently prove NVENC/NVDEC/RT activation.

Selection requires exactly one matching PCI/subsystem device, regardless of BDF.
The PM capability must report D0 and BAR0 must be a usable memory aperture.
The GPU access API only exposes reads. If COMMAND.MEMORY is disabled, only that
bit is set with a 16-bit config write; the original command is restored and read
back. PMCSR, BAR addresses, BME, BIOS, ReBAR and GPU registers are never written
by M1. The external compute successor has its own effects and is not included.

Logs use `HWT/nvhw-m1-NNNN.log`, preserving previous files. Every line is
written/flushed/closed. Source/profile/self-file/successor hashes, run ID,
statuses and validity are recorded. These are provenance checks, not remote
attestation. Failed reads remain invalid; optional poison values are retained.
Restoration, identity, transport or logging failure leads to STOP, without
starting the successor. STOP requires cold recovery, not automatic retry.
M2 uses a separate `HWT/nvhw-m2-NNNN.log` namespace and the same NVHW1 protocol.
Use its exact build manifest with `analyze-m1`; the decoder obtains the word
set from that manifest. Invalid NVENC status remains unknown, never zero.

## Build

The reference GNU-EFI package is Ubuntu amd64 `gnu-efi=3.0.15-1build1`, SHA-256
`cb325283fa03f323fb2f2f2db6085c57518afe0a2d4f752efcc1a836dd2c48e6`.
Extract it to a persistent local dependency directory; no system installation is
needed. GCC, ld and objcopy identities are recorded in each build manifest.

```sh
python3 uefi/build.py --gnu-efi-root /path/to/extracted/package --out build-a
python3 uefi/build.py --gnu-efi-root /path/to/extracted/package --out build-b
```

Append `--profile m2` to build M2. The builder rejects changes outside the
reviewed profile delta, including speculative disable/defective addresses.
It does not extend M2 to GA102/GA104 or other TU102 boards automatically.

Output directories must be new or empty. **Only `nvhw-observer-0.efi` is a hardware
candidate.** Modes1–9 and `mock-successor.efi` are synthetic QEMU artifacts and
must never be deployed. Build produces no installation, ticket or power action.

```sh
python3 uefi/qemu_test.py --build build-a --out qemu-results \
  --case complete
```

Omit `--case` to run all 11 public mock cases (12 boots, including a repeated
complete capture). These require no private loader. `plan.json` explicitly
records the omitted no-GPU and outer-chain checks. OVMF paths can be overridden
with `--ovmf-code` and `--ovmf-vars`.

An optional `--real-successor /path/to/pinned/UNLOCK.EFI` enables the mode0
no-GPU negative control after checking its hash. It is not
executed there. Successful mock cases use the generated QEMU exit stub. An
optional `--outer-mock` tests the reference frontend's one-shot routing over two
boots. No GPU passthrough or network is enabled in QEMU. These tests validate
protocol/control flow, not physical PCI/MMIO behavior on a motherboard.

On Ubuntu amd64, the build dependencies can be installed as distribution
packages: `gnu-efi gcc binutils qemu-system-x86 ovmf dosfstools mtools parted`.
For an installed GNU-EFI package use `--gnu-efi-root /`; the manifest records
actual dependency/tool hashes. A different toolchain is a new build identity,
not a reproduction of the historical reference EFI hash.

## Reference-stand launch

Deployment remains a separate lab operation with current boot/driver identity,
external volume UUID/size checks, full verified backup and exact file inventory.
It replaces only `EFI/HWT/NVDEC.EFI`; the existing frontend consumes its one-shot
ticket before starting M1. A later boot with no ticket takes the known compute
loader. The generic package has no automatic installation or shutdown command.

For each physical qualification, require a new Linux boot, strict log parsing,
preservation of old files, PCI restore, driver health and the joint
compute/NVDEC/NVENC/hardware RT protocol. A completed M1 snapshot alone proves
neither an unlock nor production readiness.

The reference board completed its first run on 2026-11-15: 90/90 valid words,
zero transport errors, COMMAND `0 -> 2 -> 0`, matching PROM identity, then the
pinned compute successor and Linux. The installed EFI SHA-256 was
`425820b5a68b4f6a7d2aba23b4008602bf2945f769d39b34b06ac7d14602d663`.
This was one board on one platform, with the existing B2 R580 driver. The
outer frontend and compute successor still have reference-stand assumptions;
M1's BDF-independent selection does not make the entire boot chain universal.

M2's first reference run obtained 91/91 valid words with no transport errors,
COMMAND `0 -> 2 -> 0`, and the same successful compute successor. All 90 shared
words matched M1; the added `0x21d68` was `3`. The hardware EFI SHA-256 was
`a00459906d4826351f58a8b3c1b5a2a87b4637a3dc5bad846419709f1ba589f1`.
On the new Linux boot, CUDA FP32/FP16, 128 MiB memory correctness and CUPTI
passed. Direct NVDEC decoder-create and NVENC session-open remained unsupported.
Vulkan RT checked 6,144 rays without mismatches or validation errors, while
RM/OptiX still reported zero hardware RT count/version. The nonzero static
helper mask derived from `0x21d68` does not establish a usable physical encoder.
No additional hardware run is implied by updating these qualification notes.
