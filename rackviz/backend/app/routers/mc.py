from fastapi import APIRouter, HTTPException, Depends, Query
from ..auth import require_admin
from ..meshcentral import list_agents, get_agent_details, load_wifi_neighbors

router = APIRouter(prefix="/api/mc", tags=["meshcentral"])


@router.get("/agents", dependencies=[Depends(require_admin)])
async def get_agents():
    """List all MeshCentral agents (for Edit mode port assignment)."""
    agents = await list_agents()
    return [
        {
            "id":     a.get("_id", ""),
            "name":   a.get("name", "Unknown"),
            "group":  a.get("groupname", ""),
            "online": bool(a.get("conn", 0) & 1),
            "os":     a.get("osdesc", ""),
            "ip":     a.get("ip", ""),
            "icon":   a.get("icon", 1),
        }
        for a in agents
        if a.get("_id")
    ]


@router.get("/node", dependencies=[Depends(require_admin)])
async def node_details(id: str = Query(...)):
    """Full device info for the side panel (admin)."""
    data = await get_agent_details(id)
    if not data:
        raise HTTPException(503, "Could not fetch device info from MeshCentral")
    return data


@router.get("/node/public")
async def node_details_public(id: str = Query(...)):
    """Public endpoint — device details for side panel in View mode."""
    data = await get_agent_details(id)
    if not data:
        raise HTTPException(503, "Could not fetch device info from MeshCentral")
    return data


@router.get("/wifi-neighbors")
async def wifi_neighbors(_: dict = Depends(require_admin)):
    """Network neighbors from wifi_clients.json (keenetic probe data)."""
    return load_wifi_neighbors()
