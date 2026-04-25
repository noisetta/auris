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

        # --- ffmpeg pass 1: volume and spectral analysis ---
        result = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-i", file_path,
                "-vn",
                "-filter_complex", (
                    "asplit=3[a][b][c];"
                    "[a]highpass=f=20000,astats=metadata=1:reset=1[high];"
                    "[b]highpass=f=16000,astats=metadata=1:reset=1[mid];"
                    "[c]volumedetect[vol]"
                ),
                "-map", "[high]",
                "-map", "[mid]",
                "-map", "[vol]",
                "-f", "null",
                "/dev/null",
            ],
            capture_output=True,
            text=True,
        )
        output = result.stderr

        # --- ffmpeg pass 2: dynamic range via direct astats (no split) ---
        # Using a separate pass avoids the asplit+astats -inf bug on FLAC files
        dr_result = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-i", file_path,
                "-vn",
                "-af", "astats",
                "-f", "null",
                "/dev/null",
            ],
            capture_output=True,
            text=True,
        )
        dr_output = dr_result.stderr

        # --- Volume ---
        max_match = re.search(r"max_volume:\s*([-\d.]+)\s*dB", output)
        mean_match = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", output)

        if not max_match or not mean_match:
            return _failed_result("volume_parse_failed", sample_rate, bit_depth)

        max_vol = float(max_match.group(1))
        mean_vol = float(mean_match.group(1))

        # --- Spectral ---
        # Filter graph now has 3 outputs: [high], [mid], [vol]
        # We need high_rms and mid_rms for cutoff detection.
        # full_rms comes from the separate DR pass (dr_output).
        rms_matches = re.findall(r"Overall.*?RMS level dB:\s*([-\d.inf]+)", output, re.DOTALL)

        if len(rms_matches) < 2:
            return _failed_result("spectral_parse_failed", sample_rate, bit_depth)

        def parse_rms(val: str) -> float:
            if val in ("-inf", "inf", "nan"):
                return -999.0
            return float(val)

        high_rms = parse_rms(rms_matches[0])
        mid_rms = parse_rms(rms_matches[1])

        # full_rms from the DR pass (direct astats, no split)
        dr_rms_for_cutoff = re.search(r"RMS level dB:\s*([-\d.inf]+)", dr_output)
        full_rms = parse_rms(dr_rms_for_cutoff.group(1)) if dr_rms_for_cutoff else -999.0

        # --- Dynamic range (from separate pass, no split filter) ---
        # The asplit filter graph produces -inf for astats on some FLAC files.
        # A direct single-stream astats pass is reliable across all formats.
        dynamic_range = None
        dr_peak_m = re.search(r"Peak level dB:\s*([-\d.]+)", dr_output)
        dr_rms_m = re.search(r"RMS level dB:\s*([-\d.inf]+)", dr_output)
        if dr_peak_m and dr_rms_m:
            try:
                dr_peak = float(dr_peak_m.group(1))
                dr_rms = parse_rms(dr_rms_m.group(1))
                if dr_rms != -999.0:
                    dynamic_range = round(dr_peak - dr_rms, 1)
            except ValueError:
                pass

        # --- Frequency cutoff ---
        # Measures energy gap between filtered and full spectrum.
        # Labels describe what was measured (frequency content present/limited/absent)
        # rather than making claims about encode provenance.
        # Spectral gap = how much quieter the high-frequency band is vs full signal.
        # Expressed as full_rms - high_rms so larger positive = more content absent.
        # When the filtered stream is silent (-999 sentinel), substitute a floor
        # value of -80 dB — this is more honest than returning None for lossy files
        # where the absence of high-frequency content IS the meaningful result.
        HIGH_FLOOR = -80.0

        high_rms_eff = high_rms if high_rms != -999.0 else HIGH_FLOOR
        mid_rms_eff = mid_rms if mid_rms != -999.0 else HIGH_FLOOR

        if full_rms != -999.0:
            high_gap = full_rms - high_rms_eff   # positive = high freq absent
            mid_gap = full_rms - mid_rms_eff
            spectral_gap_db = round(high_gap, 1)
        else:
            # Can't compute without full_rms — mark as unknown
            high_gap = None
            mid_gap = None
            spectral_gap_db = None

        # Classify based on gap — larger gap means more high-freq content absent.
        # 24-bit files are almost never lossy-sourced — lossy encoders work in
        # 16-bit internally. If bit depth is 24, cap classification at
        # Reduced Spectrum minimum regardless of spectral gap, since the limited
        # high-frequency content likely reflects the source recording or
        # instrumentation rather than lossy encoding.
        if high_gap is not None and high_gap < 40:
            cutoff = 21000
            quality = "Full Spectrum"
        elif mid_gap is not None and mid_gap < 40:
            cutoff = 18000
            quality = "Reduced Spectrum"
        elif bit_depth is not None and bit_depth >= 24:
            # 24-bit file with large spectral gap — likely genuine lossless
            # with naturally limited high-frequency content (vocal, acoustic, etc.)
            cutoff = 18000
            quality = "Reduced Spectrum"
        else:
            cutoff = 15000
            quality = "Limited Spectrum"

        # --- True peak measurement (inter-sample peaks via ebur128) ---
        # volumedetect misses inter-sample clipping. ebur128 with peak=true
        # uses oversampling to detect peaks that exceed 0dBFS between samples.
        true_peak = None
        try:
            tp_result = subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-i", file_path,
                    "-vn",
                    "-af", "ebur128=peak=true",
                    "-f", "null",
                    "/dev/null",
                ],
                capture_output=True,
                text=True,
            )
            tp_match = re.search(
                r"True peak\s*:\s*Peak:\s*([-\d.]+)\s*dBFS",
                tp_result.stderr
            )
            if tp_match:
                true_peak = float(tp_match.group(1))
        except Exception:
            pass

        return {
            "max_volume": max_vol,
            "mean_volume": mean_vol,
            "cutoff_freq": cutoff,
            "spectral_gap_db": spectral_gap_db,
            "quality": quality,
            "dynamic_range": dynamic_range,
            "true_peak": true_peak,
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