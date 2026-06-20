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
notes="${1:-Background completion notifications, encrypted sessions, account switching, separate social connections and improved publishing results.}"

if [[ -z "$version_code" || -z "$version_name" ]]; then
    echo "Could not read versionCode/versionName from app/build.gradle.kts" >&2
    exit 1
fi

./gradlew \
    :app:assembleFullDirectRelease \
    :app:assembleCreatorDirectRelease

public_dir="../assets/public"
full_apk="$public_dir/shortgen-android.apk"
creator_apk="$public_dir/shortgen-creator-android.apk"

install -m 0644 \
    app/build/outputs/apk/fullDirect/release/app-full-direct-release.apk \
    "$full_apk"
install -m 0644 \
    app/build/outputs/apk/creatorDirect/release/app-creator-direct-release.apk \
    "$creator_apk"

update_manifest() {
    local manifest="$1"
    local name="$2"
    local hash="$3"
    local temp
    temp="$(mktemp)"
    jq \
        --argjson version_code "$version_code" \
        --arg version_name "$name" \
        --arg sha256 "$hash" \
        --arg notes "$notes" \
        '
        .version_code = $version_code |
        .version_name = $version_name |
        .sha256 = $sha256 |
        .releases = (
            [.releases[] | select(.version_code != $version_code)] +
            [{
                version_code: $version_code,
                version_name: $version_name,
                notes: $notes
            }] |
            sort_by(.version_code)
        )
        ' \
        "$manifest" >"$temp"
    chmod 0644 "$temp"
    mv "$temp" "$manifest"
}

update_manifest \
    "$public_dir/shortgen-full-version.json" \
    "$version_name" \
    "$(sha256sum "$full_apk" | cut -d' ' -f1)"
update_manifest \
    "$public_dir/shortgen-creator-version.json" \
    "${version_name}-creator" \
    "$(sha256sum "$creator_apk" | cut -d' ' -f1)"

echo "Published direct APKs for version ${version_name} (${version_code})."
