"""PDF export — GET /api/rack/export/pdf
Generates a professional PDF documentation of the rack layout."""

import io
import os
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Device, Port

router = APIRouter(prefix="/api", tags=["export"])

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
_jinja_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=True)


def _port_dict_simple(p: Port) -> dict:
    return {
        "id":             p.id,
        "port_number":    p.port_number,
        "port_type":      p.port_type or "rj45",
        "source_type":    p.source_type or "free",
        "mc_node_name":   p.mc_node_name,
        "mc_node_online": p.mc_node_online or 0,
        "manual_label":   p.manual_label,
        "manual_ip":      p.manual_ip,
        "manual_mac":     p.manual_mac,
        "manual_desc":    p.manual_desc,
        "label":          p.label,
        "description":    p.description,
    }


def _build_dynamic_recs(devices: list[dict]) -> list[dict]:
    """Generate context-aware recommendations based on current rack state."""
    recs = []
    total_ports = sum(len(d["ports"]) for d in devices)
    occupied = sum(1 for d in devices for p in d["ports"] if p["source_type"] != "free")
    mc_offline = sum(
        1 for d in devices for p in d["ports"]
        if p["source_type"] == "mc" and p["mc_node_online"] != 1
    )
    no_label = sum(
        1 for d in devices for p in d["ports"]
        if p["source_type"] != "free"
        and not (p["mc_node_name"] or p["manual_label"] or p["label"])
    )
    no_notes = sum(1 for d in devices if not d.get("notes"))
    fill_pct = round(occupied / total_ports * 100) if total_ports else 0

    if fill_pct >= 80:
        recs.append({
            "kind": "warn",
            "title": f"Высокая заполненность портов: {fill_pct}%",
            "desc": (
                "Заполненность стойки превышает 80%. Рекомендуется планировать "
                "расширение — добавить коммутатор или заменить существующий "
                "на модель с большим числом портов."
            ),
        })
    elif fill_pct >= 60:
        recs.append({
            "kind": "warn",
            "title": f"Заполненность портов: {fill_pct}% — планируйте расширение",
            "desc": (
                "При такой заполненности рекомендуется заранее зарезервировать "
                "свободные порты и убедиться, что в стойке есть место для новых устройств."
            ),
        })
    else:
        recs.append({
            "kind": "ok",
            "title": f"Нормальная заполненность портов: {fill_pct}%",
            "desc": (
                f"Занято {occupied} из {total_ports} портов. Достаточный резерв "
                "для подключения новых устройств без расширения инфраструктуры."
            ),
        })

    if mc_offline > 0:
        recs.append({
            "kind": "warn",
            "title": f"Офлайн-узлы MeshCentral: {mc_offline}",
            "desc": (
                f"{mc_offline} портов назначены узлам MeshCentral, которые в данный момент "
                "не в сети. Проверьте питание устройств, сетевые подключения и статус "
                "агентов MeshCentral."
            ),
        })

    if no_label > 0:
        recs.append({
            "kind": "warn",
            "title": f"Порты без описания: {no_label}",
            "desc": (
                f"{no_label} занятых портов не имеют метки или описания. "
                "Заполните поля Label и Description — это критично при устранении неисправностей."
            ),
        })

    if no_notes > 0:
        recs.append({
            "kind": "info",
            "title": f"Устройства без заметок: {no_notes}",
            "desc": (
                f"{no_notes} устройств не имеют заметок. Добавьте в поле Notes "
                "полезную информацию: серийный номер, дату установки, гарантию, "
                "контакт ответственного."
            ),
        })

    return recs


@router.get("/rack/export/pdf", summary="Экспорт стойки в PDF")
def export_pdf(db: Session = Depends(get_db)):
    # WeasyPrint import is deferred so the app starts even if not yet installed
    try:
        from weasyprint import HTML as WeasyHTML
    except ImportError:
        from fastapi import HTTPException
        raise HTTPException(500, "WeasyPrint not installed in this environment")

    # ── Fetch data ─────────────────────────────────────────────────────────
    db_devices = db.query(Device).order_by(Device.rack_unit).all()
    devices = []
    for d in db_devices:
        ports = db.query(Port).filter(Port.device_id == d.id).order_by(Port.port_number).all()
        devices.append({
            "id":          d.id,
            "name":        d.name,
            "device_type": d.device_type,
            "rack_unit":   d.rack_unit,
            "unit_size":   d.unit_size,
            "port_count":  d.port_count,
            "port_type":   d.port_type,
            "color":       d.color or "#2a2a2a",
            "notes":       d.notes,
            "brand":       d.brand,
            "model":       d.model,
            "ports":       [_port_dict_simple(p) for p in ports],
        })

    # ── Compute stats ──────────────────────────────────────────────────────
    total_ports    = sum(d["port_count"] for d in devices)
    occupied_ports = sum(
        1 for d in devices for p in d["ports"] if p["source_type"] != "free"
    )
    mc_online      = sum(
        1 for d in devices for p in d["ports"]
        if p["source_type"] == "mc" and p["mc_node_online"] == 1
    )
    total_units    = sum(d["unit_size"] for d in devices)

    stats = {
        "total_devices":  len(devices),
        "total_units":    total_units,
        "total_ports":    total_ports,
        "occupied_ports": occupied_ports,
        "free_ports":     total_ports - occupied_ports,
        "mc_online":      mc_online,
    }

    # ── Render template ────────────────────────────────────────────────────
    generated_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    dynamic_recs = _build_dynamic_recs(devices)

    template = _jinja_env.get_template("rack_report.html")
    html_content = template.render(
        devices=devices,
        stats=stats,
        dynamic_recs=dynamic_recs,
        generated_at=generated_at,
    )

    # ── WeasyPrint → PDF ───────────────────────────────────────────────────
    pdf_bytes = WeasyHTML(string=html_content).write_pdf()

    filename = f"rack_{datetime.now().strftime('%Y-%m-%d')}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
