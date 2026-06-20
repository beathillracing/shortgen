#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

version_code="$(
    sed -nE 's/^[[:space:]]*versionCode = ([0-9]+).*/\1/p' app/build.gradle.kts |
        head -n 1
)"
version_name="$(
    sed -nE 's/^[[:space:]]*versionName = "([^"]+)".*/\1/p' app/build.gradle.kts |
        head -n 1
)"
if [[ -z "$version_code" || -z "$version_name" ]]; then
    echo "Could not read versionCode/versionName from app/build.gradle.kts" >&2
    exit 1
fi

./gradlew \
    :app:lintFullPlayRelease \
    :app:bundleFullPlayRelease

output_dir="play-store/builds"
mkdir -p "$output_dir"

rm -f "$output_dir"/*.aab "$output_dir/SHA256SUMS"
cp app/build/outputs/bundle/fullPlayRelease/app-full-play-release.aab \
    "$output_dir/beathill-studio-v${version_name}-${version_code}.aab"

sha256sum "$output_dir"/*.aab > "$output_dir/SHA256SUMS"

printf 'Play Store bundles written to %s\n' "$output_dir"
