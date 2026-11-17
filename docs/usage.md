# Command reference

## Run from this directory

```sh
PYTHONPATH=src python3 -m nvhw_observer profiles
PYTHONPATH=src python3 -m nvhw_observer inventory --output inventory.json
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

`inventory` reads PCI sysfs identity attributes and the driver symlink. It does
not open `config`, `resource*` or `rom`, call a GPU API, change a driver, or access
the network. Outputs omit hostname, IP, serial number and absolute driver path.
Review any report before sharing it; PCI IDs and BDF locations remain in it.

To inspect an existing v6 log, supply the independently recorded build hashes:

```sh
PYTHONPATH=src python3 -m nvhw_observer analyze-v6 vbios-observer-v6.log \
  --efi-sha256 "$EXPECTED_EFI_SHA256" \
  --source-sha256 "$EXPECTED_SOURCE_SHA256" \
  --output observation.json
```

An existing output file is never overwritten. Exit 0 means a complete usable
capture for `analyze-v6`, or an inventory with no reported read errors. Exit 2
means invalid/incomplete evidence, a negative control, or an input/output error;
inspect the JSON for the distinction. A successful parse does not demonstrate
functional acceleration. The four inventory/log results remain `not_measured`.
The v6 decoder is tied to that protocol and TU102 experiment; it must not be used
to interpret arbitrary registers from another GPU.

For a new M1 capture, use the manifest from that exact build:

```sh
PYTHONPATH=src python3 -m nvhw_observer analyze-m1 nvhw-m1-0001.log \
  --manifest build/manifest.json --output observation.json
```

M2 completed its first reference-board run on 2026-11-16. It retains M1's
90 observations and appends `0x21d68`, read by the TU102-selected MSENC helper
in the pinned R580 GSP. This is a status observation, not a codec enable write.
Build it explicitly with `--profile m2`; the default remains M1. Its logs use
`nvhw-m2-NNNN.log` and the same `analyze-m1` protocol decoder with the **M2**
manifest. NVDEC, RT, compute and TOP observations remain in the profile.
All 91 words were valid, PCI restore and compute handoff succeeded, and all
90 shared words matched M1. The new `0x21d68` value was `3`. NVDEC decoder-create
and NVENC session-open remained unsupported. CUDA/CUPTI and Vulkan RT correctness
passed; RM/OptiX still reported zero hardware RT count/version. This qualifies
the observation on one board, not an encoder or dedicated RT unlock.

The existing `hwt.observation.v1` JSON envelope and archived `HWT_*` wire markers
retain their names for compatibility. The project, module and command are now
NVHW-observer, `nvhw_observer` and `nvhw-observer` respectively.

## OpenGL functional check

```sh
PYTHONPATH=src python3 -m nvhw_observer test-opengl \
  --bdf 0000:01:00.0 --timeout 30 --output opengl.json
```

Replace the BDF with the intended NVIDIA GPU. This command executes GPU work;
`inventory` still does not. It needs the installed NVIDIA EGL/OpenGL libraries
and access to their device nodes, with no additional Python dependencies.
It creates an OpenGL 3.3 core context on an EGLDevice pbuffer without connecting
to X/Wayland, draws two 64×64 images with different uniform values, reads RGBA8
pixels and checks every byte against a CPU reference. It does not require a
monitor, change X configuration, or supply a remote desktop.

DRM/sysfs maps the selected device to the requested PCI address. Duplicate EGL
devices from different drivers are distinguished using `EGL_DRIVER_NAME_EXT`;
ambiguous targets and software renderers are rejected. No default GPU index is
assumed. A missing required extension or identity mapping is reported explicitly.

`nvhw.functional.v1` adds `opengl` beside compute, NVDEC, NVENC and hardware RT.
Only OpenGL is measured by this command. The report records target verification,
context creation, shader linking, work submission, readback and pixel validation
separately. A worker process bounds execution (1–120 seconds), preserving the last
checkpoint on timeout/crash. Exit 0 requires a completed successful render; exit
2 includes unsupported, error and timeout results. Existing output is refused
before GPU work. The original four-field `hwt.observation.v1` stays unchanged.

Physical validation on 2026-11-16: CMP 50HX, R580.178.04 B2, NVIDIA EGL 1.5,
OpenGL 3.3 core; **8,192 pixels checked, zero mismatches**. The requested context
version is a test minimum, not a measurement of the GPU's maximum GL version.
This is a small correctness test, not comprehensive OpenGL conformance or a
throughput benchmark. GTX 1060, RTX 3070 and CMP 70HX remain untested.

To test the existing NVIDIA PRIME/GLX path and GL/CUDA interoperability:

```sh
PYTHONPATH=src python3 -m nvhw_observer test-opengl \
  --bdf 0000:01:00.0 --backend glx --display :0 --provider NVIDIA-G0 \
  --interop --output glx.json
```

Run as a user with access to that X session; its normal `XAUTHORITY` is inherited.
Adjust the display and provider for the machine. The subprocess selects the
NVIDIA GLX vendor without changing the parent environment. `cuGLGetDevices`
maps the **current GL context** to CUDA devices, then to PCI addresses; a wrong
or multi-GPU context is rejected before the shader draw. This identity check
requires the CUDA driver library even when `--interop` is omitted. Failure of
that mapping does not prove that OpenGL itself is unavailable.

GLX uses the same shaders and exact pixel oracle as EGL. Both single- and
double-buffered RGBA8 pbuffers are accepted; no buffer swap/window presentation
is performed. `--interop` adds a 64 KiB GL upload, CUDA map/read/verification,
CUDA write, unmap and GL readback/verification. The `gl_cuda_interop` result is
separate from shader correctness and does not claim a CUDA kernel benchmark.
Its boolean flags record reached milestones, not a resource's current ownership.
If requested interop fails, the command exits 2 even when the shader test passes.

Physical GLX 1.4 validation on the same 50HX/R580 B2: 8,192 pixels with zero
mismatches and the 64 KiB round trip passed, including resource cleanup. This
does not create an emulated display or validate desktop capture/remote input.
No X server, driver or display-manager restart is needed by either backend.
