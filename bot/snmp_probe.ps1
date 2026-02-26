# snmp_probe.ps1 — Minimal SNMP v1 GET probe for local router
# Runs via MeshCentral RunCommand on a Windows PC in the target LAN.
# Placeholders replaced by bot before execution.

param(
    [string]$RouterIP  = "",
    [string]$Community = "SNMP_COMMUNITY_PLACEHOLDER"
)

# ── Auto-detect default gateway ──────────────────────────────────────
if (-not $RouterIP) {
    try {
        $gw = (Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction Stop |
               Sort-Object RouteMetric | Select-Object -First 1).NextHop
        if ($gw) { $RouterIP = $gw } else { throw "no route" }
    } catch {
        Write-Output ('{"error":"cannot detect gateway: ' + $_.Exception.Message + '"}')
        exit 1
    }
}

# ── Minimal SNMP v1 GET library ──────────────────────────────────────

function Encode-BerLength([int]$n) {
    if ($n -lt 128)  { return [byte[]]@($n) }
    if ($n -lt 256)  { return [byte[]]@(0x81, $n) }
    return [byte[]]@(0x82, [byte]($n -shr 8), [byte]($n -band 0xFF))
}

function New-BerTLV([byte]$tag, [byte[]]$value) {
    [byte[]]$len = Encode-BerLength $value.Length
    return [byte[]]( @($tag) + $len + $value )
}

function Encode-OID([string]$dotted) {
    $parts = $dotted.TrimStart('.').Split('.') | ForEach-Object { [uint32]$_ }
    $bytes = [System.Collections.Generic.List[byte]]::new()
    $bytes.Add( [byte]($parts[0] * 40 + $parts[1]) )
    for ($i = 2; $i -lt $parts.Count; $i++) {
        $v = $parts[$i]
        if ($v -lt 128) { $bytes.Add([byte]$v) }
        else {
            $sub = [System.Collections.Generic.List[byte]]::new()
            while ($v -gt 0) { $sub.Insert(0, [byte]($v -band 0x7F)); $v = $v -shr 7 }
            for ($j = 0; $j -lt $sub.Count - 1; $j++) { $bytes.Add( [byte]($sub[$j] -bor 0x80) ) }
            $bytes.Add($sub[$sub.Count - 1])
        }
    }
    return $bytes.ToArray()
}

function Decode-BerTLV([byte[]]$data, [int]$pos) {
    $tag = $data[$pos++]
    $len = [int]$data[$pos++]
    if ($len -band 0x80) {
        $nb = $len -band 0x7F; $len = 0
        for ($k = 0; $k -lt $nb; $k++) { $len = ($len -shl 8) + $data[$pos++] }
    }
    return @{ tag = $tag; len = $len; vs = $pos; next = ($pos + $len) }
}

function Get-SnmpV1 {
    param([string]$Ip, [string]$Comm, [string]$OID)
    $oidBytes = Encode-OID $OID
    $oidTlv   = New-BerTLV 0x06 $oidBytes
    $nullTlv  = [byte[]]@(0x05, 0x00)
    $varbind  = New-BerTLV 0x30 ([byte[]]($oidTlv + $nullTlv))
    $vbl      = New-BerTLV 0x30 $varbind
    $reqId    = New-BerTLV 0x02 @([byte]0x01)
    $errSt    = New-BerTLV 0x02 @([byte]0x00)
    $errIdx   = New-BerTLV 0x02 @([byte]0x00)
    $pdu      = New-BerTLV 0xA0 ([byte[]]($reqId + $errSt + $errIdx + $vbl))
    $ver      = New-BerTLV 0x02 @([byte]0x00)
    $commTlv  = New-BerTLV 0x04 ([System.Text.Encoding]::ASCII.GetBytes($Comm))
    $msg      = New-BerTLV 0x30 ([byte[]]($ver + $commTlv + $pdu))

    try {
        $udp    = [System.Net.Sockets.UdpClient]::new()
        $udp.Client.ReceiveTimeout = 2000
        $remote = [System.Net.IPEndPoint]::new([System.Net.IPAddress]::Parse($Ip), 161)
        [void]$udp.Send($msg, $msg.Length, $remote)
        $resp   = $udp.Receive([ref]$remote)
        $udp.Close()
    } catch { return $null }

    try {
        $p    = 0
        $seq  = Decode-BerTLV $resp $p; $p = $seq.vs
        $ver2 = Decode-BerTLV $resp $p; $p = $ver2.next
        $cm   = Decode-BerTLV $resp $p; $p = $cm.next
        $pdu2 = Decode-BerTLV $resp $p; $p = $pdu2.vs
        $rid  = Decode-BerTLV $resp $p; $p = $rid.next
        $es   = Decode-BerTLV $resp $p
        if ($resp[$es.vs] -ne 0) { return $null }
        $p    = $es.next
        $ei   = Decode-BerTLV $resp $p; $p = $ei.next
        $vbl2 = Decode-BerTLV $resp $p; $p = $vbl2.vs
        $vb2  = Decode-BerTLV $resp $p; $p = $vb2.vs
        $oid2 = Decode-BerTLV $resp $p; $p = $oid2.next
        $val  = Decode-BerTLV $resp $p
        if ($val.len -eq 0) { return $null }
        $vd   = $resp[$val.vs..($val.next - 1)]
        switch ($val.tag) {
            0x04 { return [System.Text.Encoding]::UTF8.GetString($vd).Trim([char]0) }  # OCTET STRING
            0x02 {  # INTEGER (signed)
                $n = [long]0
                if ($vd[0] -band 0x80) { $n = -1 }
                foreach ($b in $vd) { $n = ($n -shl 8) -bor [long]$b }
                return $n
            }
            { $_ -in @(0x40, 0x41, 0x42, 0x43, 0x47) } {  # IpAddr, Counter32, Gauge32, TimeTicks, Counter64
                $n = [uint64]0
                foreach ($b in $vd) { $n = ($n -shl 8) -bor [uint64]$b }
                return $n
            }
            default { return $null }
        }
    } catch { return $null }
}

# ── Query OIDs ────────────────────────────────────────────────────────
$ts = [System.DateTimeOffset]::UtcNow.ToUnixTimeSeconds()

$sysName   = Get-SnmpV1 $RouterIP $Community "1.3.6.1.2.1.1.5.0"
$sysDescr  = Get-SnmpV1 $RouterIP $Community "1.3.6.1.2.1.1.1.0"
$sysUpTime = Get-SnmpV1 $RouterIP $Community "1.3.6.1.2.1.1.3.0"
$cpuLoad   = Get-SnmpV1 $RouterIP $Community "1.3.6.1.2.1.25.3.3.1.2.1"
$ifIn1     = Get-SnmpV1 $RouterIP $Community "1.3.6.1.2.1.2.2.1.10.1"
$ifOut1    = Get-SnmpV1 $RouterIP $Community "1.3.6.1.2.1.2.2.1.16.1"
$ifIn2     = Get-SnmpV1 $RouterIP $Community "1.3.6.1.2.1.2.2.1.10.2"
$ifOut2    = Get-SnmpV1 $RouterIP $Community "1.3.6.1.2.1.2.2.1.16.2"
$ifIn3     = Get-SnmpV1 $RouterIP $Community "1.3.6.1.2.1.2.2.1.10.3"
$ifOut3    = Get-SnmpV1 $RouterIP $Community "1.3.6.1.2.1.2.2.1.16.3"

if ($null -eq $sysName -and $null -eq $sysDescr) {
    Write-Output ('{"error":"SNMP no response at ' + $RouterIP + ' (community=' + $Community + ')"}')
    exit 0
}

# Uptime formatting
$uptimeStr = ""; $uptimeSec = 0
if ($null -ne $sysUpTime) {
    $uptimeSec = [long]([uint64]$sysUpTime / 100)
    $d = [int]($uptimeSec / 86400); $h = [int](($uptimeSec % 86400) / 3600); $m = [int](($uptimeSec % 3600) / 60)
    $uptimeStr = if ($d -gt 0) { "${d}д ${h}ч ${m}м" } else { "${h}ч ${m}м" }
}

$out = [ordered]@{
    router      = $RouterIP
    ts          = $ts
    sys_name    = if ($sysName)  { "$sysName"  } else { "" }
    sys_descr   = if ($sysDescr) { "$sysDescr" } else { "" }
    uptime      = $uptimeStr
    uptime_sec  = $uptimeSec
    cpu_pct     = if ($null -ne $cpuLoad) { [int]$cpuLoad } else { -1 }
    if1_in      = if ($null -ne $ifIn1)  { [long]$ifIn1  } else { -1 }
    if1_out     = if ($null -ne $ifOut1) { [long]$ifOut1 } else { -1 }
    if2_in      = if ($null -ne $ifIn2)  { [long]$ifIn2  } else { -1 }
    if2_out     = if ($null -ne $ifOut2) { [long]$ifOut2 } else { -1 }
    if3_in      = if ($null -ne $ifIn3)  { [long]$ifIn3  } else { -1 }
    if3_out     = if ($null -ne $ifOut3) { [long]$ifOut3 } else { -1 }
}

Write-Output ($out | ConvertTo-Json -Compress)
