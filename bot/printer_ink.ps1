$ErrorActionPreference = 'SilentlyContinue'

# ── Virtual printer drivers to skip (no ink levels) ──────────────────
$VIRTUAL_DRIVERS = @(
    'anydesk','pdf','xps','microsoft','onenote','fax','cutepdf',
    'docuworks','nitro','adobe pdf','bullzip','pdfcreator','doro',
    'biztalk','generic / text only','send to onenote','print to pdf'
)
function Is-Virtual([string]$driver) {
    $dl = $driver.ToLower()
    foreach ($v in $VIRTUAL_DRIVERS) { if ($dl.Contains($v)) { return $true } }
    return $false
}

# ── BER length encoding ───────────────────────────────────────────────
function eg([int]$n) {
    if ($n -lt 128) { [byte[]]@($n) }
    elseif ($n -lt 256) { [byte[]]@(0x81, $n) }
    else { [byte[]]@(0x82, ($n -shr 8) -band 0xFF, $n -band 0xFF) }
}

# ── BER OID encoding ─────────────────────────────────────────────────
function eo([string]$s) {
    $p = $s.Split('.') | ForEach-Object { [int]$_ }
    $b = [System.Collections.Generic.List[byte]]::new()
    $b.Add([byte](40 * $p[0] + $p[1]))
    for ($i = 2; $i -lt $p.Count; $i++) {
        $v = $p[$i]
        if ($v -lt 128) { $b.Add([byte]$v) }
        else {
            $e = [System.Collections.Generic.List[byte]]::new()
            $e.Insert(0, [byte]($v -band 0x7F)); $v = $v -shr 7
            while ($v -gt 0) {
                $e.Insert(0, [byte](($v -band 0x7F) -bor 0x80)); $v = $v -shr 7
            }
            $b.AddRange($e)
        }
    }
    $b.ToArray()
}

# ── Build SNMP v2c GetRequest packet ─────────────────────────────────
function Make-SnmpGet([string[]]$oids) {
    $vbs = [byte[]]@()
    foreach ($o in $oids) {
        $ob = eo $o; $ol = eg $ob.Length
        $vb = [byte[]](@(0x30) + (eg ($ob.Length + $ol.Length + 3)) + @(0x06) + $ol + $ob + @(0x05, 0x00))
        $vbs += $vb
    }
    $vbl = [byte[]](@(0x30) + (eg $vbs.Length) + $vbs)
    $rid = [byte[]]@(0x02, 0x04, 0x00, 0x00, 0x00, 0x2A)
    $err = [byte[]]@(0x02, 0x01, 0x00, 0x02, 0x01, 0x00)
    $pdD = $rid + $err + $vbl
    $pdu = [byte[]](@(0xA0) + (eg $pdD.Length) + $pdD)
    $cb  = [System.Text.Encoding]::ASCII.GetBytes('public')
    $cm  = [byte[]](@(0x04) + (eg $cb.Length) + $cb)
    $ver = [byte[]]@(0x02, 0x01, 0x01)  # SNMP v2c
    $sd  = $ver + $cm + $pdu
    [byte[]](@(0x30) + (eg $sd.Length) + $sd)
}

# ── BER TLV reader ───────────────────────────────────────────────────
function rt([byte[]]$d, [int]$p) {
    if ($p -ge $d.Length) { return @{ T = 0; V = [byte[]]@(); N = $p } }
    $tag = $d[$p]; $np = $p + 1; $len = 0
    if ($np -ge $d.Length) { return @{ T = $tag; V = [byte[]]@(); N = $np } }
    if     ($d[$np] -lt 0x80) { $len = $d[$np]; $np++ }
    elseif ($d[$np] -eq 0x81) { $len = $d[$np + 1]; $np += 2 }
    elseif ($d[$np] -eq 0x82) { $len = ($d[$np + 1] -shl 8) + $d[$np + 2]; $np += 3 }
    else   { $np++ }
    $end = [Math]::Min($np + $len, $d.Length)
    @{ T = $tag; V = if ($len -gt 0 -and $end -gt $np) { $d[$np..($end - 1)] } else { [byte[]]@() }; N = $end }
}

# ── Parse BER integer (signed) ───────────────────────────────────────
function pi([byte[]]$b) {
    $v = 0L
    foreach ($x in $b) { $v = ($v -shl 8) + [byte]$x }
    if ($b.Length -gt 0 -and $b[0] -ge 0x80) { $v -= [long][Math]::Pow(2, $b.Length * 8) }
    $v
}

# ── SNMP GET: returns hashtable OID -> value ─────────────────────────
function Invoke-SnmpGet([string]$ip, [string[]]$oids) {
    try {
        $pkt = Make-SnmpGet $oids
        $udp = [System.Net.Sockets.UdpClient]::new()
        $udp.Client.ReceiveTimeout = 2000
        [void]$udp.Send($pkt, $pkt.Length, $ip, 161)
        $ep = [System.Net.IPEndPoint]::new([System.Net.IPAddress]::Any, 0)
        $r  = $udp.Receive([ref]$ep)
        $udp.Close()

        # Navigate SNMP response structure
        $seq  = rt $r 0;           $inner = $seq.V;    $p = 0
        $t    = rt $inner $p;      $p = $t.N                    # version
        $t    = rt $inner $p;      $p = $t.N                    # community
        $pduT = rt $inner $p;      $pduD = $pduT.V;    $p = 0
        $t    = rt $pduD $p;       $p = $t.N                    # request-id
        $es   = rt $pduD $p;       $p = $es.N                   # error-status
        if ((pi $es.V) -ne 0) { return @{} }                    # request-level error
        $t    = rt $pduD $p;       $p = $t.N                    # error-index
        $vbl  = rt $pduD $p;       $vD = $vbl.V; $vp = 0; $idx = 0
        $res  = @{}
        while ($vp -lt $vD.Length -and $idx -lt $oids.Length) {
            $vb  = rt $vD $vp; $vp = $vb.N
            $vc  = $vb.V; $p4 = 0
            $t   = rt $vc $p4; $p4 = $t.N       # OID (skip)
            $val = rt $vc $p4
            $tag = $val.T; $bytes = $val.V
            # 0x80=noSuchObject, 0x81=noSuchInstance, 0x82=endOfMibView → null
            if     ($tag -eq 0x02 -or ($tag -ge 0x41 -and $tag -le 0x46)) { $res[$oids[$idx]] = pi $bytes }
            elseif ($tag -eq 0x04 -or $tag -eq 0x0C)                       { $res[$oids[$idx]] = [System.Text.Encoding]::UTF8.GetString($bytes).Trim([char]0) }
            else   { $res[$oids[$idx]] = $null }
            $idx++
        }
        return $res
    } catch { return @{} }
}

# ── Get printer port IP ───────────────────────────────────────────────
function Get-PrinterIP([string]$portName) {
    try {
        $port = Get-PrinterPort -Name $portName 2>$null
        if ($port -and $port.PrinterHostAddress) { return $port.PrinterHostAddress }
    } catch {}
    return $null
}

# ── Query ink/toner supplies via SNMP ────────────────────────────────
function Get-PrinterSupplies([string]$ip) {
    $pfx  = '1.3.6.1.2.1.43.11.1.1'
    $oids = @()
    for ($i = 1; $i -le 8; $i++) {
        $oids += "$pfx.6.1.$i"   # prtMarkerSuppliesDescription
        $oids += "$pfx.8.1.$i"   # prtMarkerSuppliesCurrentLevel
        $oids += "$pfx.9.1.$i"   # prtMarkerSuppliesMaxCapacity
    }
    $snmp = Invoke-SnmpGet $ip $oids
    $out  = @()
    for ($i = 1; $i -le 8; $i++) {
        $desc = $snmp["$pfx.6.1.$i"]
        $cur  = $snmp["$pfx.8.1.$i"]
        $max  = $snmp["$pfx.9.1.$i"]
        if (-not $desc -or $desc -eq '') { continue }
        # Filter non-printable (corrupted response)
        if ($desc -match '[^\x20-\x7E\u0400-\u04FF]') { continue }
        if ($null -eq $cur -or $null -eq $max) { continue }
        if ($max -le 0) { continue }   # unlimited or unknown capacity
        $pct = if ($cur -ge 0) { [int][Math]::Round([double]$cur * 100.0 / [double]$max) } else { -1 }
        $out += @{ desc = [string]$desc; cur = [long]$cur; max = [long]$max; pct = $pct }
    }
    return $out
}

# ── Main ─────────────────────────────────────────────────────────────
$allPrinters = Get-Printer 2>$null
$result = @()

foreach ($pr in $allPrinters) {
    # Skip garbled names — OEM-encoding artifacts like "(ª®¯¨)" = "(копия)" in CP437
    # Latin Extended block U+0080..U+00FF in printer names = corrupted copy entries
    if ($pr.Name -match '[\u0080-\u00FF]') { continue }

    $obj = @{
        Name          = $pr.Name
        DriverName    = $pr.DriverName
        PortName      = $pr.PortName
        PrinterStatus = [int]$pr.PrinterStatus
        Shared        = [bool]$pr.Shared
        Default       = [bool]($pr.Attributes -band 4)
        Supplies      = @()
        IsVirtual     = Is-Virtual $pr.DriverName
    }

    if (-not $obj.IsVirtual) {
        $ip = Get-PrinterIP $pr.PortName
        if ($ip) {
            $obj.PrinterIP = $ip
            $obj.Supplies  = Get-PrinterSupplies $ip
        }
    }
    $result += $obj
}

# Force array output — ConvertTo-Json on explicit array avoids PS5 {value:[],Count:N} wrapping
ConvertTo-Json -InputObject @($result) -Depth 5 -Compress
