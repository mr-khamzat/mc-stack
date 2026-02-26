from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint, ForeignKey, func, CheckConstraint, Text
from .database import Base


class Device(Base):
    """Equipment in the rack (patch panel, switch, server, etc.)"""
    __tablename__ = "devices"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String, nullable=False)
    device_type = Column(String, nullable=False)   # patch_panel|switch|hub|router|server|poe_switch|isp
    rack_unit   = Column(Integer, nullable=False)  # position from top (1 = top)
    unit_size   = Column(Integer, default=1)       # height in rack units
    port_count  = Column(Integer, nullable=False)
    port_type   = Column(String, default="rj45")   # rj45|sfp|mixed
    color       = Column(String, default="#2a2a2a")
    notes       = Column(Text, nullable=True)       # free-text notes shown on device face
    brand       = Column(String, nullable=True)     # TP-Link, Cisco, Keenetic, SNR, MikroTik…
    model       = Column(String, nullable=True)     # TL-SG1024DE, Catalyst 2960-24T…
    created_at  = Column(DateTime, server_default=func.now())


class Port(Base):
    """Individual port on a rack device."""
    __tablename__ = "ports"

    id             = Column(Integer, primary_key=True, index=True)
    device_id      = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    port_number    = Column(Integer, nullable=False)
    port_type      = Column(String, default="rj45")    # rj45|sfp|uplink

    # What's connected — one of three source types
    source_type    = Column(String, default="free")    # free|mc|custom|manual
    mc_node_id     = Column(String)                    # MeshCentral node ID
    mc_node_name   = Column(String)                    # cached MC name
    mc_node_online = Column(Integer, default=0)        # cached online flag

    custom_device_id = Column(Integer, ForeignKey("custom_devices.id", ondelete="SET NULL"), nullable=True)
    manual_label   = Column(String)                    # free-text label for manual entries
    manual_type    = Column(String)                    # switch|router|ap|printer|camera|other
    manual_ip      = Column(String)
    manual_mac     = Column(String)
    manual_desc    = Column(String)

    label          = Column(String)                    # user display label (overrides all)
    description    = Column(String)                    # notes

    updated_at     = Column(DateTime, onupdate=func.now())

    __table_args__ = (UniqueConstraint("device_id", "port_number"),)



class PortHistory(Base):
    """Audit log of port field changes."""
    __tablename__ = "port_history"

    id         = Column(Integer, primary_key=True, index=True)
    port_id    = Column(Integer, ForeignKey("ports.id", ondelete="CASCADE"), nullable=False, index=True)
    field      = Column(String, nullable=False)
    old_value  = Column(Text)
    new_value  = Column(Text)
    changed_at = Column(DateTime, server_default=func.now())


class Callout(Base):
    """Floating annotation callout attached to a rack device."""
    __tablename__ = "callouts"

    id         = Column(Integer, primary_key=True, index=True)
    device_id  = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, unique=True)
    text       = Column(Text, nullable=False)
    color      = Column(String, default="yellow")  # yellow|blue|red|green
    created_at = Column(DateTime, server_default=func.now())


class CustomDevice(Base):
    """Non-MC device manually added (router, switch, AP, printer, etc.)"""
    __tablename__ = "custom_devices"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String, nullable=False)
    device_type = Column(String, default="other")  # switch|router|ap|printer|camera|other
    ip          = Column(String)
    mac         = Column(String)
    description = Column(String)
    location    = Column(String)
    created_at  = Column(DateTime, server_default=func.now())
