# Hardware Inventory Probe for MeshCentral Bot
# Returns JSON: cpu, ram, disks, system, network
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$result = @{}

try {
    $cs   = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
    $bios = Get-CimInstance Win32_BIOS           -ErrorAction Stop
    $os   = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop

    $result.hostname     = $env:COMPUTERNAME
    $result.manufacturer = [string]$cs.Manufacturer
    $result.model        = [string]$cs.Model
    $result.serial       = [string]$bios.SerialNumber
    $result.os_name      = [string]$os.Caption
    $result.os_arch      = [string]$os.OSArchitecture
    $result.os_version   = [string]$os.Version
    try { $result.os_install = $os.InstallDate.ToString("yyyy-MM-dd") } catch { $result.os_install = "" }
    try { $result.last_boot  = $os.LastBootUpTime.ToString("yyyy-MM-dd HH:mm") } catch { $result.last_boot = "" }
} catch {
    $result.error = "System: $($_.Exception.Message)"
}

# CPU
try {
    $cpu = Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1
    $result.cpu_name    = ($cpu.Name -replace '\s+', ' ').Trim()
    $result.cpu_cores   = [int]$cpu.NumberOfCores
    $result.cpu_threads = [int]$cpu.NumberOfLogicalProcessors
    $result.cpu_mhz     = [int]$cpu.MaxClockSpeed
} catch {
    $result.cpu_name = "n/a"
}

# RAM
try {
    $cs2 = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
    $result.ram_total_gb = [math]::Round($cs2.TotalPhysicalMemory / 1GB, 1)
    $dimms = @(Get-CimInstance Win32_PhysicalMemory -ErrorAction SilentlyContinue)
    $result.ram_slots = $dimms.Count
    $result.ram_modules = @($dimms | ForEach-Object {
        $cap = if ($_.Capacity) { [math]::Round($_.Capacity/1GB) } else { 0 }
        "$($cap)GB"
    })
} catch {
    $result.ram_total_gb = 0
}

# Disks
$disks = @()
try {
    $drives = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" -ErrorAction Stop
    foreach ($d in $drives) {
        $free_gb = if ($d.FreeSpace) { [math]::Round($d.FreeSpace / 1GB, 1) } else { 0.0 }
        $size_gb = if ($d.Size)      { [math]::Round($d.Size / 1GB, 1) }      else { 0.0 }
        $pct     = if ($d.Size -gt 0) { [math]::Round((($d.Size - $d.FreeSpace) / $d.Size) * 100) } else { 0 }

        # Detect SSD vs HDD (best-effort)
        $dtype = "HDD"
        try {
            $msft = Get-PhysicalDisk -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -ne $null } | Select-Object -First 1
            if ($msft -and $msft.MediaType -eq "SSD") { $dtype = "SSD" }
        } catch {}
        try {
            $perf = Get-Disk -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($perf -and ($perf.BusType -eq "NVMe" -or $perf.BusType -eq "SATA")) {
                $model = [string]$perf.FriendlyName
                if ($model -match "SSD|NVMe|M\.2|Kingston|Samsung\s*\d{3}[Ee]|WD\s+Green|WD\s+Blue") { $dtype = "SSD" }
            }
        } catch {}

        $disks += @{
            letter   = [string]$d.DeviceID
            label    = [string]$d.VolumeName
            size_gb  = $size_gb
            free_gb  = $free_gb
            used_pct = $pct
            dtype    = $dtype
        }
    }
} catch {}
$result.disks = $disks

# GPU
try {
    $gpu = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | Select-Object -First 1
    $result.gpu = if ($gpu) { ($gpu.Name -replace '\s+', ' ').Trim() } else { "" }
} catch { $result.gpu = "" }

# Network (first 3 enabled adapters)
try {
    $nics = @(Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled = TRUE" -ErrorAction Stop |
              Select-Object -First 3 |
              ForEach-Object { "$($_.Description): IP=$($_.IPAddress[0])  MAC=$($_.MACAddress)" })
    $result.network = $nics
} catch { $result.network = @() }

$result | ConvertTo-Json -Depth 3 -Compress
