#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

./gradlew \
    :app:bundleFullPlayRelease

output_dir="play-store/builds"
mkdir -p "$output_dir"

rm -f "$output_dir"/*.aab "$output_dir/SHA256SUMS"
cp app/build/outputs/bundle/fullPlayRelease/app-full-play-release.aab \
    "$output_dir/beathill-studio-v0.10.0-10.aab"

sha256sum "$output_dir"/*.aab > "$output_dir/SHA256SUMS"

printf 'Play Store bundles written to %s\n' "$output_dir"
