<#
.SYNOPSIS
Regenerate the kiosk's offline Chinese and English MP3 instructions.
.DESCRIPTION
Uses installed Microsoft SAPI desktop voices; no cloud speech service or API key.
WAV synthesis happens on Windows. MP3 encoding happens locally when ffmpeg,
ffprobe and Python 3 are available, otherwise on the chosen SSH build device.
The remote build directory is separate from the running kiosk application.
SSH uses normal keys or interactive password prompts; no credentials are saved.
.EXAMPLE
pwsh -File tools/generate_voice.ps1 -SshHost 192.168.88.123 -KnownHostsPath C:/path/to/known-hosts
.EXAMPLE
pwsh -File tools/generate_voice.ps1 -FfmpegPath C:/ffmpeg/bin/ffmpeg.exe -FfprobePath C:/ffmpeg/bin/ffprobe.exe -PythonPath C:/Python/python.exe
#>
[CmdletBinding()]
param(
  [string]$ManifestPath = (Join-Path $PSScriptRoot '../hmi/audio/prompts.json'),
  [string]$OutputDirectory = (Join-Path $PSScriptRoot '../hmi/audio'),
  [string]$WorkDirectory = (Join-Path ([IO.Path]::GetTempPath()) ('aws-buttonwall-voice-' + [guid]::NewGuid().ToString('N'))),
  [string]$ChineseVoice = 'Microsoft Huihui Desktop',
  [string]$EnglishVoice = 'Microsoft Zira Desktop',
  [ValidateRange(-5, 5)][int]$SpeechRate = 1,
  [string]$FfmpegPath = '',
  [string]$FfprobePath = '',
  [string]$PythonPath = '',
  [ValidatePattern('^[a-zA-Z0-9.-]+$')][string]$SshHost = '192.168.88.123',
  [ValidatePattern('^[a-zA-Z0-9_-]+$')][string]$SshUser = 'sunrise',
  [string]$KnownHostsPath = '',
  [ValidatePattern('^/[a-zA-Z0-9/_-]+$')][string]$RemoteDirectory = '/home/sunrise/aws-wall-voice-build'
)
$ErrorActionPreference = 'Stop'
$taskManifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding utf8 | ConvertFrom-Json
$taskWork = [IO.Path]::GetFullPath($WorkDirectory)
$taskOutput = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $taskWork, $taskOutput | Out-Null
$taskVoice = New-Object -ComObject SAPI.SpVoice
$taskVoices = $taskVoice.GetVoices()
$taskVoicesByLanguage = @{}
foreach ($taskLanguage in @('zh', 'en')) {
  $taskRequestedVoice = if ($taskLanguage -eq 'zh') { $ChineseVoice } else { $EnglishVoice }
  for ($taskVoiceIndex = 0; $taskVoiceIndex -lt $taskVoices.Count; $taskVoiceIndex++) {
    $taskCandidateVoice = $taskVoices.Item($taskVoiceIndex)
    if ($taskCandidateVoice.GetDescription().StartsWith($taskRequestedVoice, [StringComparison]::OrdinalIgnoreCase)) {
      $taskVoicesByLanguage[$taskLanguage] = $taskCandidateVoice
      break
    }
  }
  if (-not $taskVoicesByLanguage.ContainsKey($taskLanguage)) { throw "Install the Windows desktop voice: $taskRequestedVoice" }
}
$taskVoice.Volume = 100
$taskCount = 0
foreach ($taskLanguage in @('zh', 'en')) {
  $taskLanguagePath = Join-Path $taskWork "wav/$taskLanguage"
  New-Item -ItemType Directory -Force -Path $taskLanguagePath | Out-Null
  $taskVoice.Voice = $taskVoicesByLanguage[$taskLanguage]
  foreach ($taskPrompt in $taskManifest.prompts) {
    if ($taskPrompt.id -notmatch '^[a-z_]+$') { throw "Invalid prompt ID: $($taskPrompt.id)" }
    $taskText = $taskPrompt.$taskLanguage.text
    if ([string]::IsNullOrWhiteSpace($taskText)) { throw "Missing $taskLanguage text: $($taskPrompt.id)" }
    $taskWavePath = Join-Path $taskLanguagePath "$($taskPrompt.id).wav"
    $taskStream = New-Object -ComObject SAPI.SpFileStream
    # SAFT22kHz16BitMono: compact, lossless source for spoken instructions.
    $taskStream.Format.Type = 22
    $taskStream.Open($taskWavePath, 3, $false)
    try {
      $taskVoice.AudioOutputStream = $taskStream
      $taskVoice.Rate = if ($taskPrompt.id -in @('ready', 'go', 'forfeit')) { [Math]::Min(3, $SpeechRate + 1) } else { $SpeechRate }
      [void]$taskVoice.Speak($taskText, 0)
    } finally {
      $taskStream.Close()
      [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($taskStream)
    }
    $taskCount++
  }
}
[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($taskVoice)
Copy-Item -LiteralPath $ManifestPath -Destination (Join-Path $taskWork 'prompts.json')
$taskVoiceMetadata = @{
  generator = 'Microsoft SAPI desktop voices; offline synthesis'
  voices = @{ zh = $ChineseVoice; en = $EnglishVoice }
  speech_rate = $SpeechRate
}
$taskVoiceMetadata | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskWork 'voices.json') -Encoding utf8
Write-Host "Synthesized $taskCount offline WAV files in $taskWork"

# One encoder is used on Windows and Linux. A report records duration, channel
# count and a full decode check. Critical prompts must fit the UI playback cap.
$taskEncoder = @'
import json
import pathlib
import re
import subprocess
import sys

root = pathlib.Path(__file__).resolve().parent
ffmpeg = sys.argv[1] if len(sys.argv) > 1 else "ffmpeg"
ffprobe = sys.argv[2] if len(sys.argv) > 2 else "ffprobe"
manifest = json.loads((root / "prompts.json").read_text(encoding="utf-8-sig"))
metadata = json.loads((root / "voices.json").read_text(encoding="utf-8-sig"))
caps = {"ready": 2.2, "go": 2.4, "forfeit": 3.0}
output = root / "output"
rows = []

def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True)

def probe(path):
    return json.loads(run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_name,channels,sample_rate", "-of", "json", str(path)]).stdout)

for language in ("zh", "en"):
    (output / language).mkdir(parents=True, exist_ok=True)
    for prompt in manifest["prompts"]:
        key = prompt["id"]
        if not re.fullmatch("[a-z_]+", key):
            raise ValueError("Unsafe prompt ID")
        wav = root / "wav" / language / (key + ".wav")
        mp3 = output / language / (key + ".mp3")
        filters = "silenceremove=start_periods=1:start_duration=0.03:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_duration=0.03:start_threshold=-50dB,areverse,loudnorm=I=-18:TP=-2:LRA=7,apad=pad_dur=0.08"

        def encode(speed=1.0):
            audio_filter = filters + (",atempo=" + str(speed) if speed != 1 else "")
            run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav), "-af", audio_filter, "-ar", "24000", "-ac", "1", "-codec:a", "libmp3lame", "-b:a", "64k", "-map_metadata", "-1", str(mp3)])

        encode()
        details = probe(mp3)
        duration = float(details["format"]["duration"])
        speed = 1.0
        if key in caps and duration > caps[key]:
            speed = round(duration / (caps[key] - 0.15), 4)
            if speed > 1.35:
                raise RuntimeError(f"Shorten {language}/{key}: {duration:.3f}s exceeds {caps[key]}s by too much")
            encode(speed)
            details = probe(mp3)
            duration = float(details["format"]["duration"])
        if key in caps and duration > caps[key]:
            raise RuntimeError(f"{language}/{key}: {duration:.3f}s exceeds {caps[key]}s")
        run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(mp3), "-f", "null", "-"])
        stream = details["streams"][0]
        if stream["codec_name"] != "mp3" or stream["channels"] != 1:
            raise RuntimeError(f"Unexpected format: {language}/{key}")
        rows.append({"id": key, "language": language, "file": prompt[language]["file"], "duration_seconds": round(duration, 3), "bytes": mp3.stat().st_size, "channels": stream["channels"], "sample_rate": int(stream["sample_rate"]), "tempo_factor": speed, "decode_verified": True})

report = {"version": 1, **metadata, "critical_duration_caps_seconds": caps, "count": len(rows), "total_bytes": sum(row["bytes"] for row in rows), "files": rows}
(output / "build-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"count": len(rows), "total_bytes": report["total_bytes"], "critical": [row for row in rows if row["id"] in caps]}, ensure_ascii=False))
'@
$taskEncoder | Set-Content -LiteralPath (Join-Path $taskWork 'build_voice.py') -Encoding utf8

if (-not $FfmpegPath) { $FfmpegPath = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source }
if (-not $FfprobePath) { $FfprobePath = (Get-Command ffprobe -ErrorAction SilentlyContinue).Source }
if (-not $PythonPath) { $PythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source }
if ($FfmpegPath -and $FfprobePath -and $PythonPath) {
  & $PythonPath (Join-Path $taskWork 'build_voice.py') $FfmpegPath $FfprobePath
  if ($LASTEXITCODE -ne 0) { throw 'Local MP3 encoding failed.' }
  foreach ($taskLanguage in @('zh', 'en')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $taskOutput $taskLanguage) | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $taskWork "output/$taskLanguage") -File | Copy-Item -Destination (Join-Path $taskOutput $taskLanguage)
  }
  Copy-Item -LiteralPath (Join-Path $taskWork 'output/build-report.json') -Destination (Join-Path $taskOutput 'build-report.json')
} else {
  $taskSshOptions = @('-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=yes')
  if ($KnownHostsPath) { $taskSshOptions += @('-o', "UserKnownHostsFile=$KnownHostsPath") }
  $taskTarget = "$SshUser@$SshHost"
  $taskInputArchive = Join-Path $taskWork 'voice-input.tar.gz'
  $taskOutputArchive = Join-Path $taskWork 'voice-output.tar.gz'
  & tar -czf $taskInputArchive -C $taskWork wav prompts.json voices.json build_voice.py
  if ($LASTEXITCODE -ne 0) { throw 'Could not package WAV sources.' }
  & ssh @taskSshOptions $taskTarget "mkdir -p '$RemoteDirectory'"
  if ($LASTEXITCODE -ne 0) { throw 'Could not prepare remote build directory.' }
  & scp @taskSshOptions $taskInputArchive "${taskTarget}:$RemoteDirectory/voice-input.tar.gz"
  if ($LASTEXITCODE -ne 0) { throw 'Could not upload WAV sources.' }
  & ssh @taskSshOptions $taskTarget "cd '$RemoteDirectory' && tar -xzf voice-input.tar.gz && python3 build_voice.py && tar -czf voice-output.tar.gz -C output ."
  if ($LASTEXITCODE -ne 0) { throw 'Remote encoding or decode verification failed.' }
  & scp @taskSshOptions "${taskTarget}:$RemoteDirectory/voice-output.tar.gz" $taskOutputArchive
  if ($LASTEXITCODE -ne 0) { throw 'Could not retrieve encoded MP3 files.' }
  & tar -xzf $taskOutputArchive -C $taskOutput
  if ($LASTEXITCODE -ne 0) { throw 'Could not unpack MP3 files.' }
}
$taskReport = Get-Content -LiteralPath (Join-Path $taskOutput 'build-report.json') -Raw | ConvertFrom-Json
if ($taskReport.count -ne ($taskManifest.prompts.Count * 2)) { throw 'The report has an unexpected audio file count.' }
foreach ($taskRow in $taskReport.files) {
  $taskAsset = Join-Path $taskOutput "$($taskRow.language)/$($taskRow.id).mp3"
  if ((Get-Item -LiteralPath $taskAsset).Length -ne $taskRow.bytes) { throw "Downloaded asset size mismatch: $taskAsset" }
}
Write-Host "Verified $($taskReport.count) mono MP3 files ($($taskReport.total_bytes) bytes) in $taskOutput"
Write-Host 'Generation report: build-report.json. The running kiosk application was not modified.'
