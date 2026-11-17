"""Research plan, not permission to run TU102 register accesses on other GPUs."""

CATALOG = [
    {"id": "cmp50hx-tu102-reference", "label": "CMP 50HX reference board",
     "role": "historical reference", "reported_family": "TU102",
     "pci_identity": {"vendor": "10de", "device": "1e09",
                      "subsystem_vendor": "10de", "subsystem_device": "1554"},
     "validation": "historical_single_board", "register_profile_enabled": False},
    {"id": "gtx1060-candidate", "label": "GTX 1060",
     "role": "architecture boundary and codec comparison", "reported_family": None,
     "pci_identity": None, "validation": "pending_inventory", "register_profile_enabled": False},
    {"id": "rtx3070-candidate", "label": "RTX 3070",
     "role": "GeForce compute, codec and RT comparison", "reported_family": None,
     "pci_identity": None, "validation": "pending_inventory", "register_profile_enabled": False},
    {"id": "cmp70hx-candidate", "label": "CMP 70HX",
     "role": "second CMP family comparison", "reported_family": None,
     "pci_identity": None, "validation": "pending_inventory", "register_profile_enabled": False},
]


def identify(identity):
    """PCI match is only a candidate: it does not verify the board or its ROM."""
    candidates = [p['id'] for p in CATALOG if p['pci_identity'] is not None
                  and all(identity.get(k) == v for k, v in p['pci_identity'].items())]
    return {"pci_candidates": candidates, "board_and_rom_verified": False,
            "register_profile_enabled": False}
