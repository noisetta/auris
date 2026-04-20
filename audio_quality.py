import re
import subprocess


def analyze_file(file_path: str) -> dict:
    """
    Single ffmpeg pass extracting volume, spectral, and dynamic range stats.
    Separate ffprobe call for sample rate and bit depth.
    """
    try:
        # --- ffprobe for sample rate and bit depth ---
        probe = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=sample_rate,bits_per_raw_sample",
                "-of", "default=noprint_wrappers=1",
                file_path,
            ],
            capture_output=True,
            text=True,
        )

        sample_rate = None
        bit_depth = None

        for line in probe.stdout.splitlines():
            if line.startswith("sample_rate="):
                try:
                    sample_rate = int(line.split("=")[1].strip())
                except ValueError:
                    pass
            elif line.startswith("bits_per_raw_sample="):
                try:
                    val = int(line.split("=")[1].strip())
                    bit_depth = val if val > 0 else None
                except ValueError:
                    pass

        # --- ffmpeg for volume, spectral and dynamic range ---
        result = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-i", file_path,
                "-vn",
                "-filter_complex", (
                    "asplit=4[a][b][c][d];"
                    "[a]highpass=f=20000,astats=metadata=1:reset=1[high];"
                    "[b]highpass=f=16000,astats=metadata=1:reset=1[mid];"
                    "[c]astats=metadata=1:reset=1[full];"
                    "[d]volumedetect[vol]"
                ),
                "-map", "[high]",
                "-map", "[mid]",
                "-map", "[full]",
                "-map", "[vol]",
                "-f", "null",
                "/dev/null",
            ],
            capture_output=True,
            text=True,
        )
        output = result.stderr

        # --- Volume ---
        max_match = re.search(r"max_volume:\s*([-\d.]+)\s*dB", output)
        mean_match = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", output)

        if not max_match or not mean_match:
            return _failed_result("volume_parse_failed", sample_rate, bit_depth)

        max_vol = float(max_match.group(1))
        mean_vol = float(mean_match.group(1))

        # --- Spectral ---
        rms_matches = re.findall(r"Overall.*?RMS level dB:\s*([-\d.inf]+)", output, re.DOTALL)

        if len(rms_matches) < 3:
            return _failed_result("spectral_parse_failed", sample_rate, bit_depth)

        def parse_rms(val: str) -> float:
            if val in ("-inf", "inf", "nan"):
                return -999.0
            return float(val)

        high_rms = parse_rms(rms_matches[0])
        mid_rms = parse_rms(rms_matches[1])
        full_rms = parse_rms(rms_matches[2])

        # --- Dynamic range ---
        peak_match = re.search(r"Overall.*?Peak level dB:\s*([-\d.]+)", output, re.DOTALL)
        rms_overall_match = re.search(r"Overall.*?RMS level dB:\s*([-\d.inf]+)", output, re.DOTALL)

        dynamic_range = None
        if peak_match and rms_overall_match:
            try:
                peak = float(peak_match.group(1))
                rms = parse_rms(rms_overall_match.group(1))
                if rms != -999.0:
                    dynamic_range = round(peak - rms, 1)
            except ValueError:
                pass

        # --- Frequency cutoff ---
        high_gap = high_rms - full_rms
        mid_gap = mid_rms - full_rms

        if high_gap > 40:
            cutoff = 21000
            quality = "Lossless"
        elif mid_gap > 40:
            cutoff = 18000
            quality = "Likely Lossy"
        else:
            cutoff = 15000
            quality = "Lossy"

        return {
            "max_volume": max_vol,
            "mean_volume": mean_vol,
            "cutoff_freq": cutoff,
            "quality": quality,
            "dynamic_range": dynamic_range,
            "sample_rate": sample_rate,
            "bit_depth": bit_depth,
            "error": None,
        }

    except Exception as e:
        return _failed_result(str(e), None, None)


def _failed_result(reason: str, sample_rate, bit_depth) -> dict:
    return {
        "max_volume": None,
        "mean_volume": None,
        "cutoff_freq": None,
        "quality": "scan_failed",
        "dynamic_range": None,
        "sample_rate": sample_rate,
        "bit_depth": bit_depth,
        "error": reason,
    }