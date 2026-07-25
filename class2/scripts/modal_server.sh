
exec "$(dirname "$0")/modal.sh" "${1:-help}" "${2:-naive-server}" "${@:3}"
