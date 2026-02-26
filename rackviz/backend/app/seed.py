"""Populate the database with the initial rack layout."""
from .models import Device, Port
from .database import SessionLocal


RACK_DEVICES = [
    # ── Patch Panels (8 × 1U, 24 ports each) ──────────────────────────
    {"name": "Patch Panel 1", "device_type": "patch_panel", "rack_unit": 1,  "unit_size": 1, "port_count": 24, "color": "#3a3a4a"},
    {"name": "Patch Panel 2", "device_type": "patch_panel", "rack_unit": 2,  "unit_size": 1, "port_count": 24, "color": "#3a3a4a"},
    {"name": "Patch Panel 3", "device_type": "patch_panel", "rack_unit": 3,  "unit_size": 1, "port_count": 24, "color": "#3a3a4a"},
    {"name": "Patch Panel 4", "device_type": "patch_panel", "rack_unit": 4,  "unit_size": 1, "port_count": 24, "color": "#3a3a4a"},
    {"name": "Patch Panel 5", "device_type": "patch_panel", "rack_unit": 5,  "unit_size": 1, "port_count": 24, "color": "#3a3a4a"},
    {"name": "Patch Panel 6", "device_type": "patch_panel", "rack_unit": 6,  "unit_size": 1, "port_count": 24, "color": "#3a3a4a"},
    {"name": "Patch Panel 7", "device_type": "patch_panel", "rack_unit": 7,  "unit_size": 1, "port_count": 24, "color": "#3a3a4a"},
    {"name": "Patch Panel 8", "device_type": "patch_panel", "rack_unit": 8,  "unit_size": 1, "port_count": 24, "color": "#3a3a4a"},
    # ── Hubs / Unmanaged switches (5 × 1U, 24 ports) ──────────────────
    {"name": "Hub 1",         "device_type": "hub",         "rack_unit": 9,  "unit_size": 1, "port_count": 24, "color": "#2a3a2a"},
    {"name": "Hub 2",         "device_type": "hub",         "rack_unit": 10, "unit_size": 1, "port_count": 24, "color": "#2a3a2a"},
    {"name": "Hub 3",         "device_type": "hub",         "rack_unit": 11, "unit_size": 1, "port_count": 24, "color": "#2a3a2a"},
    {"name": "Hub 4",         "device_type": "hub",         "rack_unit": 12, "unit_size": 1, "port_count": 24, "color": "#2a3a2a"},
    {"name": "Hub 5",         "device_type": "hub",         "rack_unit": 13, "unit_size": 1, "port_count": 24, "color": "#2a3a2a"},
    # ── Managed switches (3 × 1U, 24 ports) ───────────────────────────
    {"name": "SW-01",         "device_type": "switch",      "rack_unit": 14, "unit_size": 1, "port_count": 24, "color": "#1a3a4a"},
    {"name": "SW-02",         "device_type": "switch",      "rack_unit": 15, "unit_size": 1, "port_count": 24, "color": "#1a3a4a"},
    {"name": "SW-03",         "device_type": "switch",      "rack_unit": 16, "unit_size": 1, "port_count": 24, "color": "#1a3a4a"},
    # ── Special equipment ─────────────────────────────────────────────
    {"name": "ISP Switch",    "device_type": "isp",         "rack_unit": 17, "unit_size": 1, "port_count": 24, "color": "#4a3a1a"},
    {"name": "Auth Router",   "device_type": "router",      "rack_unit": 18, "unit_size": 1, "port_count":  8, "color": "#3a1a4a"},
    {"name": "Server-01",     "device_type": "server",      "rack_unit": 19, "unit_size": 2, "port_count":  4, "color": "#1a1a2a"},
    {"name": "Server-02",     "device_type": "server",      "rack_unit": 21, "unit_size": 2, "port_count":  4, "color": "#1a1a2a"},
    {"name": "PoE Switch",    "device_type": "poe_switch",  "rack_unit": 23, "unit_size": 1, "port_count": 24, "color": "#2a4a2a"},
]


def seed_if_empty(db) -> bool:
    if db.query(Device).count() > 0:
        return False
    for d in RACK_DEVICES:
        dev = Device(**d)
        db.add(dev)
        db.flush()
        for i in range(1, d["port_count"] + 1):
            db.add(Port(device_id=dev.id, port_number=i))
    db.commit()
    return True
