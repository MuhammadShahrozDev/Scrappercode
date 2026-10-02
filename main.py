import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

SUB_PROJECTS = [
    BASE_DIR / "YCombinator" / "main.py",
    BASE_DIR / "Wellfound" / "main.py",
    BASE_DIR / "Linkedin-Scrapper" / "main.py",
    BASE_DIR / "postprocessing" / "main.py",
]

def run_subproject(script_path):
    print(f"\n{'='*60}")
    print(f"[*] Running: {script_path}")
    print(f"{'='*60}")

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=script_path.parent,
    )

    if result.returncode != 0:
        print(f"[!] {script_path} exited with code {result.returncode}")
        return False

    return True


def main():
    failures = []

    for script in SUB_PROJECTS:
        if not script.exists():
            print(f"[!] Skipping missing script: {script}")
            continue

        success = run_subproject(script)
        if not success:
            print(f"[!] Continuing to the next stage after {script.name} failed.")
            failures.append(script.name)

    if failures:
        print(f"\n[!] Pipeline completed with {len(failures)} failed subproject(s): {', '.join(failures)}")
        sys.exit(1)

    print("\n[+] All sub-projects completed successfully.")


if __name__ == "__main__":
    main()