#!/usr/bin/env bash
# brew-age-check.sh — Flag outdated Homebrew casks and/or formulae by lib-years.
#
# USAGE:
#   ./brew-age-check.sh [--mode casks|formulae|all] [--max-years N] [--warn-years N] [--quiet] [--json]
#
# OPTIONS:
#   --mode MODE      What to check: casks, formulae, or all  (default: all)
#   --max-years N    Packages older than N years are CRITICAL (default: 2)
#   --warn-years N   Packages older than N years are WARNING  (default: 1)
#   --quiet          Suppress table; only exit non-zero if criticals exist
#   --json           Emit JSON instead of a human-readable table
#   -h, --help       Show this help and exit
#
# EXIT CODES:
#   0  All packages are within the max-years threshold
#   1  One or more packages exceed the max-years threshold (CRITICAL)
#   2  Script error (brew not found, etc.)
#
# NOTES:
#   brew outdated --formula --verbose  uses " < "  as separator
#   brew outdated --cask --greedy      uses " != " as separator
#   When a formula has multiple installed versions, the oldest is used
#   (comma + space = multiple versions; comma + no space = part of version token)

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
MAX_YEARS=2
WARN_YEARS=1
QUIET=false
JSON=false
MODE=all # casks | formulae | all

# ── Colours (disabled when not a tty) ─────────────────────────────────────────
if [ -t 1 ]; then
  RED='\033[0;31m'
  YELLOW='\033[0;33m'
  GREEN='\033[0;32m'
  CYAN='\033[0;36m'
  BOLD='\033[1m'
  DIM='\033[2m'
  RESET='\033[0m'
else
  RED=''
  YELLOW=''
  GREEN=''
  CYAN=''
  BOLD=''
  DIM=''
  RESET=''
fi

# ── Argument parsing ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
  --mode)
    MODE="$2"
    case "$MODE" in casks | formulae | all) ;;
    *)
      echo "Error: --mode must be one of: casks, formulae, all" >&2
      exit 2
      ;;
    esac
    shift 2
    ;;
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
if ! command -v bc &>/dev/null; then
  echo "Error: bc not found (needed for date arithmetic)." >&2
  exit 2
fi

# ── Helper: fractional years between two YYYY-MM-DD dates ────────────────────
years_between() {
  local from="$1" to="$2"
  local epoch_from epoch_to
  epoch_from=$(date -j -f "%Y-%m-%d" "$from" "+%s" 2>/dev/null) || {
    echo "0.00"
    return
  }
  epoch_to=$(date -j -f "%Y-%m-%d" "$to" "+%s" 2>/dev/null) || {
    echo "0.00"
    return
  }
  echo "scale=2; ($epoch_to - $epoch_from) / 31557600" | bc | sed 's/^\./0./'
}

# ── Helper: parse one line of brew outdated output ───────────────────────────
# Outputs three tab-separated fields: name \t installed_ver \t latest_ver
#
# Handles:
#   name (installed) < latest          formulae, single version
#   name (ver1, ver2) < latest         formulae, multiple installed (comma + space)
#   name (installed) != latest         casks, with parens
#   name installed != latest           casks, without parens
#   name (ver,build) != latest         casks, comma is part of version token (no space after comma)
parse_outdated_line() {
  local line="$1"
  local name sep latest_ver installed_raw installed_ver

  name=$(echo "$line" | sed 's/ .*//')

  # Detect separator
  if echo "$line" | grep -qF " != "; then
    sep="!="
  else
    sep="<"
  fi

  latest_ver=$(echo "$line" | sed "s/.* ${sep} //")
  installed_raw=$(echo "$line" | sed "s/^${name} //; s/ ${sep} ${latest_ver}//" | tr -d '()')

  # "comma + space" = multiple installed versions → take oldest (first listed)
  # "comma + no space" = comma is part of the version token, keep as-is
  if echo "$installed_raw" | grep -qF ", "; then
    installed_ver=$(echo "$installed_raw" | sed 's/,.*//' | tr -d ' ')
  else
    installed_ver=$(echo "$installed_raw" | tr -d ' ')
  fi

  printf '%s\t%s\t%s' "$name" "$installed_ver" "$latest_ver"
}

# ── Helper: find the tap .rb file for a package ──────────────────────────────
find_rb_file() {
  local name="$1" type="$2"
  local first_char rb_file
  first_char=$(echo "$name" | cut -c1)

  if [[ "$type" == "cask" ]]; then
    rb_file="$(brew --repository)/Library/Taps/homebrew/homebrew-cask/Casks/${first_char}/${name}.rb"
  else
    rb_file="$(brew --repository)/Library/Taps/homebrew/homebrew-core/Formula/${first_char}/${name}.rb"
    if [[ ! -f "$rb_file" ]]; then
      rb_file="$(brew --repository)/Library/Taps/homebrew/homebrew-core/Formula/${name}.rb"
    fi
  fi

  if [[ ! -f "$rb_file" ]]; then
    rb_file=$(find "$(brew --repository)/Library/Taps" -name "${name}.rb" 2>/dev/null | head -1)
  fi

  echo "${rb_file:-}"
}

# ── Helper: date when a version was introduced in the tap ────────────────────
get_version_date() {
  local name="$1" target_version="$2" type="$3"

  # Strategy 1: git log on the tap .rb file
  local rb_file
  rb_file=$(find_rb_file "$name" "$type")

  if [[ -n "$rb_file" && -f "$rb_file" ]]; then
    local version_date
    version_date=$(git -C "$(dirname "$rb_file")" log \
      --reverse --format="%as" \
      -S "$target_version" \
      -- "$rb_file" 2>/dev/null |
      head -1)
    if [[ -n "$version_date" ]]; then
      echo "$version_date"
      return
    fi
  fi

  # Strategy 2: receipt directory mtime (date you installed this version)
  local receipt_dir
  if [[ "$type" == "cask" ]]; then
    receipt_dir="$(brew --prefix)/Caskroom/${name}/${target_version}"
  else
    receipt_dir="$(brew --prefix)/Cellar/${name}/${target_version}"
  fi

  if [[ -d "$receipt_dir" ]]; then
    local mtime
    mtime=$(stat -f "%Sm" -t "%Y-%m-%d" "$receipt_dir" 2>/dev/null)
    [[ -n "$mtime" ]] && {
      echo "$mtime"
      return
    }
  fi

  echo "" # unknown
}

# ── Helper: process one batch of brew outdated output ────────────────────────
process_batch() {
  local type="$1" outdated="$2"

  while IFS= read -r line; do
    [[ -z "$line" ]] && continue

    local fields name installed_ver latest_ver
    fields=$(parse_outdated_line "$line")
    name=$(printf '%s' "$fields" | cut -f1)
    installed_ver=$(printf '%s' "$fields" | cut -f2)
    latest_ver=$(printf '%s' "$fields" | cut -f3)

    # Skip lines that failed to parse (separator not found → latest_ver = whole line)
    if [[ "$latest_ver" == "$line" || -z "$installed_ver" ]]; then
      continue
    fi

    local installed_date age_years status
    installed_date=$(get_version_date "$name" "$installed_ver" "$type")

    if [[ -z "$installed_date" ]]; then
      age_years="?"
      status="UNKNOWN"
    else
      age_years=$(years_between "$installed_date" "$TODAY")
      local is_critical is_warn
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

    RESULTS+=("${type}|${name}|${installed_ver}|${latest_ver}|${installed_date:-unknown}|${age_years}|${status}")
  done <<<"$outdated"
}

# ── Main ──────────────────────────────────────────────────────────────────────
TODAY=$(date "+%Y-%m-%d")

$QUIET || echo -e "\n${BOLD}${CYAN}🍺  Checking outdated packages (mode: ${MODE})…${RESET}\n"

declare -a RESULTS=()
CRITICAL_COUNT=0
WARN_COUNT=0
OK_COUNT=0

if [[ "$MODE" == "casks" || "$MODE" == "all" ]]; then
  OUTDATED_CASKS=$(brew outdated --cask --greedy --verbose 2>/dev/null) || true
  [[ -n "$OUTDATED_CASKS" ]] && process_batch "cask" "$OUTDATED_CASKS"
fi

if [[ "$MODE" == "formulae" || "$MODE" == "all" ]]; then
  # --formula explicitly excludes casks from the output
  OUTDATED_FORMULAE=$(brew outdated --formula --verbose 2>/dev/null) || true
  [[ -n "$OUTDATED_FORMULAE" ]] && process_batch "formula" "$OUTDATED_FORMULAE"
fi

if [[ ${#RESULTS[@]} -eq 0 ]]; then
  $QUIET || echo -e "${GREEN}✓ All packages are up to date.${RESET}\n"
  exit 0
fi

# ── Output ────────────────────────────────────────────────────────────────────
if $JSON; then
  echo "["
  local_total=${#RESULTS[@]}
  local_idx=0
  for entry in "${RESULTS[@]}"; do
    IFS='|' read -r typ nm iv lv id ay st <<<"$entry"
    comma=","
    ((local_idx++)) || true
    [[ $local_idx -eq $local_total ]] && comma=""
    printf '  {"type":"%s","name":"%s","installed_version":"%s","latest_version":"%s","installed_date":"%s","age_years":"%s","status":"%s"}%s\n' \
      "$typ" "$nm" "$iv" "$lv" "$id" "$ay" "$st" "$comma"
  done
  echo "]"
else
  if ! $QUIET; then
    local_last_type=""
    local_sep_len=110

    if [[ "$MODE" == "all" ]]; then
      local_sep_len=120
      printf "${BOLD}%-8s %-33s %-20s %-20s %-12s %-10s %s${RESET}\n" \
        "TYPE" "PACKAGE" "INSTALLED VER" "LATEST VER" "SINCE" "LIB-YRS" "STATUS"
    else
      printf "${BOLD}%-35s %-20s %-20s %-12s %-10s %s${RESET}\n" \
        "PACKAGE" "INSTALLED VER" "LATEST VER" "SINCE" "LIB-YRS" "STATUS"
    fi
    printf '%s\n' "$(printf '─%.0s' $(seq 1 $local_sep_len))"

    for entry in "${RESULTS[@]}"; do
      IFS='|' read -r typ nm iv lv id ay st <<<"$entry"

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
        colour="$DIM"
        icon="?"
        ;;
      esac

      if [[ "$MODE" == "all" ]]; then
        if [[ -n "$local_last_type" && "$typ" != "$local_last_type" ]]; then
          printf '%s\n' "$(printf '·%.0s' $(seq 1 $local_sep_len))"
        fi
        local_last_type="$typ"
        printf "${colour}%-8s %-33s %-20s %-20s %-12s %-10s %s %s${RESET}\n" \
          "$typ" "$nm" "$iv" "$lv" "$id" "$ay" "$icon" "$st"
      else
        printf "${colour}%-35s %-20s %-20s %-12s %-10s %s %s${RESET}\n" \
          "$nm" "$iv" "$lv" "$id" "$ay" "$icon" "$st"
      fi
    done

    printf '%s\n' "$(printf '─%.0s' $(seq 1 $local_sep_len))"
    echo ""
    echo -e "  ${RED}${BOLD}Critical (≥${MAX_YEARS}y):${RESET}  ${CRITICAL_COUNT}"
    echo -e "  ${YELLOW}${BOLD}Warning  (≥${WARN_YEARS}y):${RESET}  ${WARN_COUNT}"
    echo -e "  ${GREEN}${BOLD}OK               :${RESET}  ${OK_COUNT}"
    echo ""

    if [[ $CRITICAL_COUNT -gt 0 ]]; then
      echo -e "${RED}${BOLD}⚠  ${CRITICAL_COUNT} package(s) are more than ${MAX_YEARS} year(s) out of date. Please update them.${RESET}"
    else
      echo -e "${GREEN}${BOLD}✓  No packages exceed the ${MAX_YEARS}-year threshold.${RESET}"
    fi
    echo ""
  fi
fi

[[ $CRITICAL_COUNT -gt 0 ]] && exit 1 || exit 0
