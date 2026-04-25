# Auris

**Auris** is a desktop audio library scanner for Linux, built for anyone who cares about the quality of their music collection.

It scans your music folders and gives you a deep technical analysis of every file — revealing clipping issues, dynamic range, spectral content, inter-sample peaks, and whether your files carry the frequency content you'd expect from their format.

---

![Auris Screenshot](screenshot.png)

---

## Features

- **Spectral content classification** — Full Spectrum / Reduced Spectrum / Limited Spectrum, based on measured frequency content rather than format claims
- **Spectral gap measurement** — the actual measured dB difference between high-frequency and full-spectrum content, so you can evaluate results yourself
- **True peak detection** — inter-sample peak measurement via ebur128 oversampling, catching distortion that standard peak measurement misses
- **Clipping risk detection** — identifies tracks with dangerously loud peaks, using true peak as primary signal
- **Dynamic range measurement** — reveals over-compressed or heavily limited tracks
- **Sample rate & bit depth reporting** — full technical breakdown per file
- **Compare Files** — compare 2–5 audio files side by side with a quality recommendation and clear reasoning
- **Multi-threaded scanning** — fast parallel analysis of large libraries
- **Progress bar with stop button** — cancel scans at any time
- **Filter & search** — filter by spectrum classification, search by filename or metadata
- **Export CSV** — save results for further analysis
- **Dark & light mode** — automatically follows your system theme
- **Open / Reveal in Folder** — quickly act on flagged files
- **Built-in help** — plain language explanations of every metric

---

## How It Works

Auris uses **FFmpeg** to perform analysis of each audio file across three passes:

1. **Spectral pass** — measures energy in frequency bands above 16kHz and 20kHz relative to the full signal, identifying how much high-frequency content is present
2. **Dynamic range pass** — measures peak and RMS levels via direct `astats` to calculate dynamic range reliably across all formats including FLAC
3. **True peak pass** — measures inter-sample peaks via `ebur128` oversampling, detecting distortion that standard peak measurement misses

Sample rate and bit depth are extracted separately via FFprobe.

Results are displayed in an interactive table with color-coded risk levels and exportable as CSV.

---

## Understanding Your Results

| Column | What it means |
|---|---|
| `max_volume` | Loudest sample peak in dBFS. Values close to 0.0 dB indicate potential clipping |
| `mean_volume` | Average loudness. Helps identify heavy compression |
| `risk` | Clipping risk: High / Moderate / Low. Uses true peak as primary signal when available |
| `cutoff_freq` | Frequency threshold used for spectral classification (Hz) |
| `spectral_gap_db` | Measured energy gap (dB) between >20kHz filtered signal and full signal. Larger = less high-frequency content present |
| `quality` | Spectral content classification — see below |
| `dynamic_range` | Peak minus RMS level (dB). Higher = more dynamic and natural sounding. Below 8 dB may indicate heavy compression |
| `true_peak` | Inter-sample peak (dBFS) via oversampling. Values above 0 indicate inter-sample clipping |
| `sample_rate` | Audio samples per second. 44100 = CD quality. 96000+ = hi-res |
| `bit_depth` | Bits per sample. 16-bit = CD quality. 24-bit = studio quality |

### Spectral Classification

| Label | What it means |
|---|---|
| **Full Spectrum** | High-frequency energy detected above 20kHz. Consistent with genuine lossless audio |
| **Reduced Spectrum** | Frequency content limited above 16kHz. May indicate a high-bitrate lossy source, or a 24-bit file with naturally limited high-frequency content |
| **Limited Spectrum** | Frequency content limited above 15kHz. Consistent with MP3 or other lossy encoding |

> **Important:** These labels describe *measured frequency content*, not a claim about how a file was encoded. Vocal and acoustic recordings naturally have limited high-frequency content regardless of format — a genuine lossless FLAC of a vocal performance may show a large spectral gap. 24-bit files are treated as minimum Reduced Spectrum since lossy encoders do not work in 24-bit. Use results as a guide alongside knowledge of your files' original source.

---

## Compare Files

The **Compare Files** feature lets you select 2–5 audio files and compare their quality characteristics side by side. Auris recommends which version to keep based on:

1. Spectral quality label (Full > Reduced > Limited)
2. Dynamic range (higher = more natural)
3. Sample rate, then bit depth as tiebreakers
4. Clipping risk flagged as a warning

Click **Compare Files** in the toolbar to open the comparison dialog.

---

## Requirements

- Linux
- FFmpeg (with ebur128 support — included in standard builds)
- libfuse2 (only needed for AppImage)
- libxcb-cursor0 (only needed for AppImage)
- Python 3.12+ (only needed if running from source)

---

## Installation (AppImage — recommended)

1. Download `Auris-x86_64.AppImage` from the [latest release](https://github.com/noisetta/auris/releases)
2. Make it executable and run:

```bash
chmod +x Auris-x86_64.AppImage
./Auris-x86_64.AppImage
```

Install dependencies if needed (Ubuntu / Debian / Pop!_OS):

```bash
sudo apt install ffmpeg libfuse2 libxcb-cursor0
```

## Installation (from source)

```bash
git clone https://github.com/noisetta/auris.git
cd auris
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

---

## Dependencies

- [PySide6](https://pypi.org/project/PySide6/) — GUI framework
- [FFmpeg](https://ffmpeg.org/) — audio analysis engine

---

## Changelog

### v1.1.0
- **Compare Files** — new feature to compare 2–5 audio files side by side with quality recommendation
- **Spectral classification renamed** — labels now describe measured frequency content (Full Spectrum / Reduced Spectrum / Limited Spectrum) rather than making provenance claims (Lossless / Likely Lossy / Lossy)
- **Spectral Gap column** — shows actual measured dB gap so users can evaluate results directly
- **True Peak column** — inter-sample peak measurement via ebur128 oversampling
- **Clipping risk improved** — now uses true peak as primary signal, more accurate than sample-peak alone
- **Dynamic range fixed for FLAC** — uses a separate analysis pass to avoid a known ffmpeg asplit/-inf bug affecting some FLAC files
- **24-bit refinement** — 24-bit files with large spectral gaps are classified as Reduced Spectrum minimum, reflecting that lossy encoders do not work in 24-bit
- **Help text and tooltips updated** — more accurate explanations of what each metric measures and its limitations

### v1.0.2
- Updated quality labels to Lossless / Likely Lossy / Lossy for clarity
- Added disclaimer in help dialog about spectral analysis limitations
- Added support for .m4a, .aac, .ogg, and .opus audio formats

### v1.0.1
- Column header display fix

### v1.0.0
- Initial release

---

## Contributing

Contributions are welcome. Feel free to open issues or pull requests on GitHub.

---

## Support Auris

If Auris is useful to you, consider supporting development:

☕ [Ko-fi](https://ko-fi.com/noisetta) — one-time tip

---

## License

MIT License — free to use, modify, and distribute.
