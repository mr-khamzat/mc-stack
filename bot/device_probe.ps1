# Device probe: USB printers (ink/toner via vendor WMI) + USB storage + USB devices
# Returns JSON. Runs via MeshCentral RunCommand.

$result = [ordered]@{
    ok        = $true
    updated   = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')
    printers  = @()
    usb_drives= @()
    usb_devices=@()
    debug     = @()
}

# ── VID → vendor map ──────────────────────────────────────────────────────────
$VENDORS = @{
    '03F0' = 'HP'
    '04B8' = 'Epson'
    '04A9' = 'Canon'
}

# ── Helper: scan WMI namespace for supply classes ─────────────────────────────
function Get-InkFromNamespace([string]$ns) {
    $supplies = @()
    try {
        $classes = Get-WmiObject -Namespace $ns -Class '__Class' -ErrorAction Stop |
                   Where-Object { $_ -match 'suppli|ink|toner|cartridge|consumable' }
        foreach ($cls in $classes) {
            try {
                $objs = Get-WmiObject -Namespace $ns -Class $cls -ErrorAction SilentlyContinue
                foreach ($o in $objs) {
                    $level = $o.Level ?? $o.InkLevel ?? $o.TonerLevel ?? $o.CurrentLevel ?? $o.RemainingCapacity
                    $max   = $o.MaxCapacity ?? $o.MaxLevel ?? $o.Capacity ?? 100
                    $name  = $o.Name ?? $o.ColorName ?? $o.MarkerColor ?? $o.Description ?? $cls
                    if ($level -ne $null) {
                        $pct = if ($max -gt 0) { [math]::Round(($level / $max) * 100) } else { $level }
                        $supplies += [ordered]@{ name=[string]$name; level=$pct; raw_level=$level; raw_max=$max }
                    }
                }
            } catch {}
        }
    } catch {}
    return $supplies
}

# ── HP ink via HP WMI ─────────────────────────────────────────────────────────
function Get-HPInk([string]$printerName) {
    $supplies = @()
    $namespaces = @('root\hp\hpsum', 'root\hp', 'root\HP\InkLevel', 'root\HP\MFP')
    foreach ($ns in $namespaces) {
        try {
            $classes = Get-WmiObject -Namespace $ns -List -ErrorAction Stop |
                       Where-Object { $_.Name -imatch 'suppli|ink|toner|consum' }
            foreach ($cls in $classes) {
                try {
                    $objs = Get-WmiObject -Namespace $ns -Class $cls.Name -ErrorAction SilentlyContinue |
                            Where-Object { -not $printerName -or ($_.Name -like "*$($printerName.Split(' ')[0])*") }
                    foreach ($o in $objs) {
                        $level = if ($o.PSObject.Properties['Level'])        { $o.Level }
                                 elseif ($o.PSObject.Properties['InkLevel']) { $o.InkLevel }
                                 elseif ($o.PSObject.Properties['Percent'])  { $o.Percent }
                                 else { $null }
                        if ($level -ne $null) {
                            $max   = if ($o.PSObject.Properties['MaxCapacity']) { $o.MaxCapacity } else { 100 }
                            $color = if ($o.PSObject.Properties['ColorName'])   { $o.ColorName }
                                     elseif ($o.PSObject.Properties['Name'])    { $o.Name }
                                     else { 'Unknown' }
                            $pct = if ($max -gt 0 -and $max -ne 100) { [math]::Round(($level/$max)*100) } else { $level }
                            $supplies += [ordered]@{ name=[string]$color; level=$pct }
                        }
                    }
                } catch {}
            }
            if ($supplies.Count -gt 0) { break }
        } catch {}
    }
    return $supplies
}

# ── Epson: try Status Monitor registry ───────────────────────────────────────
function Get-EpsonInk([string]$printerName) {
    $supplies = @()
    $regPaths = @(
        'HKLM:\SOFTWARE\EPSON\Printer',
        'HKLM:\SOFTWARE\WOW6432Node\EPSON\Printer',
        'HKLM:\SYSTEM\CurrentControlSet\Control\Print\Printers'
    )
    foreach ($regPath in $regPaths) {
        try {
            $keys = Get-ChildItem $regPath -ErrorAction SilentlyContinue
            foreach ($k in $keys) {
                try {
                    $v = Get-ItemProperty $k.PSPath -ErrorAction SilentlyContinue
                    @('InkBlack','InkCyan','InkMagenta','InkYellow','InkLightCyan','InkLightMagenta') |
                    ForEach-Object {
                        if ($v.PSObject.Properties[$_]) {
                            $supplies += [ordered]@{ name=$_.Replace('Ink',''); level=[int]($v.$_) }
                        }
                    }
                } catch {}
            }
        } catch {}
    }
    if ($supplies.Count -eq 0) {
        $supplies = Get-InkFromNamespace 'root\EPSON'
        if ($supplies.Count -eq 0) { $supplies = Get-InkFromNamespace 'root\Epson' }
    }
    return $supplies
}

# ── Canon: WMI namespace ─────────────────────────────────────────────────────
function Get-CanonInk([string]$printerName) {
    $supplies = @()
    try {
        $ns = 'root\cimv2'
        $classes = Get-WmiObject -Namespace $ns -List -ErrorAction SilentlyContinue |
                   Where-Object { $_.Name -imatch 'canon.*ink|canon.*suppli|canon.*toner' }
        foreach ($cls in $classes) {
            try {
                $objs = Get-WmiObject -Namespace $ns -Class $cls.Name -ErrorAction SilentlyContinue
                foreach ($o in $objs) {
                    $level = $o.InkRemaining ?? $o.Level ?? $o.Remaining
                    if ($level -ne $null) {
                        $supplies += [ordered]@{ name=[string]($o.InkColor ?? $o.Name ?? 'Ink'); level=[int]$level }
                    }
                }
            } catch {}
        }
    } catch {}
    if ($supplies.Count -eq 0) {
        $supplies = Get-InkFromNamespace 'root\Canon'
    }
    return $supplies
}

# ── Get all installed printers ────────────────────────────────────────────────
$allPrinters = Get-WmiObject Win32_Printer -ErrorAction SilentlyContinue
$pnpEntities = Get-WmiObject Win32_PnPEntity -ErrorAction SilentlyContinue |
               Where-Object { $_.DeviceID -like 'USB\VID_*' -and
                              ($_.PNPClass -eq 'Printer' -or $_.Name -imatch 'print') }

$result.debug += "total_printers=$($allPrinters.Count) pnp_printers=$($pnpEntities.Count)"

foreach ($p in $allPrinters) {
    if ($p.Name -imatch 'fax|pdf|xps|onenote|microsoft|send to') { continue }

    $pInfo = [ordered]@{
        name       = $p.Name
        driver     = $p.DriverName
        port       = $p.PortName
        status     = switch ([int]$p.PrinterStatus) {
                         1 { 'Other' } 2 { 'Unknown' } 3 { 'Idle' }
                         4 { 'Printing' } 5 { 'Warmup' } 6 { 'Stopped' }
                         7 { 'Offline' } default { "Status $($p.PrinterStatus)" }
                     }
        is_default = [bool]$p.Default
        connection = 'unknown'
        vendor     = 'Unknown'
        pnp_id     = ''
        ink        = @()
        ink_method = 'none'
    }

    # Determine connection type
    if ($p.PortName -match '^USB' -or $p.PortName -match '^COM') {
        $pInfo.connection = 'usb'
    } elseif ($p.PortName -match '^\d{1,3}\.\d' -or $p.PortName -match '^IP_' -or $p.PortName -match 'TCP') {
        $pInfo.connection = 'network'
    }

    # Match PnP entity to printer for USB devices
    $pnp = $pnpEntities | Where-Object {
        $_.Name -like "*$($p.Name.Split(' ')[0])*" -or
        $p.Name -like "*$($_.Name.Split(' ')[0])*"
    } | Select-Object -First 1

    if (-not $pnp -and $pInfo.connection -eq 'usb') {
        $pnp = $pnpEntities | Select-Object -First 1
    }

    if ($pnp) {
        $pInfo.pnp_id = $pnp.DeviceID
        if ($pnp.DeviceID -match 'VID_([0-9A-Fa-f]{4})') {
            $vid = $Matches[1].ToUpper()
            $pInfo.vendor = if ($VENDORS.ContainsKey($vid)) { $VENDORS[$vid] } else { "VID_$vid" }
        }
    } else {
        # Guess vendor from driver/name
        if ($p.DriverName -imatch 'HP|Hewlett')    { $pInfo.vendor = 'HP' }
        elseif ($p.DriverName -imatch 'Epson')      { $pInfo.vendor = 'Epson' }
        elseif ($p.DriverName -imatch 'Canon')      { $pInfo.vendor = 'Canon' }
        elseif ($p.Name -imatch 'HP|Hewlett')       { $pInfo.vendor = 'HP' }
        elseif ($p.Name -imatch 'Epson')            { $pInfo.vendor = 'Epson' }
        elseif ($p.Name -imatch 'Canon')            { $pInfo.vendor = 'Canon' }
    }

    # ── Query ink by vendor ──────────────────────────────────────────────────
    $ink = @()
    switch ($pInfo.vendor) {
        'HP'    { $ink = Get-HPInk $p.Name;    if ($ink.Count -gt 0) { $pInfo.ink_method = 'wmi-hp' } }
        'Epson' { $ink = Get-EpsonInk $p.Name; if ($ink.Count -gt 0) { $pInfo.ink_method = 'registry-epson' } }
        'Canon' { $ink = Get-CanonInk $p.Name; if ($ink.Count -gt 0) { $pInfo.ink_method = 'wmi-canon' } }
    }
    $pInfo.ink = $ink

    $result.printers += $pInfo
}

# ── USB storage drives ────────────────────────────────────────────────────────
$usbDisks = Get-WmiObject Win32_DiskDrive -ErrorAction SilentlyContinue |
            Where-Object { $_.InterfaceType -eq 'USB' }
foreach ($d in $usbDisks) {
    $vols = @()
    $assoc = Get-WmiObject -Query "ASSOCIATORS OF {Win32_DiskDrive.DeviceID='$($d.DeviceID -replace '\\\\','\\')' } WHERE AssocClass=Win32_DiskDriveToDiskPartition" -ErrorAction SilentlyContinue
    foreach ($part in $assoc) {
        $logDisks = Get-WmiObject -Query "ASSOCIATORS OF {Win32_DiskPartition.DeviceID='$($part.DeviceID)'} WHERE AssocClass=Win32_LogicalDiskToPartition" -ErrorAction SilentlyContinue
        foreach ($ld in $logDisks) {
            $vols += [ordered]@{
                letter     = $ld.DeviceID
                label      = $ld.VolumeName
                fs         = $ld.FileSystem
                size_gb    = [math]::Round($ld.Size / 1GB, 1)
                free_gb    = [math]::Round($ld.FreeSpace / 1GB, 1)
                free_pct   = if ($ld.Size -gt 0) { [math]::Round(($ld.FreeSpace / $ld.Size) * 100) } else { 0 }
            }
        }
    }
    $result.usb_drives += [ordered]@{
        model      = $d.Model
        size_gb    = [math]::Round($d.Size / 1GB, 1)
        serial     = $d.SerialNumber.Trim()
        volumes    = $vols
    }
}

# ── All USB devices (non-hub, non-root) ───────────────────────────────────────
$usbAll = Get-PnpDevice -Class USB -ErrorAction SilentlyContinue |
          Where-Object { $_.Status -eq 'OK' -and
                         $_.FriendlyName -notmatch 'Root Hub|Host Controller|Composite Device' }
foreach ($u in $usbAll) {
    $result.usb_devices += [ordered]@{
        name   = $u.FriendlyName
        id     = $u.InstanceId
        status = $u.Status
    }
}
# Also add other connected USB classes
@('HIDClass','PrintQueue','DiskDrive','Image','Media') | ForEach-Object {
    $cls = $_
    Get-PnpDevice -Class $cls -ErrorAction SilentlyContinue |
    Where-Object { $_.Status -eq 'OK' -and $_.InstanceId -like 'USB*' } |
    ForEach-Object {
        if (-not ($result.usb_devices | Where-Object { $_.id -eq $_.InstanceId })) {
            $result.usb_devices += [ordered]@{ name=$_.FriendlyName; id=$_.InstanceId; status=$_.Status }
        }
    }
}

$result | ConvertTo-Json -Depth 6 -Compress
