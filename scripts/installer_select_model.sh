#!/usr/bin/env bash
set -euo pipefail

TARGET_ROOT="${1:-/target}"
OUT_FILE="${2:-$TARGET_ROOT/etc/aegis/install-selections.env}"
CATALOG_PATH="${AEGIS_MODEL_CATALOG:-$TARGET_ROOT/etc/aegis/model_catalog.json}"
AEGISOS_ROOT="${AEGISOS_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

choose_with_whiptail() {
  local title="$1"
  local prompt="$2"
  shift 2
  whiptail --title "$title" --menu "$prompt" 20 88 10 "$@" 3>&1 1>&2 2>&3
}

choose_with_dialog() {
  local title="$1"
  local prompt="$2"
  shift 2
  dialog --stdout --title "$title" --menu "$prompt" 20 88 10 "$@"
}

plain_choice() {
  local prompt="$1"
  shift
  local default="$1"
  shift
  echo "$prompt"
  local i=1
  for row in "$@"; do
    echo "  $i) $row"
    i=$((i + 1))
  done
  read -r -p "Choose [$default]: " raw
  raw="${raw:-$default}"
  echo "$raw"
}

map_choice() {
  local idx="$1"
  shift
  local entries=("$@")
  local n="${#entries[@]}"
  if [[ "$idx" =~ ^[0-9]+$ ]] && (( idx >= 1 && idx <= n )); then
    echo "${entries[$((idx - 1))]}"
    return 0
  fi
  echo "${entries[0]}"
}

perm_ids=(strict prompt_once balanced open)

load_profiles_from_catalog() {
  if [[ ! -f "$CATALOG_PATH" ]] || ! command -v python3 >/dev/null 2>&1; then
    return 1
  fi

  local rows
  if ! rows="$(python3 - "$CATALOG_PATH" "$AEGISOS_ROOT" <<'PY'
import json
import os
import pathlib
import sys

catalog_path = pathlib.Path(sys.argv[1])
source_root = pathlib.Path(sys.argv[2])
sys.path.insert(0, str(source_root))

try:
    from aegis.llm.model_discovery import discover_model_profiles
except Exception:
    discover_model_profiles = None

def load_catalog_rows(path: pathlib.Path):
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("profiles", []))

def norm(value: str) -> str:
    return value.strip().lower()

def infer_provider(repo: str) -> str:
    repo = norm(repo)
    if "deepseek" in repo:
        return "deepseek"
    if "mistral" in repo:
        return "mistral"
    if "qwen" in repo:
        return "qwen"
    if "llama" in repo:
        return "llama"
    return "unknown"

def infer_size(item: dict) -> str:
    for key in ("model_size", "size", "parameter_count", "profile_id"):
        raw = str(item.get(key, "")).strip()
        if raw:
            break
    else:
        raw = "unknown"

    raw = norm(raw).replace(" ", "")
    aliases = {"small": "1.5b", "medium": "7b", "large": "14b"}
    return aliases.get(raw, raw)

  def to_bool(value):
    if isinstance(value, bool):
      return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

  profiles = load_catalog_rows(catalog_path)
  dynamic_enabled = str(os.getenv("AEGIS_DYNAMIC_MODEL_DISCOVERY", "1")).strip().lower() in {"1", "true", "yes", "on"}
  timeout_s = float(os.getenv("AEGIS_MODEL_DISCOVERY_TIMEOUT_SECONDS", "5"))
  if dynamic_enabled and discover_model_profiles is not None:
    profiles = discover_model_profiles(existing_profiles=profiles, timeout_s=timeout_s)

  for item in profiles:
    profile_id = str(item.get("profile_id", "")).strip()
    if not profile_id:
        continue
    provider = str(item.get("provider", "")).strip() or infer_provider(str(item.get("repo", "")))
    model_size = infer_size(item)
    label = str(item.get("label", profile_id)).replace("\t", " ").replace("\n", " ")
    min_ram = str(item.get("min_ram_gb", "?"))
    params = str(item.get("parameter_count", "unknown"))
    min_cpu = str(item.get("min_cpu_cores", "4"))
    min_storage = str(item.get("min_storage_gb", item.get("min_rom_gb", "8")))
    requires_gpu = "1" if to_bool(item.get("requires_gpu", False)) else "0"
    min_vram = str(item.get("min_vram_gb", "0"))
    description = str(item.get("description", "")).replace("\t", " ").replace("\n", " ")
    print("\t".join([profile_id, provider, model_size, label, min_ram, params, min_cpu, min_storage, requires_gpu, min_vram, description]))
PY
)"; then
    return 1
  fi

  if [[ -z "$rows" ]]; then
    return 1
  fi

  PROFILE_IDS=()
  PROFILE_PROVIDERS=()
  PROFILE_SIZES=()
  PROFILE_LABELS=()
  PROFILE_RAM=()
  PROFILE_PARAMS=()
  PROFILE_CPU=()
  PROFILE_STORAGE=()
  PROFILE_GPU=()
  PROFILE_VRAM=()
  PROFILE_DESCRIPTION=()

  while IFS=$'\t' read -r profile_id provider model_size label min_ram params min_cpu min_storage requires_gpu min_vram description; do
    PROFILE_IDS+=("$profile_id")
    PROFILE_PROVIDERS+=("$provider")
    PROFILE_SIZES+=("$model_size")
    PROFILE_LABELS+=("$label")
    PROFILE_RAM+=("$min_ram")
    PROFILE_PARAMS+=("$params")
    PROFILE_CPU+=("$min_cpu")
    PROFILE_STORAGE+=("$min_storage")
    PROFILE_GPU+=("$requires_gpu")
    PROFILE_VRAM+=("$min_vram")
    PROFILE_DESCRIPTION+=("$description")
  done <<< "$rows"

  return 0
}

setup_fallback_profiles() {
  PROFILE_IDS=(small medium large)
  PROFILE_PROVIDERS=(deepseek deepseek deepseek)
  PROFILE_SIZES=(1.5b 7b 14b)
  PROFILE_LABELS=(
    "DeepSeek 1.5B (fastest)"
    "DeepSeek 7B (balanced)"
    "DeepSeek 14B (best quality)"
  )
  PROFILE_RAM=(8 16 32)
  PROFILE_PARAMS=(1.5B 7B 14B)
  PROFILE_CPU=(4 8 12)
  PROFILE_STORAGE=(3 6 10)
  PROFILE_GPU=(0 0 1)
  PROFILE_VRAM=(0 0 10)
  PROFILE_DESCRIPTION=(
    "Low memory footprint and fast startup."
    "Balanced quality and latency for daily use."
    "Higher quality with larger hardware requirements."
  )
}

profile_index_by_id() {
  local wanted="$1"
  local i
  for ((i = 0; i < ${#PROFILE_IDS[@]}; i++)); do
    if [[ "${PROFILE_IDS[$i]}" == "$wanted" ]]; then
      echo "$i"
      return 0
    fi
  done
  echo "-1"
}

provider_list() {
  local providers=()
  local provider
  for provider in "${PROFILE_PROVIDERS[@]}"; do
    local seen=0
    local p
    for p in "${providers[@]}"; do
      if [[ "$p" == "$provider" ]]; then
        seen=1
        break
      fi
    done
    if [[ "$seen" -eq 0 ]]; then
      providers+=("$provider")
    fi
  done
  echo "${providers[*]}"
}

profile_ids_for_provider() {
  local provider="$1"
  local ids=()
  local i
  for ((i = 0; i < ${#PROFILE_IDS[@]}; i++)); do
    if [[ "${PROFILE_PROVIDERS[$i]}" == "$provider" ]]; then
      ids+=("${PROFILE_IDS[$i]}")
    fi
  done
  echo "${ids[*]}"
}

if ! load_profiles_from_catalog; then
  setup_fallback_profiles
fi

perm_tags=(
  "strict" "Strict: minimal grants"
  "prompt_once" "Prompt Once: ask once per sensitive action"
  "balanced" "Balanced: common actions pre-granted"
  "open" "Open: broad local automation"
)

DEFAULT_PROFILE="medium"
DEFAULT_PROVIDER="deepseek"
DEFAULT_MODEL_SIZE="7b"

default_idx="$(profile_index_by_id "$DEFAULT_PROFILE")"
if [[ "$default_idx" != "-1" ]]; then
  DEFAULT_PROVIDER="${PROFILE_PROVIDERS[$default_idx]}"
  DEFAULT_MODEL_SIZE="${PROFILE_SIZES[$default_idx]}"
fi

MODEL_PROFILE=""
MODEL_PROVIDER=""
MODEL_SIZE=""
PERM_PROFILE=""

providers_str="$(provider_list)"
read -r -a PROVIDERS <<< "$providers_str"

provider_tags=()
for provider in "${PROVIDERS[@]}"; do
  provider_tags+=("$provider" "Provider: $provider")
done

choose_size_for_provider() {
  local provider="$1"
  local ids_str
  ids_str="$(profile_ids_for_provider "$provider")"
  read -r -a ids <<< "$ids_str"
  if [[ ${#ids[@]} -eq 0 ]]; then
    echo ""
    return 0
  fi

  local tags=()
  local id
  for id in "${ids[@]}"; do
    local idx
    idx="$(profile_index_by_id "$id")"
    if [[ "$idx" == "-1" ]]; then
      continue
    fi
    tags+=(
      "$id"
      "size=${PROFILE_SIZES[$idx]} params=${PROFILE_PARAMS[$idx]} ram=${PROFILE_RAM[$idx]}GB cpu=${PROFILE_CPU[$idx]} storage=${PROFILE_STORAGE[$idx]}GB"
    )
  done

  if command -v whiptail >/dev/null 2>&1 && [[ -t 1 ]]; then
    choose_with_whiptail "AegisOS Model Size Selection" "Select model size for provider '$provider'" "${tags[@]}"
    return 0
  fi

  if command -v dialog >/dev/null 2>&1 && [[ -t 1 ]]; then
    choose_with_dialog "AegisOS Model Size Selection" "Select model size for provider '$provider'" "${tags[@]}"
    return 0
  fi

  local options=()
  local i
  for ((i = 0; i < ${#ids[@]}; i++)); do
    options+=("${PROFILE_SIZES[$(profile_index_by_id "${ids[$i]}")]}")
  done
  local idx_raw
  idx_raw="$(plain_choice "AegisOS installer model size for provider '$provider':" 1 "${options[@]}")"
  map_choice "$idx_raw" "${ids[@]}"
}

if command -v whiptail >/dev/null 2>&1 && [[ -t 1 ]]; then
  MODEL_PROVIDER="$(choose_with_whiptail "AegisOS Model Provider Selection" "Select model provider" "${provider_tags[@]}")"
  MODEL_PROFILE="$(choose_size_for_provider "$MODEL_PROVIDER")"
  PERM_PROFILE="$(choose_with_whiptail "AegisOS Permission Selection" "Select permission profile" "${perm_tags[@]}")"
elif command -v dialog >/dev/null 2>&1 && [[ -t 1 ]]; then
  MODEL_PROVIDER="$(choose_with_dialog "AegisOS Model Provider Selection" "Select model provider" "${provider_tags[@]}")"
  MODEL_PROFILE="$(choose_size_for_provider "$MODEL_PROVIDER")"
  PERM_PROFILE="$(choose_with_dialog "AegisOS Permission Selection" "Select permission profile" "${perm_tags[@]}")"
else
  provider_idx="$(plain_choice "AegisOS installer model provider:" 1 "${PROVIDERS[@]}")"
  MODEL_PROVIDER="$(map_choice "$provider_idx" "${PROVIDERS[@]}")"
  MODEL_PROFILE="$(choose_size_for_provider "$MODEL_PROVIDER")"
  perm_idx="$(plain_choice "AegisOS installer permission profile:" 2 "strict" "prompt_once" "balanced" "open")"
  PERM_PROFILE="$(map_choice "$perm_idx" "${perm_ids[@]}")"
fi

if [[ -z "$MODEL_PROFILE" ]]; then
  MODEL_PROFILE="$DEFAULT_PROFILE"
fi

selected_idx="$(profile_index_by_id "$MODEL_PROFILE")"
if [[ "$selected_idx" == "-1" ]]; then
  selected_idx="$(profile_index_by_id "$DEFAULT_PROFILE")"
fi

if [[ "$selected_idx" != "-1" ]]; then
  MODEL_PROVIDER="${PROFILE_PROVIDERS[$selected_idx]}"
  MODEL_SIZE="${PROFILE_SIZES[$selected_idx]}"
  GPU_TEXT="not required"
  if [[ "${PROFILE_GPU[$selected_idx]}" == "1" ]]; then
    GPU_TEXT="required (${PROFILE_VRAM[$selected_idx]}GB VRAM minimum)"
  fi
  echo "Spec Requirement Bar: RAM>=${PROFILE_RAM[$selected_idx]}GB | ROM>=${PROFILE_STORAGE[$selected_idx]}GB | CPU>=${PROFILE_CPU[$selected_idx]} cores | GPU=${GPU_TEXT} | Storage>=${PROFILE_STORAGE[$selected_idx]}GB"
else
  MODEL_PROVIDER="$DEFAULT_PROVIDER"
  MODEL_SIZE="$DEFAULT_MODEL_SIZE"
fi

mkdir -p "$(dirname "$OUT_FILE")"
cat > "$OUT_FILE" <<EOF
AEGIS_MODEL_PROVIDER=$MODEL_PROVIDER
AEGIS_MODEL_SIZE=$MODEL_SIZE
AEGIS_MODEL_PROFILE=$MODEL_PROFILE
AEGIS_PERMISSION_PROFILE=$PERM_PROFILE
EOF

echo "Wrote installer selections to $OUT_FILE"
