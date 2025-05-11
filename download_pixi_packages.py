import argparse
import os
import sys
import urllib.parse
import yaml
import requests

# --- Configuration ---
# Version of the pixi.lock format this script is primarily designed for
SUPPORTED_LOCKFILE_VERSION = 6
# Timeout for network requests in seconds
REQUEST_TIMEOUT = 60
# Chunk size for downloading files
DOWNLOAD_CHUNK_SIZE = 8192


def parse_arguments():
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Download Conda packages specified in a pixi.lock file into a channel structure."
    )
    parser.add_argument(
        "lockfile", metavar="PIXI_LOCKFILE", help="Path to the pixi.lock file."
    )
    parser.add_argument(
        "output_dir",
        metavar="OUTPUT_DIRECTORY",
        help="Base directory to create channel structure and download packages into.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force download even if the file already exists in the output directory.",
    )
    return parser.parse_args()


def load_lockfile(lockfile_path):
    """Loads and parses the YAML lockfile."""
    if not os.path.exists(lockfile_path):
        print(f"Error: Lockfile not found at '{lockfile_path}'", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(lockfile_path):
        print(f"Error: Lockfile path '{lockfile_path}' is not a file.", file=sys.stderr)
        sys.exit(1)
    try:
        with open(lockfile_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            print(
                f"Error: Lockfile '{lockfile_path}' is not a valid YAML dictionary.",
                file=sys.stderr,
            )
            sys.exit(1)

        file_version = data.get("version")
        if file_version != SUPPORTED_LOCKFILE_VERSION:
            print(
                f"Warning: This script is designed for pixi.lock version {SUPPORTED_LOCKFILE_VERSION}. "
                f"The provided file is version '{file_version}'. "
                "Proceeding, but there might be issues if the structure changed significantly.",
                file=sys.stderr,
            )
        return data
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file '{lockfile_path}': {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(
            f"An unexpected error occurred while reading '{lockfile_path}': {e}",
            file=sys.stderr,
        )
        sys.exit(1)


def extract_conda_package_urls(lockfile_data):
    """Extracts all unique Conda package URLs from the lockfile data."""
    urls = set()
    # Primary source of URLs in v6 format
    if "packages" in lockfile_data and isinstance(lockfile_data["packages"], list):
        for package_info in lockfile_data["packages"]:
            if isinstance(package_info, dict) and "conda" in package_info:
                url = package_info["conda"]
                if isinstance(url, str) and url.startswith("http"):
                    urls.add(url)
                else:
                    print(
                        f"Warning: Skipping malformed or non-HTTP URL in top-level 'packages' list: {url}",
                        file=sys.stderr,
                    )
            # else:
            #     print(f"Debug: Skipping entry in top-level 'packages' not matching expected structure: {package_info}", file=sys.stderr)

    # Fallback: Check within environments if the primary method yielded no URLs
    # This is more for robustness or if the structure guarantees diverge.
    if (
        not urls
        and "environments" in lockfile_data
        and isinstance(lockfile_data["environments"], dict)
    ):
        print(
            "Info: No URLs found in top-level 'packages'. Checking 'environments' section.",
            file=sys.stderr,
        )
        for env_name, env_data in lockfile_data["environments"].items():
            if (
                isinstance(env_data, dict)
                and "packages" in env_data
                and isinstance(env_data["packages"], dict)
            ):
                for platform, platform_packages_list in env_data["packages"].items():
                    if isinstance(platform_packages_list, list):
                        for pkg_url_map in platform_packages_list:
                            if isinstance(pkg_url_map, dict) and "conda" in pkg_url_map:
                                url = pkg_url_map["conda"]
                                if isinstance(url, str) and url.startswith("http"):
                                    urls.add(url)
                                # else:
                                #     print(f"Debug: Skipping malformed 'conda' entry in environment '{env_name}/{platform}': {url}", file=sys.stderr)

    if not urls:
        print("No Conda package URLs found in the lockfile.", file=sys.stderr)
    return list(urls)


def download_package(url, base_output_dir, force_download=False):
    """
    Downloads a single package URL into the appropriate platform subdirectory
    within the base_output_dir.
    """
    output_path = ""  # Initialize for cleanup logic
    try:
        parsed_url = urllib.parse.urlparse(url)
        filename = os.path.basename(parsed_url.path)
        if not filename:
            print(
                f"Error: Could not determine filename from URL: {url}. Skipping.",
                file=sys.stderr,
            )
            return False

        # Extract platform subdir from URL (e.g., linux-64, noarch)
        # Path components: e.g. /conda-forge/linux-64/package-name.conda
        path_components = [comp for comp in parsed_url.path.split("/") if comp]
        if (
            len(path_components) < 2
        ):  # Needs at least channel/subdir/filename or subdir/filename
            print(
                f"Error: Could not determine platform subdirectory from URL path: {parsed_url.path}. Skipping {filename}.",
                file=sys.stderr,
            )
            return False

        # The subdir is typically the second to last component in the path
        # e.g. ['conda-forge', 'linux-64', 'some-package.conda'] -> 'linux-64'
        # e.g. ['my-channel', 'noarch', 'other-package.conda'] -> 'noarch'
        platform_subdir_name = path_components[-2]

        # Create platform-specific directory
        platform_output_dir = os.path.join(base_output_dir, platform_subdir_name)
        if not os.path.exists(platform_output_dir):
            try:
                os.makedirs(platform_output_dir, exist_ok=True)
                print(f"Created platform directory: '{platform_output_dir}'")
            except OSError as e:
                print(
                    f"Error: Could not create platform directory '{platform_output_dir}': {e}",
                    file=sys.stderr,
                )
                return False

        output_path = os.path.join(platform_output_dir, filename)

        if not force_download and os.path.exists(output_path):
            print(
                f"Skipping '{filename}': File already exists in '{platform_output_dir}'."
            )
            return True  # Considered a success as the file is present

        print(f"Downloading '{filename}' to '{platform_output_dir}' from '{url}'...")
        response = requests.get(url, stream=True, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                f.write(chunk)

        print(f"Successfully downloaded '{filename}' to '{platform_output_dir}'.")
        return True

    except requests.exceptions.HTTPError as e:
        print(
            f"HTTP Error downloading '{filename}': {e.response.status_code} {e.response.reason}",
            file=sys.stderr,
        )
    except requests.exceptions.ConnectionError as e:
        print(f"Connection Error downloading '{filename}': {e}", file=sys.stderr)
    except requests.exceptions.Timeout as e:
        print(f"Timeout during download of '{filename}': {e}", file=sys.stderr)
    except requests.exceptions.RequestException as e:
        print(f"Error downloading '{filename}': {e}", file=sys.stderr)
    except Exception as e:
        print(
            f"An unexpected error occurred while processing '{url}': {e}",
            file=sys.stderr,
        )

    # Cleanup partially downloaded file if an error occurred
    if output_path and os.path.exists(output_path) and os.path.isfile(output_path):
        try:
            # Check if file size is 0, often indicative of an interrupted download start
            if os.path.getsize(output_path) == 0:
                print(
                    f"Note: '{filename}' was 0 bytes and might be a partial download due to error.",
                    file=sys.stderr,
                )
            os.remove(output_path)
            print(
                f"Cleaned up potentially incomplete file: {output_path}",
                file=sys.stderr,
            )
        except OSError as oe:
            print(f"Error cleaning up file {output_path}: {oe}", file=sys.stderr)
    return False


def main():
    """Main function to orchestrate the download process."""
    args = parse_arguments()

    # Create base output directory if it doesn't exist
    if not os.path.exists(args.output_dir):
        try:
            os.makedirs(args.output_dir, exist_ok=True)  # exist_ok=True is fine here
            print(f"Created base output directory: '{args.output_dir}'")
        except OSError as e:
            print(
                f"Error: Could not create base output directory '{args.output_dir}': {e}",
                file=sys.stderr,
            )
            sys.exit(1)
    elif not os.path.isdir(args.output_dir):
        print(
            f"Error: Output path '{args.output_dir}' exists but is not a directory.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.access(args.output_dir, os.W_OK):
        print(
            f"Error: Output directory '{args.output_dir}' is not writable.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Loading lockfile: '{args.lockfile}'")
    lockfile_data = load_lockfile(args.lockfile)

    print("Extracting Conda package URLs...")
    conda_urls = extract_conda_package_urls(lockfile_data)

    if not conda_urls:
        print("No packages to download. Exiting.")
        sys.exit(0)

    print(f"\nFound {len(conda_urls)} unique Conda package URLs to process.")

    success_count = 0
    failure_count = 0
    skipped_count = 0

    for i, url in enumerate(conda_urls, 1):
        print(f"\n--- Processing package {i}/{len(conda_urls)} ---")

        # Determine potential filename and subdir for pre-check if not forcing
        # This is a bit more complex due to subdir logic being inside download_package
        # For a simple skipped count, we can rely on download_package's return or its print.
        # Let's refine the skipped logic slightly.

        # The `download_package` function now handles the "already exists" check and prints it.
        # We just need to interpret its return value.

        is_successful_or_skipped = download_package(url, args.output_dir, args.force)

        if is_successful_or_skipped:
            success_count += 1
            # To accurately count skips, we need more info from download_package or check here.
            # For simplicity, if not forcing and file exists, download_package returns True.
            # We can refine this if a distinct "skipped" vs "newly_downloaded" count is critical.
            # The current print from download_package already says "Skipping..."
        else:
            failure_count += 1
        # print("-" * 30) # Separator is now within the loop start

    print("\n--- Download Summary ---")
    print(f"  Total URLs found: {len(conda_urls)}")
    # success_count includes files that were successfully downloaded + files that were skipped (already existed)
    print(f"  Successfully processed (downloaded or already existed): {success_count}")
    print(f"  Failed downloads: {failure_count}")
    print("------------------------")

    if failure_count > 0:
        print(
            "\nSome packages failed to download. Please check the errors above.",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        print("\nAll specified packages processed successfully.")


if __name__ == "__main__":
    # Ensure required libraries are available
    try:
        import yaml
        import requests
    except ImportError as e:
        print(
            f"Error: Missing required Python library. Please install PyYAML and requests.",
            file=sys.stderr,
        )
        print(
            f"You can typically install them using: pip install PyYAML requests",
            file=sys.stderr,
        )
        print(f"(Details: {e})", file=sys.stderr)
        sys.exit(1)
    main()
