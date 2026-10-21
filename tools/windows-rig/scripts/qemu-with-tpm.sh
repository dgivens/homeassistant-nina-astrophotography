#!/usr/bin/env bash
# Packer's qemu_binary. It runs qemu-system-aarch64 with Packer's arguments,
# changed in ways that Packer's `qemuargs` cannot make, since that option
# replaces the generated command line rather than adding to it:
#
#   - Packer's CD-ROM drives move to USB storage. The `virt` machine has no
#     IDE or SATA, and WinPE has no virtio driver to read a virtio CD with.
#   - Packer's port forwards bind the loopback interface, not every interface.
#   - A TPM (swtpm, on $SWTPM_SOCK), a framebuffer the firmware and Windows
#     Setup can draw on (ramfb), and a USB keyboard and tablet are added.
#
# The USB controller comes before the drives on it, and the install ISO before
# the answer-file CD: the firmware boots the first USB disc it finds.

set -euo pipefail

if [[ ! -S "${SWTPM_SOCK:-}" ]]; then
  echo "qemu-with-tpm.sh: SWTPM_SOCK is not a socket; rig.py starts swtpm first" >&2
  exit 1
fi

args=()
cds=()
n=0
while (( $# )); do
  if [[ "$1" == "-drive" && "${2:-}" == *"media=cdrom"* ]]; then
    drive="$(sed -E 's/(^|,)(if|index)=[^,]*//g; s/^,//' <<<"$2")"
    args+=(-drive "${drive},if=none,id=cd${n}")
    cds+=(-device "usb-storage,drive=cd${n},bus=usb.0")
    n=$((n + 1))
    shift 2
    continue
  fi
  if [[ "$1" == "-netdev" && "${2:-}" == user,* ]]; then
    args+=(-netdev "${2//hostfwd=tcp::/hostfwd=tcp:127.0.0.1:}")
    shift 2
    continue
  fi
  args+=("$1")
  shift
done

exec qemu-system-aarch64 "${args[@]}" \
  -chardev "socket,id=chrtpm,path=${SWTPM_SOCK}" \
  -tpmdev "emulator,id=tpm0,chardev=chrtpm" \
  -device "tpm-tis-device,tpmdev=tpm0,ppi=off" \
  -device ramfb \
  -device "qemu-xhci,id=usb" \
  -device "usb-kbd,bus=usb.0" \
  -device "usb-tablet,bus=usb.0" \
  ${cds[@]+"${cds[@]}"}
