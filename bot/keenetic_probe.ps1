# Network client probe — Keenetic API (primary) + Get-NetNeighbor (fallback)
# Placeholders replaced by bot at runtime: ROUTER_LOGIN, ROUTER_PASSWORD

$login = 'ROUTER_LOGIN'
$pass  = 'ROUTER_PASSWORD'

$debug = @()

# ── Detect gateway ────────────────────────────────────────────────────────────
$gw = $null
try {
    $gw = (Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
           Where-Object { $_.NextHop -ne '0.0.0.0' -and $_.NextHop -ne '' -and $_.NextHop -ne '::' } |
           Sort-Object RouteMetric | Select-Object -First 1).NextHop
} catch {}
if (-not $gw) {
    foreach ($line in (ipconfig 2>$null)) {
        if ($line -match ':\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})') {
            $ip = $Matches[1]
            if ($ip -ne '0.0.0.0' -and $ip -ne '127.0.0.1') { $gw = $ip; break }
        }
    }
}
if (-not $gw) {
    [ordered]@{ ok=$false; error='no gateway'; debug=@() } | ConvertTo-Json -Compress; exit
}
$debug += "gw=$gw"
$subnet = $gw -replace '\.\d+$', ''

# ── MD5 helper ────────────────────────────────────────────────────────────────
function Get-MD5([string]$text) {
    $md5   = [System.Security.Cryptography.MD5]::Create()
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($text)
    return ($md5.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') }) -join ''
}

# ── Read response body from WebException (robust) ────────────────────────────
function Read-ErrorBody([System.Net.WebException]$ex) {
    $er = $ex.Response
    if (-not $er) { return '' }
    try {
        $s = $er.GetResponseStream()
        $buf = New-Object byte[] 8192
        $n = $s.Read($buf, 0, 8192)
        $s.Close()
        if ($n -gt 0) { return [System.Text.Encoding]::UTF8.GetString($buf, 0, $n) }
    } catch {}
    return ''
}

# ── HTTP request helper (returns body string or $null on error) ───────────────
function Invoke-Http {
    param(
        [string]$Url,
        [string]$Method = 'GET',
        [byte[]]$Body = $null,
        [string]$ContentType = 'application/json',
        [System.Net.CookieContainer]$Cookies = $null,
        [hashtable]$Headers = @{},
        [int]$Timeout = 8000
    )
    try {
        $req = [System.Net.HttpWebRequest]::Create($Url)
        $req.Method      = $Method
        $req.Timeout     = $Timeout
        if ($Cookies) { $req.CookieContainer = $Cookies }
        foreach ($k in $Headers.Keys) { $req.Headers[$k] = $Headers[$k] }
        if ($Body) {
            $req.ContentType   = $ContentType
            $req.ContentLength = $Body.Length
            $s = $req.GetRequestStream()
            $s.Write($Body, 0, $Body.Length)
            $s.Close()
        }
        $resp = $req.GetResponse()
        $text = (New-Object System.IO.StreamReader($resp.GetResponseStream())).ReadToEnd()
        $resp.Close()
        return $text
    } catch [System.Net.WebException] {
        $sc = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
        return "##ERR:$sc##" + (Read-ErrorBody $_)
    } catch {
        return $null
    }
}

# ── Keenetic API ──────────────────────────────────────────────────────────────
$hotspot  = $null
$dhcp_map = @{}
$method   = 'neighbor+nbtstat'
$cookies  = New-Object System.Net.CookieContainer
$base     = "http://$gw"

# ── Step 0: Hotspot without auth ──────────────────────────────────────────────
$r0 = Invoke-Http "$base/rci/show/ip/hotspot" -Cookies $cookies -Timeout 6000
if ($r0 -and -not $r0.StartsWith('##ERR:')) {
    $debug += "hotspot_noauth=200 len=$($r0.Length)"
    try {
        $p0 = $r0 | ConvertFrom-Json
        if ($p0 -is [array] -and $p0.Count -gt 0) {
            $hotspot = $p0; $method = 'keenetic-api-noauth'
        } elseif ($p0.PSObject.Properties['host'] -and $p0.host.Count -gt 0) {
            $hotspot = $p0.host; $method = 'keenetic-api-noauth'
        }
    } catch {}
} else {
    $sc0 = if ($r0) { ($r0 -replace '##ERR:(\d+)##.*','$1') } else { '0' }
    $debug += "hotspot_noauth=$sc0"
}

# ── Step 1: HTTP Basic auth (fastest, many Keenetic models support it) ────────
if (-not $hotspot -and $login -ne '' -and $pass -ne '') {
    $cred = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes("${login}:${pass}"))
    $r1b = Invoke-Http "$base/rci/show/ip/hotspot" -Cookies $cookies -Timeout 8000 `
           -Headers @{ Authorization = "Basic $cred" }
    if ($r1b -and -not $r1b.StartsWith('##ERR:')) {
        $debug += "hotspot_basic=200 len=$($r1b.Length)"
        try {
            $p1b = $r1b | ConvertFrom-Json
            if ($p1b -is [array] -and $p1b.Count -gt 0) {
                $hotspot = $p1b; $method = 'keenetic-api-basic'
            } elseif ($p1b.PSObject.Properties['host'] -and $p1b.host.Count -gt 0) {
                $hotspot = $p1b.host; $method = 'keenetic-api-basic'
            }
        } catch {}
        # Get DHCP with Basic auth
        if ($hotspot) {
            $rDhcp = Invoke-Http "$base/rci/show/ip/dhcp/bindings" -Cookies $cookies -Timeout 6000 `
                     -Headers @{ Authorization = "Basic $cred" }
            if ($rDhcp -and -not $rDhcp.StartsWith('##ERR:')) {
                try {
                    foreach ($b in ($rDhcp | ConvertFrom-Json)) {
                        $bm = ([string]($b.mac -replace '-',':')).ToLower()
                        $bn = [string]($b.name -replace '\s+$','')
                        if ($bm -and $bn) { $dhcp_map[$bm] = $bn }
                    }
                    $debug += "dhcp=$($dhcp_map.Count)"
                } catch {}
            }
        }
    } else {
        $sc1b = if ($r1b) { ($r1b -replace '##ERR:(\d+)##.*','$1') } else { '0' }
        $debug += "hotspot_basic=$sc1b"
    }
}

# ── Step 2: MD5-challenge auth (classic Keenetic NDMS2) ───────────────────────
if (-not $hotspot -and $login -ne '' -and $pass -ne '') {
    $challenge = $null

    # GET /auth
    $rAuth = Invoke-Http "$base/auth" -Cookies $cookies -Timeout 8000
    if ($rAuth) {
        $bodyForChallenge = if ($rAuth.StartsWith('##ERR:')) { $rAuth -replace '^##ERR:\d+##','' } else { $rAuth }
        $debug += "auth_get=ok len=$($bodyForChallenge.Length)"
        if ($bodyForChallenge.Length -gt 0) {
            try { $challenge = ($bodyForChallenge | ConvertFrom-Json).challenge } catch {}
        }
        # Try WWW-Authenticate (can't get it via helper, try direct for challenge in header)
    }
    $debug += "challenge=$(if($challenge){'found'}else{'null'})"

    if ($challenge) {
        $hash     = Get-MD5((Get-MD5 $pass) + $challenge)
        $postBody = [System.Text.Encoding]::UTF8.GetBytes('{"login":"' + $login + '","password":"' + $hash + '"}')
        $rPost = Invoke-Http "$base/auth" -Method 'POST' -Body $postBody -Cookies $cookies -Timeout 8000
        if ($rPost -and -not $rPost.StartsWith('##ERR:')) {
            $debug += "auth_post=200"
            $rHot = Invoke-Http "$base/rci/show/ip/hotspot" -Cookies $cookies -Timeout 8000
            if ($rHot -and -not $rHot.StartsWith('##ERR:')) {
                try {
                    $pH = $rHot | ConvertFrom-Json
                    if ($pH -is [array]) { $hotspot = $pH; $method = 'keenetic-api' }
                    elseif ($pH.PSObject.Properties['host']) { $hotspot = $pH.host; $method = 'keenetic-api' }
                } catch { $debug += "hotspot_parse_err=$_" }
            }
            # DHCP bindings
            if ($hotspot) {
                $rDhcp2 = Invoke-Http "$base/rci/show/ip/dhcp/bindings" -Cookies $cookies -Timeout 6000
                if ($rDhcp2 -and -not $rDhcp2.StartsWith('##ERR:')) {
                    try {
                        foreach ($b in ($rDhcp2 | ConvertFrom-Json)) {
                            $bm = ([string]($b.mac -replace '-',':')).ToLower()
                            $bn = [string]($b.name -replace '\s+$','')
                            if ($bm -and $bn) { $dhcp_map[$bm] = $bn }
                        }
                        $debug += "dhcp=$($dhcp_map.Count)"
                    } catch {}
                }
            }
        } else {
            $scP = if ($rPost) { ($rPost -replace '##ERR:(\d+)##.*','$1') } else { '0' }
            $debug += "auth_post=$scP"
        }
    } else {
        # No challenge — try plain MD5 POST
        $md5pass   = Get-MD5 $pass
        $postBody2 = [System.Text.Encoding]::UTF8.GetBytes('{"login":"' + $login + '","password":"' + $md5pass + '"}')
        $rPost2 = Invoke-Http "$base/auth" -Method 'POST' -Body $postBody2 -Cookies $cookies -Timeout 8000
        if ($rPost2 -and -not $rPost2.StartsWith('##ERR:')) {
            $debug += "auth_md5_post=200"
            $rHot2 = Invoke-Http "$base/rci/show/ip/hotspot" -Cookies $cookies -Timeout 8000
            if ($rHot2 -and -not $rHot2.StartsWith('##ERR:')) {
                try {
                    $pH2 = $rHot2 | ConvertFrom-Json
                    if ($pH2 -is [array] -and $pH2.Count -gt 0) { $hotspot = $pH2; $method = 'keenetic-api-md5' }
                } catch {}
            }
        } else {
            $scQ = if ($rPost2) { ($rPost2 -replace '##ERR:(\d+)##.*','$1') } else { '0' }
            $debug += "auth_md5_post=$scQ"
        }
    }
}

# ── Build client list from hotspot data ───────────────────────────────────────
$clients = @()

if ($hotspot) {
    foreach ($h in $hotspot) {
        $cip  = [string]($h.ip  -replace '\s','')
        $cmac = ([string]($h.mac -replace '-',':')).ToLower()
        if (-not $cip -or -not $cip.StartsWith($subnet)) { continue }
        $iface  = [string]($h.interface -replace '\s','')
        $isWifi = ($iface -imatch 'wifi|wlan|wireless|pt' -or
                   ($h.PSObject.Properties['rssi'] -and $h.rssi -ne $null -and
                    [string]$h.rssi -ne '0' -and [string]$h.rssi -ne ''))
        $ctype  = if ($isWifi) { 'wifi' } else { 'lan' }
        $cname  = ''
        if ($dhcp_map.ContainsKey($cmac)) { $cname = $dhcp_map[$cmac] }
        if (-not $cname) { $cname = [string]($h.name -replace '\s+$','') }
        if (-not $cname) { $cname = $cip }
        $clients += [ordered]@{
            mac       = $cmac; ip = $cip; name = $cname
            iface     = if ($isWifi) { $iface } else { 'LAN' }
            type      = $ctype
            rssi      = if ($h.PSObject.Properties['rssi'])        { $h.rssi }        else { $null }
            online_sec= if ($h.PSObject.Properties['online-time']) { $h.'online-time' } else { $null }
            link_mbps = if ($h.PSObject.Properties['link'])        { $h.link }        else { $null }
        }
    }
}

# ── Step 3: Retry API on port 8080 (some Keenetic / third-party firmware) ─────
if (-not $hotspot) {
    foreach ($altPort in @(8080)) {
        if ($hotspot) { break }
        $altBase = "http://${gw}:$altPort"

        # noauth
        $rA0 = Invoke-Http "$altBase/rci/show/ip/hotspot" -Cookies $cookies -Timeout 4000
        if ($rA0 -and -not $rA0.StartsWith('##ERR:')) {
            $debug += "hotspot_p${altPort}_noauth=200 len=$($rA0.Length)"
            try {
                $pA0 = $rA0 | ConvertFrom-Json
                if ($pA0 -is [array] -and $pA0.Count -gt 0) { $hotspot = $pA0; $method = "keenetic-api-$altPort-noauth" }
                elseif ($pA0.PSObject.Properties['host'] -and $pA0.host.Count -gt 0) { $hotspot = $pA0.host; $method = "keenetic-api-$altPort-noauth" }
            } catch {}
        } else {
            $scA0 = if ($rA0) { ($rA0 -replace '##ERR:(\d+)##.*','$1') } else { '0' }
            $debug += "hotspot_p${altPort}_noauth=$scA0"
        }

        # Basic auth on alt port
        if (-not $hotspot -and $login -ne '' -and $pass -ne '') {
            $cred2 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes("${login}:${pass}"))
            $rAB = Invoke-Http "$altBase/rci/show/ip/hotspot" -Cookies $cookies -Timeout 5000 `
                   -Headers @{ Authorization = "Basic $cred2" }
            if ($rAB -and -not $rAB.StartsWith('##ERR:')) {
                $debug += "hotspot_p${altPort}_basic=200 len=$($rAB.Length)"
                try {
                    $pAB = $rAB | ConvertFrom-Json
                    if ($pAB -is [array] -and $pAB.Count -gt 0) { $hotspot = $pAB; $method = "keenetic-api-$altPort-basic" }
                    elseif ($pAB.PSObject.Properties['host'] -and $pAB.host.Count -gt 0) { $hotspot = $pAB.host; $method = "keenetic-api-$altPort-basic" }
                } catch {}
            } else {
                $scAB = if ($rAB) { ($rAB -replace '##ERR:(\d+)##.*','$1') } else { '0' }
                $debug += "hotspot_p${altPort}_basic=$scAB"
            }
        }

        # MD5 challenge on alt port
        if (-not $hotspot -and $login -ne '' -and $pass -ne '') {
            $rA2 = Invoke-Http "$altBase/auth" -Cookies $cookies -Timeout 5000
            $bodyA2 = if ($rA2 -and $rA2.StartsWith('##ERR:')) { $rA2 -replace '^##ERR:\d+##','' } else { $rA2 }
            $challA = $null
            if ($bodyA2 -and $bodyA2.Length -gt 0) { try { $challA = ($bodyA2 | ConvertFrom-Json).challenge } catch {} }
            $debug += "auth_p${altPort}_challenge=$(if($challA){'found'}else{'null'})"
            if ($challA) {
                $hashA = Get-MD5((Get-MD5 $pass) + $challA)
                $postA = [System.Text.Encoding]::UTF8.GetBytes('{"login":"' + $login + '","password":"' + $hashA + '"}')
                $rAP   = Invoke-Http "$altBase/auth" -Method 'POST' -Body $postA -Cookies $cookies -Timeout 5000
                if ($rAP -and -not $rAP.StartsWith('##ERR:')) {
                    $rAH = Invoke-Http "$altBase/rci/show/ip/hotspot" -Cookies $cookies -Timeout 5000
                    if ($rAH -and -not $rAH.StartsWith('##ERR:')) {
                        try {
                            $pAH = $rAH | ConvertFrom-Json
                            if ($pAH -is [array] -and $pAH.Count -gt 0) { $hotspot = $pAH; $method = "keenetic-api-$altPort-md5" }
                            elseif ($pAH.PSObject.Properties['host'] -and $pAH.host.Count -gt 0) { $hotspot = $pAH.host; $method = "keenetic-api-$altPort-md5" }
                        } catch { $debug += "hotspot_p${altPort}_md5_parse=$_" }
                    }
                }
            }
        }
    }

    # Re-build client list if API succeeded on alt port
    if ($hotspot) {
        foreach ($h in $hotspot) {
            $cip  = [string]($h.ip  -replace '\s','')
            $cmac = ([string]($h.mac -replace '-',':')).ToLower()
            if (-not $cip -or -not $cip.StartsWith($subnet)) { continue }
            $iface  = [string]($h.interface -replace '\s','')
            $isWifi = ($iface -imatch 'wifi|wlan|wireless|pt' -or
                       ($h.PSObject.Properties['rssi'] -and $h.rssi -ne $null -and
                        [string]$h.rssi -ne '0' -and [string]$h.rssi -ne ''))
            $ctype = if ($isWifi) { 'wifi' } else { 'lan' }
            $cname = ''
            if ($dhcp_map.ContainsKey($cmac)) { $cname = $dhcp_map[$cmac] }
            if (-not $cname) { $cname = [string]($h.name -replace '\s+$','') }
            if (-not $cname) { $cname = $cip }
            $clients += [ordered]@{
                mac=$cmac; ip=$cip; name=$cname
                iface=if ($isWifi) { $iface } else { 'LAN' }
                type=$ctype
                rssi      = if ($h.PSObject.Properties['rssi'])        { $h.rssi }        else { $null }
                online_sec= if ($h.PSObject.Properties['online-time']) { $h.'online-time' } else { $null }
                link_mbps = if ($h.PSObject.Properties['link'])        { $h.link }        else { $null }
            }
        }
    }
}

# ── Fallback: Ping sweep + ARP + Get-NetNeighbor ─────────────────────────────
if ($clients.Count -eq 0) {
    # Async ping sweep — discovers ALL devices in subnet, populates OS ARP cache
    $pingTasks = @{}
    foreach ($i in 1..254) {
        $ip = "$subnet.$i"
        $p  = [System.Net.NetworkInformation.Ping]::new()
        $pingTasks[$ip] = $p.SendPingAsync($ip, 500)
    }
    # Wait up to 3 sec for all pings to complete
    $allTasks = [System.Threading.Tasks.Task]::WhenAll($pingTasks.Values)
    $allTasks.Wait(3000) | Out-Null
    $debug += "ping_sweep=done"

    $seen = @{}
    foreach ($line in (arp -a 2>$null)) {
        if ($line -match '(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+([0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2})') {
            $ip = $Matches[1]; $mac = ($Matches[2] -replace '-',':').ToLower()
            if ($ip.StartsWith($subnet) -and $mac -notmatch 'ff:ff:ff' -and $mac -notmatch '01:00:5e') {
                $seen[$ip] = $mac
            }
        }
    }
    $neighbors = Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress.StartsWith($subnet) -and
            $_.LinkLayerAddress -notmatch '^(FF-FF|01-00-5E|33-33|00-00-00)' -and
            $_.State -in @('Reachable','Stale','Delay','Probe','Permanent') }
    foreach ($n in $neighbors) { if (-not $seen[$n.IPAddress]) { $seen[$n.IPAddress] = ($n.LinkLayerAddress -replace '-',':').ToLower() } }
    $debug += "arp_fallback ips=$($seen.Count)"

    $nbJobs = @{}
    foreach ($ip in $seen.Keys) {
        $nbJobs[$ip] = Start-Job -ScriptBlock {
            $r = nbtstat -A $args[0] 2>$null | Select-String '<00>\s+UNIQUE' | Select-Object -First 1
            if ($r) { ($r.ToString().Trim() -split '\s+')[0] } else { '' }
        } -ArgumentList $ip
    }
    Start-Sleep -Seconds 3
    $dnsJobs = @{}
    foreach ($ip in $seen.Keys) { $dnsJobs[$ip] = [System.Net.Dns]::BeginGetHostEntry($ip, $null, $null) }

    foreach ($ip in $seen.Keys) {
        $name = ''
        $nbJob = $nbJobs[$ip]
        if ($nbJob -and $nbJob.State -eq 'Completed') { $nb = Receive-Job $nbJob -ErrorAction SilentlyContinue; if ($nb) { $name = $nb.ToString().Trim() } }
        if (-not $name) { $dj = $dnsJobs[$ip]; if ($dj -and $dj.AsyncWaitHandle.WaitOne(100)) { try { $name = ([System.Net.Dns]::EndGetHostEntry($dj)).HostName -replace '\.$','' } catch {} } }
        if (-not $name -or $name -eq $ip) { $name = $ip }
        $mac = $seen[$ip]
        $clients += [ordered]@{ mac=$mac; ip=$ip; name=$name; iface='LAN'; type='lan'; rssi=$null; online_sec=$null; link_mbps=$null }
    }
    $nbJobs.Values | Remove-Job -Force -ErrorAction SilentlyContinue
}

# ── Printer detection (parallel TCP port check) ───────────────────────────────
# Printer ports: 9100 (JetDirect/RAW), 631 (IPP), 515 (LPD)
$printerJobs = @{}
foreach ($c in $clients) {
    $ip = $c.ip
    $printerJobs[$ip] = Start-Job -ScriptBlock {
        param($ip)
        foreach ($port in @(9100, 631, 515)) {
            try {
                $tcp = New-Object System.Net.Sockets.TcpClient
                $ar  = $tcp.BeginConnect($ip, $port, $null, $null)
                $ok  = $ar.AsyncWaitHandle.WaitOne(400)
                $tcp.Close()
                if ($ok) { return $port }
            } catch {}
        }
        return 0
    } -ArgumentList $ip
}
# Wait up to 2 seconds for printer jobs
Start-Sleep -Seconds 2
foreach ($c in $clients) {
    $job = $printerJobs[$c.ip]
    if ($job -and $job.State -eq 'Completed') {
        $port = Receive-Job $job -ErrorAction SilentlyContinue
        if ($port -gt 0) {
            $c['type']         = 'printer'
            $c['printer_port'] = $port
        }
    }
}
$printerJobs.Values | Remove-Job -Force -ErrorAction SilentlyContinue

[ordered]@{
    ok      = $true
    router  = $gw
    method  = $method
    debug   = $debug
    updated = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')
    count   = $clients.Count
    clients = $clients
} | ConvertTo-Json -Compress -Depth 4
