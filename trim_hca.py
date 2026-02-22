import os
import sys
import argparse


def trim_file(input_path: str, output_dir: str) -> bool:
    with open(input_path, "rb") as f:
        data = f.read()

    marker = b"HCA"
    idx = data.find(marker)

    if idx == -1:
        print(f"  SKIP: 'HCA' not found in {input_path}")
        return False

    basename = os.path.splitext(os.path.basename(input_path))[0]
    output_path = os.path.join(output_dir, basename + ".hca")

    trimmed = data[idx:]
    with open(output_path, "wb") as f:
        f.write(trimmed)

    print(f"  OK: trimmed {idx} byte(s) -> {output_path}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Trim bytes before the first 'HCA' marker and save with .hca extension."
    )
    parser.add_argument("input_dir", help="Directory containing files to process")
    parser.add_argument(
        "output_dir",
        nargs="?",
        help="Directory to write trimmed files (default: same as input)",
    )
    args = parser.parse_args()

    input_dir = args.input_dir
    output_dir = args.output_dir or input_dir

    if not os.path.isdir(input_dir):
        print(f"Error: '{input_dir}' is not a directory.")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
    if not files:
        print("No files found in input directory.")
        return

    print(f"Processing {len(files)} file(s) from '{input_dir}'...")
    processed = 0
    for filename in files:
        input_path = os.path.join(input_dir, filename)
        if trim_file(input_path, output_dir):
            processed += 1

    print(f"\nDone. {processed}/{len(files)} file(s) trimmed.")


if __name__ == "__main__":
    main()
