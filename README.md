# NVHW-observer

GPU research tools that keep **observations, advertised capabilities and completed
work** separate. Development preview **0.2.0.dev0** for Linux; Python 3.10+.

[Русский](README.ru.md) · [Commands](docs/usage.md) · [Reference results](docs/reference-results.md) · [Sources](docs/sources.md) · [Design](DESIGN.md) · [Contributing](CONTRIBUTING.md)

| Included | What it establishes |
|---|---|
| PCI inventory | Device and driver identity from sysfs; multiple GPUs supported |
| Offline v6 and M1/M2 decoders | Completeness, build identity, read validity and PCI restoration |
| NVIDIA EGL/OpenGL test | Two rendered images checked against a CPU reference |
| GLX + optional CUDA exchange | Current-context PCI identity and a validated 64 KiB buffer round trip |
| Passive EFI M1/M2 source | A narrowly qualified CMP 50HX snapshot and handoff protocol |

**No NVDEC/NVENC or dedicated RT unlock is claimed.** Compute, both video
engines, hardware RT and OpenGL remain separate result fields. A successful
capture or render cannot turn unmeasured features into PASS.

## Install and try

From this source directory:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
nvhw-observer --version
nvhw-observer inventory --output inventory.json
nvhw-observer profiles
```

There are no third-party Python runtime dependencies. Source/wheel installation
is supported; availability on PyPI is not implied.

Inventory needs no administrator access. It reads PCI identity files and the
driver symlink, without opening PCI config, BAR resources or ROM. It does not
call GPU APIs or access the network. Reports omit hostname, IP and serial
numbers; review a report before sharing. Existing output files are preserved.

To run actual GPU work, select the intended NVIDIA device explicitly:

```sh
nvhw-observer test-opengl --bdf 0000:01:00.0 --output opengl.json
```

Replace the example BDF with your inventory result. This uses installed NVIDIA
EGL/OpenGL libraries, verifies the device, renders two 64×64 images and checks
every pixel. It does not need X/Wayland or a monitor. GLX and GL/CUDA exchange
on an existing X session are documented in [the command reference](docs/usage.md).

## Current hardware scope

EFI profiles were qualified on **one CMP 50HX / TU102 board and ROM**.
Selection checks PCI/subsystem, BOOT0 and PROM identity; a marketing name or
matching chip alone is insufficient. GTX 1060, RTX 3070 and CMP 70HX comparisons
are planned, not validated support.

The public EFI source has no GPU MMIO write/reset interface. It may temporarily
enable PCI MEMORY decoding, restores that bit and verifies the result. It then
chains an independently pinned external compute loader, which is **not included**.
This is a reference research backend, not an installable universal boot chain.
There is no flash, deployment, reboot or power-control command in the package.
See [EFI build and QEMU controls](uefi/README.md).

Previous lab results include working OpenGL/interop and CUDA-assisted JPEG
decoding despite a negative capability query. Dedicated video decode/encode
and hardware RT execution remain unconfirmed. JPEG, VDPAU, CUDA and Vulkan lab
workloads are **not portable commands in this release**. Dated findings and
their limits are in [reference results](docs/reference-results.md).

## Develop and package

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 tools/release.py check
python3 -m pip install build
python3 -m build
```

Tests use synthetic input and GCC for SHA-256 validation. CI additionally checks
installed wheels and EFI/QEMU controls without a physical GPU. A wheel contains
the host CLI; the source archive includes EFI source, tests, profiles and docs.

[Release preparation](docs/releasing.md) exports only the explicit public file
list, with checksums and a reproducible source archive. It never publishes or
includes the private research Git history.

## License and lineage

GPL-2.0-only; see [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md). Adapted MIT
material retains its [notice](LICENSES/MIT.txt). This is an independent project,
not an NVIDIA product. No NVIDIA firmware, ROMs or driver binaries are bundled.

## Sources and acknowledgements

Our [annotated source list](docs/sources.md) credits the upstream UEFI and CMP
projects, NVIDIA/Nouveau sources, official API specifications and research tools.
It identifies examined revisions and explains each source's role. Thank you to
their authors and maintainers for making this research possible.

## Support the Project =)

If you find NVHW-observer useful and want to support its development, consider:

- 🍪 Buy me a cookie — [Boosty](https://boosty.to/alex.di/donate)
- ⭐ Star the repo — it helps with visibility
- 🐛 Report bugs — open issues for any problems you find
- 🤝 Contribute — PRs welcome!

Every cookie fuels more features, faster bug fixes, and better documentation! 🚀
