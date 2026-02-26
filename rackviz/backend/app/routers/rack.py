from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from ..database import get_db
from ..models import Device, Port, CustomDevice, PortHistory
from ..auth import require_admin

router = APIRouter(prefix="/api", tags=["rack"])


# ─── Schemas ─────────────────────────────────────────────────────────────────

class PortPatch(BaseModel):
    source_type:      Optional[str] = None   # free|mc|custom|manual
    mc_node_id:       Optional[str] = None
    mc_node_name:     Optional[str] = None
    mc_node_online:   Optional[int] = None
    custom_device_id: Optional[int] = None
    manual_label:     Optional[str] = None
    manual_type:      Optional[str] = None
    manual_ip:        Optional[str] = None
    manual_mac:       Optional[str] = None
    manual_desc:      Optional[str] = None
    label:            Optional[str] = None
    description:      Optional[str] = None
    port_type:        Optional[str] = None


class DeviceCreate(BaseModel):
    name:        str
    device_type: str
    rack_unit:   int
    unit_size:   int = 1
    port_count:  int
    port_type:   str = "rj45"
    color:       str = "#2a2a2a"
    notes:       Optional[str] = None
    brand:       Optional[str] = None
    model:       Optional[str] = None


class MoveRequest(BaseModel):
    direction: str  # 'up' | 'down'


class CustomDeviceCreate(BaseModel):
    name:        str
    device_type: str = "other"
    ip:          Optional[str] = None
    mac:         Optional[str] = None
    description: Optional[str] = None
    location:    Optional[str] = None


class RepositionRequest(BaseModel):
    rack_unit: int


class ReorderRequest(BaseModel):
    device_ids: List[int]   # IDs in desired top-to-bottom order


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _port_dict(p: Port) -> dict:
    return {
        "id":             p.id,
        "device_id":      p.device_id,
        "port_number":    p.port_number,
        "port_type":      p.port_type,
        "source_type":    p.source_type or "free",
        "mc_node_id":     p.mc_node_id,
        "mc_node_name":   p.mc_node_name,
        "mc_node_online": p.mc_node_online,
        "custom_device_id": p.custom_device_id,
        "manual_label":   p.manual_label,
        "manual_type":    p.manual_type,
        "manual_ip":      p.manual_ip,
        "manual_mac":     p.manual_mac,
        "manual_desc":    p.manual_desc,
        "label":          p.label,
        "description":    p.description,
    }


def _device_dict(d: Device, ports: list[Port]) -> dict:
    return {
        "id":          d.id,
        "name":        d.name,
        "device_type": d.device_type,
        "rack_unit":   d.rack_unit,
        "unit_size":   d.unit_size,
        "port_count":  d.port_count,
        "port_type":   d.port_type,
        "color":       d.color,
        "notes":       d.notes,
        "brand":       d.brand,
        "model":       d.model,
        "ports":       [_port_dict(p) for p in sorted(ports, key=lambda x: x.port_number)],
    }


# ─── Rack endpoints ───────────────────────────────────────────────────────────

@router.get("/rack")
def get_rack(db: Session = Depends(get_db)):
    devices = db.query(Device).order_by(Device.rack_unit).all()
    result  = []
    for d in devices:
        ports = db.query(Port).filter(Port.device_id == d.id).all()
        result.append(_device_dict(d, ports))
    return result


@router.get("/rack/devices/{device_id}")
def get_device(device_id: int, db: Session = Depends(get_db)):
    d = db.query(Device).filter(Device.id == device_id).first()
    if not d:
        raise HTTPException(404, "Device not found")
    ports = db.query(Port).filter(Port.device_id == device_id).all()
    return _device_dict(d, ports)


@router.post("/rack/devices", dependencies=[Depends(require_admin)])
def add_device(body: DeviceCreate, db: Session = Depends(get_db)):
    d = Device(**body.model_dump())
    db.add(d)
    db.flush()
    for i in range(1, body.port_count + 1):
        db.add(Port(device_id=d.id, port_number=i, port_type=body.port_type))
    db.commit()
    db.refresh(d)
    ports = db.query(Port).filter(Port.device_id == d.id).all()
    return _device_dict(d, ports)


@router.put("/rack/devices/{device_id}", dependencies=[Depends(require_admin)])
def update_device(device_id: int, body: DeviceCreate, db: Session = Depends(get_db)):
    d = db.query(Device).filter(Device.id == device_id).first()
    if not d:
        raise HTTPException(404, "Device not found")
    for k, v in body.model_dump().items():
        setattr(d, k, v)
    db.commit()
    db.refresh(d)
    ports = db.query(Port).filter(Port.device_id == device_id).all()
    return _device_dict(d, ports)


@router.post("/rack/devices/{device_id}/move", dependencies=[Depends(require_admin)])
def move_device(device_id: int, body: MoveRequest, db: Session = Depends(get_db)):
    """Swap position with the adjacent device above or below."""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(404, "Device not found")
    all_devs = sorted(db.query(Device).all(), key=lambda d: d.rack_unit)
    idx = next((i for i, d in enumerate(all_devs) if d.id == device_id), None)
    if idx is None:
        raise HTTPException(404)
    if body.direction == 'up' and idx > 0:
        above = all_devs[idx - 1]
        # Place current device where 'above' was; push 'above' down by current device's size
        new_cur = above.rack_unit
        new_above = above.rack_unit + device.unit_size
        device.rack_unit = new_cur
        above.rack_unit = new_above
    elif body.direction == 'down' and idx < len(all_devs) - 1:
        below = all_devs[idx + 1]
        new_cur = device.rack_unit + below.unit_size
        new_below = device.rack_unit
        device.rack_unit = new_cur
        below.rack_unit = new_below
    else:
        return {"ok": True, "moved": False}
    db.commit()
    return {"ok": True, "moved": True}


@router.delete("/rack/devices", dependencies=[Depends(require_admin)])
def clear_all_devices(db: Session = Depends(get_db)):
    """Delete every device (and cascade-delete their ports) — factory reset."""
    count = db.query(Device).count()
    db.query(Device).delete()
    db.commit()
    return {"ok": True, "deleted": count}


@router.post("/rack/devices/reorder", dependencies=[Depends(require_admin)])
def reorder_devices(body: ReorderRequest, db: Session = Depends(get_db)):
    """Reorder devices and repack: recalculate rack_unit for each device
    based on new order, packing tight from U1 (no gaps)."""
    all_devs = {d.id: d for d in db.query(Device).all()}
    current_u = 1
    for dev_id in body.device_ids:
        dev = all_devs.get(dev_id)
        if dev is None:
            continue
        dev.rack_unit = current_u
        current_u += dev.unit_size
    db.commit()
    return {"ok": True, "total_units": current_u - 1}


@router.delete("/rack/devices/{device_id}", dependencies=[Depends(require_admin)])
def delete_device(device_id: int, db: Session = Depends(get_db)):
    d = db.query(Device).filter(Device.id == device_id).first()
    if not d:
        raise HTTPException(404, "Device not found")
    db.delete(d)
    db.commit()
    return {"ok": True}


# ─── Port endpoints ───────────────────────────────────────────────────────────

@router.get("/ports/{port_id}")
def get_port(port_id: int, db: Session = Depends(get_db)):
    p = db.query(Port).filter(Port.id == port_id).first()
    if not p:
        raise HTTPException(404, "Port not found")
    return _port_dict(p)


@router.patch("/ports/{port_id}", dependencies=[Depends(require_admin)])
def patch_port(port_id: int, body: PortPatch, db: Session = Depends(get_db)):
    p = db.query(Port).filter(Port.id == port_id).first()
    if not p:
        raise HTTPException(404, "Port not found")
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        old = str(getattr(p, k, None) or "")
        new = str(v or "")
        if old != new:
            db.add(PortHistory(port_id=port_id, field=k, old_value=old, new_value=new))
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return _port_dict(p)


@router.get("/ports/{port_id}/history")
def get_port_history(port_id: int, db: Session = Depends(get_db)):
    rows = (db.query(PortHistory)
              .filter(PortHistory.port_id == port_id)
              .order_by(PortHistory.changed_at.desc())
              .limit(50)
              .all())
    return [
        {
            "id":         r.id,
            "field":      r.field,
            "old_value":  r.old_value,
            "new_value":  r.new_value,
            "changed_at": r.changed_at.isoformat() if r.changed_at else None,
        }
        for r in rows
    ]


@router.post("/ports/{port_id}/free", dependencies=[Depends(require_admin)])
def free_port(port_id: int, db: Session = Depends(get_db)):
    p = db.query(Port).filter(Port.id == port_id).first()
    if not p:
        raise HTTPException(404, "Port not found")
    p.source_type    = "free"
    p.mc_node_id     = None
    p.mc_node_name   = None
    p.mc_node_online = 0
    p.custom_device_id = None
    p.manual_label   = None
    p.manual_type    = None
    p.manual_ip      = None
    p.manual_mac     = None
    p.manual_desc    = None
    p.label          = None
    db.commit()
    return _port_dict(p)


# ─── Custom devices ───────────────────────────────────────────────────────────

@router.get("/custom-devices")
def list_custom_devices(db: Session = Depends(get_db)):
    return [
        {"id": d.id, "name": d.name, "device_type": d.device_type,
         "ip": d.ip, "mac": d.mac, "description": d.description, "location": d.location}
        for d in db.query(CustomDevice).all()
    ]


@router.post("/custom-devices", dependencies=[Depends(require_admin)])
def add_custom_device(body: CustomDeviceCreate, db: Session = Depends(get_db)):
    d = CustomDevice(**body.model_dump())
    db.add(d)
    db.commit()
    db.refresh(d)
    return {"id": d.id, "name": d.name, "device_type": d.device_type,
            "ip": d.ip, "mac": d.mac, "description": d.description, "location": d.location}


@router.delete("/custom-devices/{cid}", dependencies=[Depends(require_admin)])
def del_custom_device(cid: int, db: Session = Depends(get_db)):
    d = db.query(CustomDevice).filter(CustomDevice.id == cid).first()
    if not d:
        raise HTTPException(404)
    db.delete(d)
    db.commit()
    return {"ok": True}


# ─── Device repositioning (drag-and-drop) ────────────────────────────────────

@router.post("/rack/devices/{device_id}/reposition", dependencies=[Depends(require_admin)])
def reposition_device(device_id: int, body: RepositionRequest, db: Session = Depends(get_db)):
    """Move device to any rack unit, checking for collisions."""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(404, "Device not found")
    target = body.rack_unit
    if target < 1:
        raise HTTPException(400, "rack_unit must be >= 1")
    target_range = set(range(target, target + device.unit_size))
    for other in db.query(Device).filter(Device.id != device_id).all():
        other_range = set(range(other.rack_unit, other.rack_unit + other.unit_size))
        if target_range & other_range:
            raise HTTPException(409, f"Position {target} occupied by {other.name}")
    device.rack_unit = target
    db.commit()
    return {"ok": True, "rack_unit": device.rack_unit}


# ─── Callout endpoints ────────────────────────────────────────────────────────

class CalloutCreate(BaseModel):
    device_id: int
    text:      str
    color:     str = "yellow"   # yellow|blue|red|green


class CalloutUpdate(BaseModel):
    text:  Optional[str] = None
    color: Optional[str] = None


def _callout_dict(c) -> dict:
    return {"id": c.id, "device_id": c.device_id, "text": c.text, "color": c.color}


@router.get("/callouts")
def list_callouts(db: Session = Depends(get_db)):
    from ..models import Callout
    return [_callout_dict(c) for c in db.query(Callout).all()]


@router.post("/callouts", dependencies=[Depends(require_admin)])
def create_callout(body: CalloutCreate, db: Session = Depends(get_db)):
    from ..models import Callout
    existing = db.query(Callout).filter(Callout.device_id == body.device_id).first()
    if existing:
        raise HTTPException(400, "Callout already exists for this device")
    c = Callout(device_id=body.device_id, text=body.text, color=body.color)
    db.add(c)
    db.commit()
    db.refresh(c)
    return _callout_dict(c)


@router.patch("/callouts/{cid}", dependencies=[Depends(require_admin)])
def update_callout(cid: int, body: CalloutUpdate, db: Session = Depends(get_db)):
    from ..models import Callout
    c = db.query(Callout).filter(Callout.id == cid).first()
    if not c:
        raise HTTPException(404, "Callout not found")
    if body.text is not None:
        c.text = body.text
    if body.color is not None:
        c.color = body.color
    db.commit()
    db.refresh(c)
    return _callout_dict(c)


@router.delete("/callouts/{cid}", dependencies=[Depends(require_admin)])
def delete_callout(cid: int, db: Session = Depends(get_db)):
    from ..models import Callout
    c = db.query(Callout).filter(Callout.id == cid).first()
    if not c:
        raise HTTPException(404, "Callout not found")
    db.delete(c)
    db.commit()
    return {"ok": True}
