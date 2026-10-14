[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$WslDistribution,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$')][string]$RuntimeUser,
    [Parameter(Mandatory=$true)][string]$LinuxInstallationRoot,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{64}$')][string]$ExpectedMachineId,
    [string]$TaskName,
    [string]$LegacyEntrypoint,
    [switch]$AdoptExisting,
    [switch]$Apply,
    [switch]$Check
)
$ErrorActionPreference = 'Stop'
if ($Apply -and $Check) { throw 'Choose installation or readback.' }
if ($env:OS -ne 'Windows_NT') { throw 'Windows owner startup requires Windows.' }
if ($LinuxInstallationRoot -notmatch '^/[^\r\n\x00]*$' -or $WslDistribution -match '[\r\n\x00]') {
    throw 'Selected Runtime path or distribution is invalid.'
}
$wslExe = Join-Path $env:WINDIR 'System32\wsl.exe'
function Quote-NativeArgument([string]$Value) {
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    return '"' + [regex]::Replace($escaped, '(\\+)$', '$1$1') + '"'
}
function Join-NativeArguments([string[]]$Values) {
    return (@($Values | ForEach-Object { Quote-NativeArgument $_ }) -join ' ')
}
function Invoke-WslReadback([string[]]$Arguments) {
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $wslExe
    $info.Arguments = Join-NativeArguments -Values (@('--distribution',$WslDistribution,'--user',$RuntimeUser,'--exec') + $Arguments)
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $info
    try {
        if (-not $process.Start()) { throw 'Runtime observation could not start.' }
        $process.StandardInput.Close()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(20000)) { $process.Kill(); throw 'Runtime observation timed out.' }
        if ($process.ExitCode -ne 0) { throw 'Runtime observation failed.' }
        return $stdout.Result
    } finally { $process.Dispose() }
}
function Stop-OwnedMaintainer {
    $code = @'
import json,os,select,signal,sys
from pathlib import Path
r=Path(sys.argv[1]); legacy=sys.argv[2] if len(sys.argv)>2 else ''
state=json.loads((r/'state.json').read_text())
lock=Path(state['runtime_config_ref']).parent/'login-recovery.lock'
if not lock.exists():
    print('{}');raise SystemExit(0)
info=lock.stat()
for line in Path('/proc/locks').read_text().splitlines():
    fields=line.split()
    if len(fields)<6 or fields[1]!='FLOCK':continue
    device=fields[5].split(':')
    if len(device)!=3:continue
    if (int(device[0],16),int(device[1],16),int(device[2]))!=(os.major(info.st_dev),os.minor(info.st_dev),info.st_ino):continue
    pid=int(fields[4]);proc=Path('/proc')/str(pid)
    try:
        handle=os.pidfd_open(pid,0)
    except ProcessLookupError:
        continue
    try:
        initial=(proc/'stat').read_text().rsplit(')',1)[1].split()[19]
        if proc.stat().st_uid!=os.getuid():raise RuntimeError('maintenance process owner requires review')
        args=(proc/'cmdline').read_bytes().decode().split('\0')
        original=legacy and len(args)>1 and args[1]==legacy
        current=len(args)>1 and args[1]==str(r/'acs_launcher.py') and '--maintain-startup' in args and '--installation-root' in args and args[args.index('--installation-root')+1]==str(r)
        if not (original or current):raise RuntimeError('maintenance lock holder requires owner review')
        if (proc/'stat').read_text().rsplit(')',1)[1].split()[19]!=initial:raise RuntimeError('maintenance process identity changed')
        signal.pidfd_send_signal(handle,signal.SIGTERM,None,0)
        poll=select.poll();poll.register(handle,select.POLLIN)
        if not poll.poll(5000):raise RuntimeError('previous maintenance process has not stopped')
    except (FileNotFoundError,ProcessLookupError):
        continue
    finally:
        os.close(handle)
print('{}')
'@
    Invoke-WslReadback -Arguments @('/usr/bin/python3','-c',$code,$LinuxInstallationRoot,$LegacyEntrypoint) | Out-Null
}
$probeCode = @'
import hashlib,importlib.util,json,sys
from pathlib import Path
r=Path(sys.argv[1])
s=importlib.util.spec_from_file_location('acs_binding_probe',r/'acs_launcher.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
active,argv=m.resolve_launch(r)
observed=m.observe_machine()
state=json.loads((r/'state.json').read_text())
if hashlib.sha256((r/'acs_launcher.py').read_bytes()).hexdigest()!=state['helper_digests']['acs_launcher.py']:raise RuntimeError('installed launcher digest differs')
if '--maintain-startup' not in (r/'acs_launcher.py').read_text():raise RuntimeError('selected release needs startup maintenance entry')
print(json.dumps({'machine_id':observed['machine_id'],'account':observed['account'],'installation_root':str(r),'version':state['version'],'startup_enabled':state.get('startup',{}).get('enabled',True)}))
'@
$machine = (Invoke-WslReadback -Arguments @('/usr/bin/python3','-c',$probeCode,$LinuxInstallationRoot)) | ConvertFrom-Json
if ($machine.machine_id -ne $ExpectedMachineId -or $machine.account -ne $RuntimeUser -or $machine.installation_root -ne $LinuxInstallationRoot) {
    throw 'Selected Runtime machine/account/installation differs.'
}
if (-not $machine.startup_enabled) {
    [pscustomobject]@{Schema='acs-windows-startup/1';State='owner_disabled';Version=$machine.version} | ConvertTo-Json -Compress
    exit 0
}
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$binding = [ordered]@{WindowsOwner=$sid;Distribution=$WslDistribution;RuntimeUser=$RuntimeUser;InstallationRoot=$LinuxInstallationRoot;MachineId=$ExpectedMachineId}
$bindingText = $binding | ConvertTo-Json -Compress
$sha = [Security.Cryptography.SHA256]::Create()
try { $bindingHash = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($bindingText)))).Replace('-','').ToLowerInvariant() } finally { $sha.Dispose() }
if (-not $TaskName) { $TaskName = 'ACS-WSL-' + $bindingHash.Substring(0,12) + '-Startup-Recovery' }
if ($TaskName -notmatch '^ACS-[a-zA-Z0-9_.-]+-Startup-Recovery$') { throw 'Use an ACS owner startup task name.' }
$base = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.agent-collaboration\startup'
$destination = Join-Path $base $bindingHash.Substring(0,16)
$marker = Join-Path $destination 'installation-receipt.json'
$owned = $null
if (Test-Path -LiteralPath $marker) {
    $owned = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
    if ($owned.Schema -ne 'acs-windows-startup/1' -or $owned.BindingHash -ne $bindingHash) { throw 'Existing startup ownership differs.' }
}
$existing = Get-ScheduledTask -TaskName $TaskName -TaskPath '\' -ErrorAction SilentlyContinue
$launcher = $LinuxInstallationRoot + '/acs_launcher.py'
$linuxArguments = @('--distribution',$WslDistribution,'--user',$RuntimeUser,'--exec','/usr/bin/python3',$launcher,'--installation-root',$LinuxInstallationRoot,'--maintain-startup')
$backgroundArguments = Join-NativeArguments -Values (@($wslExe) + $linuxArguments)
if ($existing) {
    $action = @($existing.Actions)
    if ($action.Count -ne 1) { throw 'Existing startup has multiple actions.' }
    $valid = $false
    if ($owned -and $action[0].Execute -eq $owned.GUIHost -and $action[0].Arguments -eq $owned.TaskArguments -and
        (Get-FileHash -LiteralPath $owned.GUIHost -Algorithm SHA256).Hash.ToLowerInvariant() -eq $owned.GUIHostSHA256) { $valid = $true }
    if (-not $valid -and $AdoptExisting) {
        $legacyArguments = Join-NativeArguments -Values @('--distribution',$WslDistribution,'--user',$RuntimeUser,'--exec','/usr/bin/python3',$LegacyEntrypoint)
        if ($LegacyEntrypoint -and $action[0].Execute -eq $wslExe -and $action[0].Arguments -eq $legacyArguments) { $valid = $true }
        $legacyReceipt = Join-Path (Split-Path -Parent $action[0].Execute) 'installation-receipt.json'
        if (-not $valid -and $LegacyEntrypoint -and (Test-Path -LiteralPath $legacyReceipt)) {
            $legacy = Get-Content -LiteralPath $legacyReceipt -Raw | ConvertFrom-Json
            if ($legacy.Task -eq $TaskName -and $legacy.GUIHost -eq $action[0].Execute -and
                $action[0].Arguments -in @(((Quote-NativeArgument $wslExe) + ' ' + $legacyArguments),('"' + $wslExe + '" ' + $legacyArguments)) -and
                (Get-FileHash -LiteralPath $action[0].Execute -Algorithm SHA256).Hash.ToLowerInvariant() -eq $legacy.GUIHostSHA256) { $valid = $true }
        }
    }
    $principal = $existing.Principal.UserId
    $currentName = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    if (-not $valid -or $principal -notin @($sid,$currentName,($currentName -split '\\')[-1])) { throw 'Existing task action or owner requires review.' }
}
$source = Join-Path (Split-Path -Parent $PSScriptRoot) 'assets\windows\acs_background_host.cs'
$sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
$binaryDirectory = Join-Path $destination $sourceHash.Substring(0,16)
$binary = Join-Path $binaryDirectory 'acs_background_host.exe'
if ($Check) {
    if (-not $owned -or -not $existing -or $existing.Actions.Execute -ne $binary -or $existing.State -ne 'Running') { throw 'Owner startup requires activation.' }
    [pscustomobject]@{Schema='acs-windows-startup/1';State='running';Task=$TaskName;TaskHidden=$existing.Settings.Hidden;MachineId=$ExpectedMachineId;Version=$machine.version} | ConvertTo-Json -Compress
    exit 0
}
if (-not $Apply) {
    [pscustomobject]@{Schema='acs-windows-startup/1';State='planned';Task=$TaskName;Binding=$binding;GUIHost=$binary;ExistingTask=[bool]$existing;Version=$machine.version} | ConvertTo-Json -Depth 4
    exit 0
}
if ($owned -and $owned.SourceSHA256 -eq $sourceHash -and $existing -and $existing.State -eq 'Running' -and $existing.Actions.Execute -eq $binary -and $existing.Actions.Arguments -eq $backgroundArguments) {
    $owned | ConvertTo-Json -Depth 4
    exit 0
}
foreach ($selectedPath in @($destination,$source)) {
    $cursor = [IO.Path]::GetFullPath($selectedPath)
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Startup source or destination traverses a reparse point.'
            }
        }
        $parent = [IO.Path]::GetDirectoryName($cursor)
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
}
New-Item -ItemType Directory -Path $binaryDirectory -Force | Out-Null
$backupDirectory = Join-Path $destination ('backup-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $backupDirectory | Out-Null
if ($existing) { Export-ScheduledTask -TaskName $TaskName -TaskPath '\' | Set-Content -LiteralPath (Join-Path $backupDirectory 'task.xml') -Encoding Unicode }
if ($owned) { Copy-Item -LiteralPath $marker -Destination (Join-Path $backupDirectory 'installation-receipt.json') }
if (-not (Test-Path -LiteralPath $binary)) {
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    Copy-Item -LiteralPath $source -Destination (Join-Path $binaryDirectory 'acs_background_host.cs')
    & $compiler /nologo /target:winexe /platform:x64 ('/out:' + $binary) (Join-Path $binaryDirectory 'acs_background_host.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Background host compilation failed.' }
}
$bytes = [IO.File]::ReadAllBytes($binary)
$offset = [BitConverter]::ToInt32($bytes,60)
if ([BitConverter]::ToUInt16($bytes,$offset+24+68) -ne 2) { throw 'Background host subsystem differs.' }
$action = New-ScheduledTaskAction -Execute $binary -Argument $backgroundArguments
try {
    if ($existing) {
        $existing.Settings.Hidden = $true
        Set-ScheduledTask -TaskName $TaskName -TaskPath '\' -Action $action -Settings $existing.Settings | Out-Null
        Stop-ScheduledTask -TaskName $TaskName -TaskPath '\'
        Stop-OwnedMaintainer
    } else {
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $sid
        $principal = New-ScheduledTaskPrincipal -UserId $sid -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -Hidden -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskName $TaskName -TaskPath '\' -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
    }
    Start-ScheduledTask -TaskName $TaskName -TaskPath '\'
    Start-Sleep -Milliseconds 1200
    $result = Get-ScheduledTask -TaskName $TaskName -TaskPath '\'
    if ($result.Actions.Execute -ne $binary -or $result.State -ne 'Running') { throw 'Background startup readback failed.' }
    $receipt = [ordered]@{Schema='acs-windows-startup/1';State='running';Task=$TaskName;BindingHash=$bindingHash;Binding=$binding;GUIHost=$binary;GUIHostSHA256=(Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant();SourceSHA256=$sourceHash;TaskArguments=$backgroundArguments;Backup=$backupDirectory;Version=$machine.version}
    $receipt | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath ($marker + '.stage') -Encoding UTF8
    Move-Item -LiteralPath ($marker + '.stage') -Destination $marker -Force
    $receipt | ConvertTo-Json -Depth 4
} catch {
    $savedTask = Join-Path $backupDirectory 'task.xml'
    if (Test-Path -LiteralPath $savedTask) { Register-ScheduledTask -TaskName $TaskName -TaskPath '\' -Xml (Get-Content -LiteralPath $savedTask -Raw) -Force | Out-Null; Start-ScheduledTask -TaskName $TaskName -TaskPath '\' }
    elseif (-not $existing) { Unregister-ScheduledTask -TaskName $TaskName -TaskPath '\' -Confirm:$false -ErrorAction SilentlyContinue }
    throw
}
