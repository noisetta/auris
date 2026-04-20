import csv
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from audio_quality import analyze_file

AUDIO_EXTENSIONS = (".flac", ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus")


def find_audio_files(directory: str) -> list[str]:
    """Recursively find all audio files in a directory."""
    matches = []
    for root, _, files in os.walk(directory):
        for filename in files:
            if filename.lower().endswith(AUDIO_EXTENSIONS):
                matches.append(os.path.join(root, filename))
    return sorted(matches)


def calculate_risk(max_volume: float, mean_volume: float) -> str:
    """Apply risk classification logic."""
    if max_volume >= -0.1 and mean_volume > -13:
        return "high"
    elif max_volume >= -0.5 and mean_volume > -15:
        return "moderate"
    else:
        return "low"


def scan_directory(directory: str, output_csv: str, progress_callback=None, should_stop=None, max_workers: int = 4) -> int:
    """
    Scan all audio files in a directory and write results to a CSV file.
    Uses a thread pool to scan multiple files in parallel.
    """
    files = find_audio_files(directory)
    total = len(files)
    results = {}
    counter_lock = threading.Lock()
    completed = [0]

    def scan_one(file_path: str) -> tuple:
        if should_stop and should_stop():
            raise InterruptedError("Scan stopped by user.")

        result = analyze_file(file_path)

        if result["error"] or result["max_volume"] is None:
            row = [file_path, "", "", "scan_failed", "", "scan_failed", "", result.get("sample_rate", ""), result.get("bit_depth", "")]
        else:
            max_vol = result["max_volume"]
            mean_vol = result["mean_volume"]
            risk = calculate_risk(max_vol, mean_vol)
            cutoff = result["cutoff_freq"]
            quality = result["quality"]
            dynamic_range = result.get("dynamic_range", "")
            sample_rate = result.get("sample_rate", "")
            bit_depth = result.get("bit_depth", "")
            row = [file_path, max_vol, mean_vol, risk, cutoff, quality, dynamic_range, sample_rate, bit_depth]

        with counter_lock:
            completed[0] += 1
            current = completed[0]

        if progress_callback:
            progress_callback(current, total, file_path)

        return file_path, row

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(scan_one, f): f for f in files}
        for future in as_completed(futures):
            try:
                file_path, row = future.result()
                results[file_path] = row
            except InterruptedError:
                executor.shutdown(wait=False, cancel_futures=True)
                break
            except Exception as e:
                file_path = futures[future]
                results[file_path] = [file_path, "", "", "scan_failed", "", "scan_failed"]
                print(f"Error scanning {file_path}: {e}")

    # Write results in original file order
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["file", "max_volume", "mean_volume", "risk", "cutoff_freq", "quality", "dynamic_range", "sample_rate", "bit_depth"])
        for file_path in files:
            if file_path in results:
                writer.writerow(results[file_path])

    return len(results)