# Temperature & Load Probe for MeshCentral Bot
# Returns JSON: temps[], cpu_load_pct, hostname

$result = @{ hostname = $env:COMPUTERNAME; temps = @(); cpu_load_pct = 0 }

# CPU load
try {
    $load = (Get-WmiObject Win32_Processor -ErrorAction Stop |
             Measure-Object -Property LoadPercentage -Average).Average
    $result.cpu_load_pct = [math]::Round($load)
} catch {}

# Thermal zones (MSAcpi) — works on most ACPI-compliant hardware
try {
    $zones = Get-WmiObject -Namespace "root\wmi" `
                           -Class "MSAcpi_ThermalZoneTemperature" `
                           -ErrorAction Stop
    foreach ($z in $zones) {
        $c = [math]::Round($z.CurrentTemperature / 10 - 273.15, 1)
        if ($c -gt 5 -and $c -lt 130) {
            $result.temps += @{
                zone   = [string]$z.InstanceName
                temp_c = $c
            }
        }
    }
} catch {
    $result.acpi_error = $_.Exception.Message
}

# Fallback: Open Hardware Monitor / LibreHardwareMonitor via WMI namespace
if ($result.temps.Count -eq 0) {
    try {
        $ohm = Get-WmiObject -Namespace "root\LibreHardwareMonitor" `
                             -Class Sensor `
                             -Filter "SensorType='Temperature'" `
                             -ErrorAction Stop
        foreach ($s in $ohm) {
            if ($s.Value -gt 5 -and $s.Value -lt 130) {
                $result.temps += @{ zone = [string]$s.Name; temp_c = [math]::Round($s.Value, 1) }
            }
        }
    } catch {}
}

if ($result.temps.Count -eq 0) {
    $result.no_sensor = $true
}

$result | ConvertTo-Json -Depth 3 -Compress
