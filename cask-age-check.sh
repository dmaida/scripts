#!/usr/bin/env bash
# cask-age-check.sh — Flag Homebrew casks that exceed a max lib-years threshold.
#
# USAGE:
#   ./cask-age-check.sh [--max-years N] [--warn-years N] [--quiet] [--json]
#
# OPTIONS:
#   --max-years N    Casks older than N years are flagged as CRITICAL  (default: 2)
#   --warn-years N   Casks older than N years are flagged as WARNING    (default: 1)
#   --quiet          Suppress the summary table; only exit non-zero if criticals exist
#   --json           Emit JSON output instead of a human-readable table
#   -h, --help       Show this help and exit
#
# EXIT CODES:
#   0  All casks are within the max-years threshold
#   1  One or more casks exceed the max-years threshold (CRITICAL)
#   2  Script error (brew not found, etc.)

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
MAX_YEARS=2
WARN_YEARS=1
QUIET=false
JSON=false

# ── Colours (disabled when not a tty) ─────────────────────────────────────────
if [ -t 1 ]; then
  RED='\033[0;31m'
  YELLOW='\033[0;33m'
  GREEN='\033[0;32m'
  CYAN='\033[0;36m'
  BOLD='\033[1m'
  RESET='\033[0m'
else
  RED=''
  YELLOW=''
  GREEN=''
  CYAN=''
  BOLD=''
  RESET=''
fi

# ── Argument parsing ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
  --max-years)
    MAX_YEARS="$2"
    shift 2
    ;;
  --warn-years)
    WARN_YEARS="$2"
    shift 2
    ;;
  --quiet)
    QUIET=true
    shift
    ;;
  --json)
    JSON=true
    shift
    ;;
  -h | --help)
    sed -n '/^# USAGE:/,/^[^#]/{ /^[^#]/d; s/^# \{0,2\}//; p }' "$0"
    exit 0
    ;;
  *)
    echo "Unknown option: $1" >&2
    exit 2
    ;;
  esac
done

# ── Sanity checks ─────────────────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
  echo "Error: brew not found in PATH." >&2
  exit 2
fi

# Require bc for floating-point comparisons (ships with macOS)
if ! command -v bc &>/dev/null; then
  echo "Error: bc not found (needed for date arithmetic)." >&2
  exit 2
fi

# ── Helper: compute fractional years between two ISO-8601 dates ───────────────
years_between() {
  local from="$1" # e.g. 2022-03-15
  local to="$2"   # e.g. 2024-09-01

  # Convert to epoch seconds (macOS date syntax)
  local epoch_from epoch_to
  epoch_from=$(date -j -f "%Y-%m-%d" "$from" "+%s" 2>/dev/null) || {
    echo "0"
    return
  }
  epoch_to=$(date -j -f "%Y-%m-%d" "$to" "+%s" 2>/dev/null) || {
    echo "0"
    return
  }

  # bc omits the leading zero for values < 1 (e.g. ".90" instead of "0.90")
  echo "scale=2; ($epoch_to - $epoch_from) / 31557600" | bc | sed 's/^\./0./'
}

# ── Helper: fetch the date the installed version was first committed to the tap ─
# Strategy (in order of preference):
#   1. Git log -S on the tap's .rb file: find when this exact version string
#      was *introduced* (oldest commit containing it). This approximates the
#      upstream release date regardless of when you installed it.
#   2. Brew receipt mtime: the filesystem modification time of the installed
#      receipt directory, which is set when `brew install` ran.
#   3. Give up and return empty string.
get_version_date() {
  local cask="$1"
  local target_version="$2"

  # -- Strategy 1: tap git history -----------------------------------------
  local cask_file
  # homebrew-cask uses a single-letter subdirectory layout
  local first_char
  first_char=$(echo "$cask" | cut -c1)
  cask_file="$(brew --repository)/Library/Taps/homebrew/homebrew-cask/Casks/${first_char}/${cask}.rb"
  if [[ ! -f "$cask_file" ]]; then
    # flat layout (third-party taps) or name differs
    cask_file=$(find "$(brew --repository)/Library/Taps" -name "${cask}.rb" 2>/dev/null | head -1)
  fi

  if [[ -n "$cask_file" && -f "$cask_file" ]]; then
    # -S picks commits that added/removed the string; --reverse gives oldest first
    local version_date
    version_date=$(git -C "$(dirname "$cask_file")" log \
      --reverse --format="%as" \
      -S "$target_version" \
      -- "$cask_file" 2>/dev/null |
      head -1)
    if [[ -n "$version_date" ]]; then
      echo "$version_date"
      return
    fi
  fi

  # -- Strategy 2: receipt directory mtime ----------------------------------
  # Brew stores installed cask metadata under $(brew --prefix)/Caskroom/<cask>/<version>
  local receipt_dir
  receipt_dir="$(brew --prefix)/Caskroom/${cask}/${target_version}"
  if [[ -d "$receipt_dir" ]]; then
    # stat -f "%Sm" with format %Y-%m-%d (macOS stat)
    local mtime
    mtime=$(stat -f "%Sm" -t "%Y-%m-%d" "$receipt_dir" 2>/dev/null)
    if [[ -n "$mtime" ]]; then
      echo "$mtime"
      return
    fi
  fi

  echo "" # unknown
}

# ── Main logic ─────────────────────────────────────────────────────────────────
TODAY=$(date "+%Y-%m-%d")

$QUIET || echo -e "\n${BOLD}${CYAN}🍺  Checking outdated casks (greedy)…${RESET}\n"

# Run brew outdated and capture output
# Format per line: "<name>  <current_version> != <latest_version>"
OUTDATED=$(brew outdated --cask --greedy --verbose 2>/dev/null) || true

if [[ -z "$OUTDATED" ]]; then
  $QUIET || echo -e "${GREEN}✓ All casks are up to date.${RESET}\n"
  exit 0
fi

# ── Collect results ────────────────────────────────────────────────────────────
declare -a RESULTS=()
CRITICAL_COUNT=0
WARN_COUNT=0
OK_COUNT=0

while IFS= read -r line; do
  [[ -z "$line" ]] && continue

  # brew outdated --cask --greedy --verbose output format:
  #   brave-browser (1.77.101.0) != 1.88.136.0      ← with parens (common)
  #   brave-browser 1.77.101.0 != 1.88.136.0        ← without parens (some versions)
  # Extract everything after " != " as latest, and the middle token as installed.
  cask=$(echo "$line" | sed 's/ .*//')
  latest_ver=$(echo "$line" | sed 's/.* != //')
  # installed: strip cask name and latest_ver, remove any surrounding parens
  installed_ver=$(echo "$line" | sed "s/^${cask} //; s/ != ${latest_ver}//" | tr -d '()')

  # Get date when the *installed* version was released (lib-years = staleness)
  installed_date=$(get_version_date "$cask" "$installed_ver")

  if [[ -z "$installed_date" ]]; then
    age_years="?"
    status="UNKNOWN"
  else
    age_years=$(years_between "$installed_date" "$TODAY")
    # Compare with threshold
    is_critical=$(echo "$age_years >= $MAX_YEARS" | bc)
    is_warn=$(echo "$age_years >= $WARN_YEARS" | bc)

    if [[ "$is_critical" == "1" ]]; then
      status="CRITICAL"
      ((CRITICAL_COUNT++)) || true
    elif [[ "$is_warn" == "1" ]]; then
      status="WARN"
      ((WARN_COUNT++)) || true
    else
      status="OK"
      ((OK_COUNT++)) || true
    fi
  fi

  RESULTS+=("${cask}|${installed_ver}|${latest_ver}|${installed_date:-unknown}|${age_years}|${status}")
done <<<"$OUTDATED"

# ── Output ─────────────────────────────────────────────────────────────────────
if $JSON; then
  echo "["
  total=${#RESULTS[@]}
  idx=0
  for entry in "${RESULTS[@]}"; do
    IFS='|' read -r c iv lv id ay st <<<"$entry"
    comma=","
    ((idx++)) || true
    [[ $idx -eq $total ]] && comma=""
    printf '  {"cask":"%s","installed_version":"%s","latest_version":"%s","installed_date":"%s","age_years":"%s","status":"%s"}%s\n' \
      "$c" "$iv" "$lv" "$id" "$ay" "$st" "$comma"
  done
  echo "]"
else
  if ! $QUIET; then
    # Table header
    printf "${BOLD}%-35s %-20s %-20s %-12s %-10s %s${RESET}\n" \
      "CASK" "INSTALLED VER" "LATEST VER" "SINCE" "LIB-YRS" "STATUS"
    printf '%s\n' "$(printf '─%.0s' {1..110})"

    for entry in "${RESULTS[@]}"; do
      IFS='|' read -r c iv lv id ay st <<<"$entry"

      case "$st" in
      CRITICAL)
        colour="$RED"
        icon="✖"
        ;;
      WARN)
        colour="$YELLOW"
        icon="⚠"
        ;;
      OK)
        colour="$GREEN"
        icon="✔"
        ;;
      *)
        colour=""
        icon="?"
        ;;
      esac

      printf "${colour}%-35s %-20s %-20s %-12s %-10s %s %s${RESET}\n" \
        "$c" "$iv" "$lv" "$id" "$ay" "$icon" "$st"
    done

    printf '%s\n' "$(printf '─%.0s' {1..110})"

    # Summary
    echo ""
    echo -e "  ${RED}${BOLD}Critical (≥${MAX_YEARS}y):${RESET}  ${CRITICAL_COUNT}"
    echo -e "  ${YELLOW}${BOLD}Warning  (≥${WARN_YEARS}y):${RESET}  ${WARN_COUNT}"
    echo -e "  ${GREEN}${BOLD}OK               :${RESET}  ${OK_COUNT}"
    echo ""

    if [[ $CRITICAL_COUNT -gt 0 ]]; then
      echo -e "${RED}${BOLD}⚠  ${CRITICAL_COUNT} cask(s) are more than ${MAX_YEARS} year(s) out of date. Please update them.${RESET}"
    else
      echo -e "${GREEN}${BOLD}✓  No casks exceed the ${MAX_YEARS}-year threshold.${RESET}"
    fi
    echo ""
  fi
fi

# Exit non-zero if any criticals
[[ $CRITICAL_COUNT -gt 0 ]] && exit 1 || exit 0
